# -*- coding: utf-8 -*-
"""
utils/xml_builder.py

Tally Prime XML Envelope builder for Odoo 19 Tally Connector.

KEY SIGN CONVENTION (Critical — do NOT change):
    Tally uses an inverted sign convention in ledger entry AMOUNT tags:
        Debit entry  → AMOUNT is NEGATIVE  (e.g., -10000.00)
        Credit entry → AMOUNT is POSITIVE  (e.g.,  10000.00)

    This is the opposite of normal accounting intuition and the #1 cause
    of wrong postings in Tally integrations. This module enforces the rule
    strictly via _get_tally_amount() and _is_deemed_positive().

XML References:
    - Tally Developer Reference: ENVELOPE > BODY > IMPORTDATA
    - Voucher import uses REPORTNAME = "Vouchers"
    - Master import uses REPORTNAME = "All Masters"
"""

import json
import os
import re
from calendar import monthrange
from datetime import date, datetime
from xml.etree import ElementTree as ET
from xml.dom import minidom
import logging

from odoo import fields

_logger = logging.getLogger(__name__)
_logger.info(
    '[odoo_tally_connector] xml_builder loaded (voucher import uses SVFROMDATE/SVTODATE YYYYMMDD)'
)

# XML 1.0 forbids most C0 control chars (incl. Tally's legacy &#4; prefix).
_INVALID_XML_CHAR_RE = re.compile(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x84\x86-\x9F]')


def _sanitize_xml_text(value):
    """Strip characters that break XML 1.0 parsers and Tally export viewers."""
    if value is None:
        return ''
    return _INVALID_XML_CHAR_RE.sub('', str(value))


def _partner_phone_for_tally(partner):
    """Return the partner's mobile number, falling back to the phone number."""
    phone = (getattr(partner, 'phone', None) or '').strip()
    mobile = str(getattr(partner, 'mobile', None) or '').strip()
    return mobile or phone


def _partner_isd_code_for_tally(partner):
    """Return Tally's expected country ISD code format."""
    if partner.country_id and partner.country_id.phone_code:
        return f"+{partner.country_id.phone_code}"
    return '+91'


def _party_name_for_move(move):
    """Resolve the Tally party ledger name for this document."""
    if not move.partner_id:
        return ''
    return (move.partner_id.name or '').strip()[:100]


def _coerce_to_date(value):
    """Normalize Odoo date/datetime values to ``datetime.date`` for Tally YYYYMMDD tags."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return None


def _voucher_accounting_date(move):
    """Date for Tally voucher DATE tag — never None (Tally rejects empty voucher date)."""
    d = _coerce_to_date(getattr(move, 'invoice_date', None)) or _coerce_to_date(
        getattr(move, 'date', None)
    )
    if d:
        return d
    line_date = move.env['account.move.line'].sudo().search(
        [('move_id', '=', move.id), ('date', '!=', False)],
        limit=1,
        order='id',
    ).date
    line_date = _coerce_to_date(line_date)
    if line_date:
        return line_date
    return fields.Date.context_today(move)


def _voucher_narration_text(move):
    """Voucher narration containing every product."""
    narration_parts = []
    base_narration = (move.narration or move.payment_reference or '').strip()
    if base_narration:
        narration_parts.append(base_narration)

    invoice_lines = getattr(move, 'invoice_line_ids', None)
    if invoice_lines:
        product_lines = invoice_lines.filtered(
            lambda line: _is_stock_invoice_line(line)
        )
        for number, line in enumerate(product_lines, start=1):
            product_text = (getattr(line, 'name', '') or line.product_id.name or '').strip()
            product_text = ' '.join(product_text.split())
            qty = (
                getattr(line, 'quantity', 0.0)
                or getattr(line, 'product_uom_qty', 0.0)
                or getattr(line, 'product_qty', 0.0)
            )
            uom = getattr(line, 'product_uom_id', False) or getattr(line, 'product_uom', False)
            uom_name = (getattr(uom, 'name', '') or '').strip()
            narration_parts.append(
                f'{number}. Qty: {qty:g} {uom_name} | {product_text}'
            )

    return '; '.join(narration_parts) or (move.name or '')


def _voucher_reference_text(move):
    """REFERENCE tag for account.move."""
    return (move.ref or move.payment_reference or move.name or '').strip()


_TALLY_TRANSPORT_MODES = {
    '1': 'Road',
    '2': 'Rail',
    '3': 'Air',
    '4': 'Ship',
}

_TALLY_VEHICLE_TYPES = {
    'R': 'Regular',
    'O': 'Over Dimensional Cargo',
}

_TALLY_VEHICLE_TYPE_CODES = {
    'R': 'R',
    'O': 'O',
}


def _partner_commune_value(partner):
    """
    Odoo address label "Commune" is stored on ``city`` (or a custom commune field).
  """
    if not partner:
        return ''
    for field_name in ('commune', 'x_commune', 'l10n_commune', 'city'):
        if field_name not in partner._fields:
            continue
        value = getattr(partner, field_name, None)
        if value and str(value).strip():
            return str(value).strip()[:50]
    return ''


def _partner_place_label(partner):
    """Place / locality for Tally e-Way Bill (Commune / city first)."""
    if not partner:
        return ''
    commune = _partner_commune_value(partner)
    if commune:
        return commune
    street2 = (partner.street2 or '').strip()
    if street2:
        return street2[:50]
    if partner.state_id:
        return partner.state_id.name.split('(')[0].strip()[:50]
    return (partner.name or '').strip()[:50]


def _resolve_ewaybill_partners(move, ewaybill):
    """Resolve dispatch / ship / bill partners with Odoo e-Way Bill fallbacks."""
    if not ewaybill:
        return None, None, None
    ship_from = ewaybill.partner_ship_from_id
    ship_to = ewaybill.partner_ship_to_id
    bill_to = ewaybill.partner_bill_to_id
    linked_move = ewaybill.account_move_id or move
    if linked_move and not ship_from:
        ship_from = linked_move.partner_shipping_id or linked_move.partner_id
    if linked_move and not ship_to:
        warehouse_partner = False
        if hasattr(linked_move, '_l10n_in_get_warehouse_address'):
            try:
                warehouse_partner = linked_move._l10n_in_get_warehouse_address()
            except Exception:
                warehouse_partner = False
        ship_to = warehouse_partner or linked_move.company_id.partner_id
    if linked_move and not bill_to:
        bill_to = linked_move.partner_id
    return ship_from, ship_to, bill_to


def _append_ewaybill_place_tags(target, dispatch_place, ship_place):
    """Write place tags Tally may read for Dispatch from / Ship to."""
    if dispatch_place:
        for tag in (
            'DISPATCHFROMPLACE',
            'FROMPLACE',
            'DISPATCHFROM',
            'CONSIGNORPLACE',
        ):
            _sub(target, tag, dispatch_place)
    if ship_place:
        for tag in (
            'SHIPTOPLACE',
            'TOPLACE',
            'SHIPTO',
            'CONSIGNEEPLACE',
        ):
            _sub(target, tag, ship_place)


def _partner_lookup_chain(partner):
    """Partner records to read address/GST fields from (self, commercial, parent)."""
    if not partner:
        return []
    seen = set()
    chain = []
    for candidate in (
        partner,
        getattr(partner, 'commercial_partner_id', None),
        getattr(partner, 'parent_id', None),
    ):
        if candidate and candidate.id not in seen:
            seen.add(candidate.id)
            chain.append(candidate)
    return chain


def _partner_state_label(partner):
    for candidate in _partner_lookup_chain(partner):
        if candidate.state_id:
            return candidate.state_id.name.split('(')[0].strip()
    return ''


def _partner_country_label(partner):
    for candidate in _partner_lookup_chain(partner):
        if candidate.country_id:
            return candidate.country_id.name
    return ''


def _partner_gstin(partner):
    for candidate in _partner_lookup_chain(partner):
        gstin = (getattr(candidate, 'vat', None) or '').strip()
        if gstin:
            return gstin
    return ''


def _partner_pincode(partner):
    for candidate in _partner_lookup_chain(partner):
        pin = (candidate.zip or '').strip()
        if pin:
            return pin
    return ''


def _tally_fy_applicable_from():
    today_val = date.today()
    fy_year = today_val.year if today_val.month >= 4 else today_val.year - 1
    return f'{fy_year}0401'


def _move_bill_to_partner(move):
    """Invoice customer / bill-to partner."""
    return getattr(move, 'partner_id', None)


def _move_ship_to_partner(move):
    """Invoice delivery address partner."""
    ship = getattr(move, 'partner_shipping_id', None)
    if ship:
        return ship
    return _move_bill_to_partner(move)


def _tally_gst_registration_type(move, partner):
    """Map Odoo GST treatment to Tally registration type label."""
    treatment = getattr(move, 'l10n_in_gst_treatment', None) or getattr(
        partner, 'l10n_in_gst_treatment', None
    )
    mapping = {
        'regular': 'Regular',
        'composition': 'Composition',
        'unregistered': 'Unregistered',
        'consumer': 'Consumer',
        'overseas': 'Overseas',
        'special_economic_zone': 'Special Economic Zone',
        'deemed_export': 'Deemed Export',
        'uin_holders': 'UIN Holders',
    }
    return mapping.get(treatment, '')


def _move_place_of_supply_name(move):
    """Place of supply from Odoo invoice (l10n_in_state_id)."""
    pos_state = getattr(move, 'l10n_in_state_id', None)
    if pos_state and pos_state.name:
        return pos_state.name.split('(')[0].strip()
    ship = _move_ship_to_partner(move)
    if ship and ship.country_id and ship.country_id.code != 'IN':
        return 'Foreign Country'
    return _partner_state_label(ship) or _partner_state_label(_move_bill_to_partner(move))


def _partner_own_address_lines(partner):
    """Street/city from this partner record only (no parent fallback)."""
    if not partner:
        return []
    lines = []
    if partner.street:
        lines.append(partner.street.strip()[:120])
    if partner.street2:
        lines.append(partner.street2.strip()[:120])
    city_line = (partner.city or '').strip()
    if city_line and city_line not in lines:
        lines.append(city_line[:120])
    return lines[:3]


def _partner_display_address_lines(partner):
    """Address lines as Odoo shows on invoices (contact/inherited address)."""
    if not partner:
        return []
    text = ''
    try:
        text = (getattr(partner, 'contact_address', None) or '').strip()
        if not text:
            text = partner._display_address(without_company=True)
    except Exception:
        text = ''
    if not text:
        return []
    lines = []
    for raw in text.replace('\r\n', '\n').split('\n'):
        line = raw.strip()
        if line and line not in lines:
            lines.append(line[:120])
    return lines[:3]


def _partner_consignee_address_lines(partner, bill_partner=None):
    """Delivery address lines for Tally consignee (ship-to partner first)."""
    if not partner:
        return []
    own = _partner_own_address_lines(partner)
    if own:
        return own
    if bill_partner and partner.id != bill_partner.id:
        display = _partner_display_address_lines(partner)
        if display:
            name = (partner.name or '').strip()
            if len(display) > 1 and name and display[0].strip() == name:
                display = display[1:]
            return display
        return []
    display = _partner_display_address_lines(partner)
    if display:
        name = (partner.name or '').strip()
        if len(display) > 1 and name and display[0].strip() == name:
            display = display[1:]
        return display
    return _partner_address_lines(partner)


def _move_consignee_address_lines(move):
    """Consignee address lines from invoice delivery partner only."""
    ship_partner = _move_ship_to_partner(move)
    if not ship_partner:
        return []
    return _partner_consignee_address_lines(
        ship_partner, bill_partner=_move_bill_to_partner(move),
    )


def _append_address_lines(parent, list_tag, item_tag, lines):
    """Append a Tally string list from pre-built address lines."""
    if not lines:
        return False
    addr_list = ET.SubElement(parent, list_tag)
    addr_list.set('TYPE', 'String')
    for line in lines:
        _sub(addr_list, item_tag, line)
    return True


def _partner_address_lines(partner):
    """Up to three address lines for Tally buyer ADDRESS lists."""
    for candidate in _partner_lookup_chain(partner):
        lines = _partner_own_address_lines(candidate)
        if lines:
            return lines[:3]
    return []


def _resolve_consignee_ledger_name(move):
    """Tally consignee party ledger (Ship to A/c) from delivery partner."""
    bill_partner = _move_bill_to_partner(move)
    ship_partner = _move_ship_to_partner(move)
    if bill_partner and ship_partner and ship_partner.id != bill_partner.id:
        return (ship_partner.name or '').strip()[:100]
    if bill_partner:
        return (bill_partner.name or '').strip()[:100]
    return ''


def _partner_address_source(partner):
    """Partner record whose street/city supplied the address lines."""
    if not partner:
        return partner
    for candidate in _partner_lookup_chain(partner):
        if _partner_own_address_lines(candidate):
            return candidate
    return partner


def _consignee_geo_details(move):
    """State, country, and pincode for Tally consignee (delivery partner only)."""
    bill_partner = _move_bill_to_partner(move)
    ship_partner = _move_ship_to_partner(move) or bill_partner
    if not ship_partner:
        return '', '', ''
    ship_differs = bool(
        bill_partner and ship_partner.id != bill_partner.id
    )
    if ship_differs:
        return (
            _partner_state_label(ship_partner) or _partner_state_for_address(ship_partner),
            _partner_country_label(ship_partner) or _partner_country_for_address(ship_partner),
            _partner_pincode(ship_partner) or _partner_pincode_for_address(ship_partner),
        )
    return (
        _partner_state_label(bill_partner),
        _partner_country_label(bill_partner),
        _partner_pincode(bill_partner),
    )



def _partner_state_for_address(partner):
    return _partner_state_label(_partner_address_source(partner))


def _partner_country_for_address(partner):
    return _partner_country_label(_partner_address_source(partner))


def _partner_pincode_for_address(partner):
    return _partner_pincode(_partner_address_source(partner))


def _append_ledger_multi_address_block(ledger, partner, address_name, bill_partner=None):
    """Add a Tally multiple mailing address block on a party ledger."""
    lines = _partner_own_address_lines(partner)
    if not lines:
        lines = _partner_consignee_address_lines(partner, bill_partner=bill_partner)
    if not lines:
        lines = _partner_display_address_lines(partner)
    if not lines and not address_name:
        return
    multi = ET.SubElement(ledger, 'LEDMULTIADDRESSLIST.LIST')
    if lines:
        addr = ET.SubElement(multi, 'ADDRESS.LIST')
        addr.set('TYPE', 'String')
        for line in lines:
            _sub(addr, 'ADDRESS', line)
    pin = _partner_pincode(partner) or _partner_pincode_for_address(partner)
    if pin:
        _sub(multi, 'PINCODE', pin)
    state = _partner_state_label(partner) or _partner_state_for_address(partner)
    if state:
        _sub(multi, 'STATE', state)
    country = _partner_country_label(partner) or _partner_country_for_address(partner)
    if country:
        _sub(multi, 'COUNTRYNAME', country)
    gstin = _partner_gstin(partner)
    if gstin:
        _sub(multi, 'PARTYGSTIN', gstin)
    if country and country != 'India':
        _sub(multi, 'ISOTHTERRITORYASSESSEE', 'Yes')
    if address_name:
        _sub(multi, 'ADDRESSNAME', address_name[:100])
        _sub(multi, 'MAILINGNAME', address_name[:100])
        _sub(multi, 'CONTACTPERSON', address_name[:100])
    _sub(multi, 'APPLICABLEFROM', _tally_fy_applicable_from())


def _append_named_address_list(parent, list_tag, item_tag, partner):
    """Append a Tally ADDRESS-style list for a partner."""
    lines = _partner_address_lines(partner)
    if not lines:
        return False
    addr_list = ET.SubElement(parent, list_tag)
    addr_list.set('TYPE', 'String')
    for line in lines:
        _sub(addr_list, item_tag, line)
    return True


def _append_buyer_mailing_details(
    voucher,
    partner,
    mailing_name,
    state='',
    country='',
    pin='',
):
    """Buyer mailing block for Tally Party Details (Bill to)."""
    lines = _partner_address_lines(partner)
    if not lines and not mailing_name:
        return
    if not state:
        state = _partner_state_label(partner)
    if not country:
        country = _partner_country_label(partner)
    if not pin:
        pin = _partner_pincode(partner)
    mailing = ET.SubElement(voucher, 'PARTYMAILINGDETAILS.LIST')
    if lines:
        _append_address_lines(mailing, 'ADDRESS.LIST', 'ADDRESS', lines)
        _append_address_lines(
            mailing, 'BASICBUYERADDRESS.LIST', 'BASICBUYERADDRESS', lines
        )
    _sub(mailing, 'APPLICABLEFROM', _tally_fy_applicable_from())
    if mailing_name:
        _sub(mailing, 'MAILINGNAME', mailing_name)
    if state:
        _sub(mailing, 'STATE', state)
    if country:
        _sub(mailing, 'COUNTRY', country)
        _sub(mailing, 'COUNTRYNAME', country)
    if pin:
        _sub(mailing, 'PINCODE', pin)


def _append_consignee_mailing_details(
    voucher,
    partner,
    consignee_ledger,
    mailing_name,
    state='',
    country='',
    pin='',
    address_name='',
    address_lines=None,
):
    """Consignee mailing block for Tally Party Details (Ship to)."""
    lines = address_lines if address_lines is not None else _partner_consignee_address_lines(partner)
    if not lines and not mailing_name and not consignee_ledger:
        return
    if not state:
        state = _partner_state_label(partner) or _partner_state_for_address(partner)
    if not country:
        country = _partner_country_label(partner) or _partner_country_for_address(partner)
    if not pin:
        pin = _partner_pincode(partner) or _partner_pincode_for_address(partner)
    mailing = ET.SubElement(voucher, 'CONSIGNEEMAILINGDETAILS.LIST')
    if lines:
        _append_address_lines(mailing, 'ADDRESS.LIST', 'ADDRESS', lines)
        _append_address_lines(
            mailing, 'CONSIGNEEADDRESS.LIST', 'ADDRESS', lines
        )
        _append_address_lines(
            mailing, 'BASICCONSIGNEEADDRESS.LIST', 'BASICCONSIGNEEADDRESS', lines
        )
    _sub(mailing, 'APPLICABLEFROM', _tally_fy_applicable_from())
    if address_name:
        _sub(mailing, 'ADDRESSNAME', address_name)
    if state:
        _sub(mailing, 'STATE', state)
    if country:
        _sub(mailing, 'COUNTRY', country)
        _sub(mailing, 'COUNTRYNAME', country)
    if pin:
        _sub(mailing, 'PINCODE', pin)
    if mailing_name:
        _sub(mailing, 'MAILINGNAME', mailing_name)
        _sub(mailing, 'CONTACTPERSON', mailing_name)


def _append_consignee_address_lists(voucher, lines):
    """Consignee address lines for Tally Party Details (Ship to)."""
    if not lines:
        return
    _append_address_lines(voucher, 'CONSIGNEEADDRESS.LIST', 'CONSIGNEEADDRESS', lines)
    _append_address_lines(voucher, 'CONSIGNEEADDRESS.LIST', 'ADDRESS', lines)
    _append_address_lines(
        voucher, 'BASICCONSIGNEEADDRESS.LIST', 'BASICCONSIGNEEADDRESS', lines
    )


def _append_buyer_address_lists(voucher, partner):
    """Buyer (Bill to) address lines for Tally Party Details."""
    lines = _partner_address_lines(partner)
    if not lines:
        return
    _append_address_lines(
        voucher, 'BASICBUYERADDRESS.LIST', 'BASICBUYERADDRESS', lines
    )
    _append_address_lines(voucher, 'ADDRESS.LIST', 'ADDRESS', lines)


def _append_voucher_party_address_tail(voucher, move):
    """
    Bill-to address at voucher end while BASICBUYERNAME still points to buyer.

    Use ADDRESS.LIST only here — BASICBUYERADDRESS is written later for ship-to.
    """
    bill_partner = _move_bill_to_partner(move)
    ship_partner = _move_ship_to_partner(move)
    if not bill_partner or not ship_partner:
        return
    if ship_partner.id == bill_partner.id:
        return
    buyer_name = (bill_partner.name or '').strip()[:100]
    buyer_lines = _partner_address_lines(bill_partner)
    if not buyer_lines:
        return
    _sub(voucher, 'BASICBUYERNAME', buyer_name)
    _append_address_lines(voucher, 'ADDRESS.LIST', 'ADDRESS', buyer_lines)


def _append_voucher_consignee_party_details(voucher, move):
    """Map Odoo delivery address to Tally consignee (Ship to) party tags."""
    move_type = getattr(move, 'move_type', '')
    if move_type not in ('out_invoice', 'out_refund', 'out_receipt'):
        return

    bill_partner = _move_bill_to_partner(move)
    ship_partner = _move_ship_to_partner(move) or bill_partner
    if not bill_partner or not ship_partner:
        return

    buyer_name = (bill_partner.name or '').strip()[:100]
    ship_name = (ship_partner.name or '').strip()[:100]
    ship_lines = _move_consignee_address_lines(move)
    ship_differs = ship_partner.id != bill_partner.id
    consignee_ledger = _resolve_consignee_ledger_name(move) if ship_differs else buyer_name
    mailing_name = ship_name or consignee_ledger or buyer_name

    if ship_differs:
        _sub(voucher, 'ISCONSIGNEEASSAME', 'No')
    else:
        _sub(voucher, 'ISCONSIGNEEASSAME', 'Yes')
        return

    ship_state, ship_country, ship_pin = _consignee_geo_details(move)

    # Tally "Consignee (Ship to)" party field maps to voucher BASICBUYERNAME when
    # ISCONSIGNEEASSAME=No. Buyer column uses BASICBASEPARTYNAME / PARTYMAILINGNAME.
    if consignee_ledger:
        _sub(voucher, 'BASICBUYERNAME', consignee_ledger)
        _sub(voucher, 'CONSIGNEEPARTYLEDGERNAME', consignee_ledger)
        _sub(voucher, 'CONSIGNEELEDGERNAME', consignee_ledger)
        _sub(voucher, 'CONSIGNEENAME', consignee_ledger)
        _sub(voucher, 'BASICCONSIGNEENAME', consignee_ledger)
    _sub(voucher, 'CONSIGNEEMAILINGNAME', mailing_name)

    if ship_lines or ship_differs:
        if ship_differs and ship_lines:
            # Consignee column reads BASICBUYERADDRESS after BASICBUYERNAME=ship-to.
            _append_address_lines(
                voucher, 'BASICBUYERADDRESS.LIST', 'BASICBUYERADDRESS', ship_lines
            )
        _append_consignee_address_lists(voucher, ship_lines)
        _append_consignee_mailing_details(
            voucher,
            ship_partner,
            consignee_ledger,
            mailing_name,
            state=ship_state,
            country=ship_country,
            pin=ship_pin,
            address_name='',
            address_lines=ship_lines,
        )

    if ship_state:
        _sub(voucher, 'CONSIGNEESTATENAME', ship_state)
    if ship_country:
        _sub(voucher, 'CONSIGNEECOUNTRYNAME', ship_country)
    if ship_pin:
        _sub(voucher, 'CONSIGNEEPINCODE', ship_pin)
    ship_gstin = _partner_gstin(ship_partner)
    if not ship_gstin and not ship_differs:
        ship_gstin = _partner_gstin(bill_partner)
    if ship_gstin:
        _sub(voucher, 'CONSIGNEEGSTIN', ship_gstin)
    if ship_country and ship_country != 'India':
        _sub(voucher, 'ISCONSIGNEEOTHERTERRITORYASSESSEE', 'Yes')
    elif ship_country == 'United States':
        _sub(voucher, 'ISCONSIGNEEOTHERTERRITORYASSESSEE', 'Yes')

    try:
        from odoo.addons.odoo_tally_connector.utils.tally_http import (
            _agent_debug_log as _agent_dbg,
        )

        _agent_dbg(
            'consignee mapping',
            {
                'move_name': getattr(move, 'name', ''),
                'bill_partner': buyer_name,
                'ship_partner': ship_name,
                'ship_differs': ship_differs,
                'consignee_ledger': consignee_ledger,
                'ship_lines': ship_lines,
                'ship_state': ship_state,
                'ship_country': ship_country,
                'ship_pin': ship_pin,
                'ship_gstin': ship_gstin,
                'own_lines': _partner_own_address_lines(ship_partner),
                'display_lines': _partner_display_address_lines(ship_partner),
            },
            'CONSIGNEE',
            'xml_builder.py:_append_voucher_consignee_party_details',
        )
    except Exception:
        pass


def _append_voucher_invoice_party_details(voucher, move):
    """
    Map Odoo bill-to, delivery address, and place of supply to Tally party tags.
    """
    move_type = getattr(move, 'move_type', '')
    if move_type not in ('out_invoice', 'out_refund', 'out_receipt'):
        return

    bill_partner = _move_bill_to_partner(move)
    if not bill_partner:
        return

    buyer_name = (bill_partner.name or '').strip()[:100]
    ship_partner = _move_ship_to_partner(move)
    ship_differs = bool(
        ship_partner and ship_partner.id != bill_partner.id
    )

    pos_name = _move_place_of_supply_name(move)
    if pos_name:
        _sub(voucher, 'PLACEOFSUPPLY', pos_name)

    _sub(voucher, 'BASICBASEPARTYNAME', buyer_name)
    _sub(voucher, 'PARTYMAILINGNAME', buyer_name)
    # BASICBUYERNAME is used by Tally for Consignee (Ship to) when delivery differs.
    if not ship_differs:
        _sub(voucher, 'BASICBUYERNAME', buyer_name)

    bill_state = _partner_state_label(bill_partner)
    bill_country = _partner_country_label(bill_partner)
    if bill_state:
        _sub(voucher, 'STATENAME', bill_state)
        _sub(voucher, 'BASICFINALDESTINATION', bill_state)
    if bill_country:
        _sub(voucher, 'COUNTRYOFRESIDENCE', bill_country)
        _sub(voucher, 'COUNTRYNAME', bill_country)
    bill_pin = _partner_pincode(bill_partner)
    if bill_pin:
        _sub(voucher, 'PARTYPINCODE', bill_pin)
    bill_gstin = _partner_gstin(bill_partner)
    if bill_gstin:
        _sub(voucher, 'PARTYGSTIN', bill_gstin)
        _sub(voucher, 'GSTIN', bill_gstin)
        _sub(voucher, 'GSTREGISTRATION', bill_gstin)
    reg_type = _tally_gst_registration_type(move, bill_partner)
    if reg_type:
        _sub(voucher, 'GSTREGISTRATIONTYPE', reg_type)
    if not ship_differs:
        _append_buyer_address_lists(voucher, bill_partner)


def _append_voucher_purchase_party_details(voucher, move):
    """Map Odoo vendor and place of supply to Tally purchase invoice tags."""
    move_type = getattr(move, 'move_type', '')
    if move_type not in ('in_invoice', 'in_refund'):
        return

    vendor = move.partner_id
    if not vendor:
        return

    vendor_name = (vendor.name or '').strip()[:100]
    _sub(voucher, 'BASICBASEPARTYNAME', vendor_name)
    _sub(voucher, 'PARTYMAILINGNAME', vendor_name)

    pos_name = _move_place_of_supply_name(move)
    if pos_name:
        _sub(voucher, 'PLACEOFSUPPLY', pos_name)

    vendor_state = _partner_state_label(vendor)
    vendor_country = _partner_country_label(vendor)
    if vendor_state:
        _sub(voucher, 'STATENAME', vendor_state)
        _sub(voucher, 'BASICFINALDESTINATION', vendor_state)
    if vendor_country:
        _sub(voucher, 'COUNTRYOFRESIDENCE', vendor_country)
        _sub(voucher, 'COUNTRYNAME', vendor_country)
    vendor_pin = _partner_pincode(vendor)
    if vendor_pin:
        _sub(voucher, 'PARTYPINCODE', vendor_pin)
    vendor_gstin = _partner_gstin(vendor)
    if vendor_gstin:
        _sub(voucher, 'PARTYGSTIN', vendor_gstin)
        _sub(voucher, 'GSTIN', vendor_gstin)
        _sub(voucher, 'GSTREGISTRATION', vendor_gstin)
    reg_type = _tally_gst_registration_type(move, vendor)
    if reg_type:
        _sub(voucher, 'GSTREGISTRATIONTYPE', reg_type)
    _append_buyer_address_lists(voucher, vendor)


def _append_tally_address_block(parent, tag_prefix, partner):
    """Append repeated ADDRESS + PLACE/STATE/PINCODE under an extension block."""
    if not partner:
        return
    place = _partner_commune_value(partner) or _partner_place_label(partner)
    state = _partner_state_label(partner)
    pin = (partner.zip or '').strip()
    if place:
        _sub(parent, 'PLACE', place)
    if state:
        _sub(parent, 'STATE', state)
    if pin:
        _sub(parent, 'PINCODE', pin)
    lines = []
    if partner.street:
        lines.append(partner.street.strip()[:120])
    commune = _partner_commune_value(partner)
    if partner.street2:
        lines.append(partner.street2.strip()[:120])
    elif commune and commune != place:
        lines.append(commune[:120])
    if lines:
        addr = ET.SubElement(parent, 'ADDRESS.LIST')
        addr.set('TYPE', 'String')
        for line in lines:
            _sub(addr, 'ADDRESS', line)
    if place and tag_prefix:
        _sub(parent, f'{tag_prefix}PLACE', place)


def _ewaybill_transport_mode_value(ewaybill):
    """Tally Part-B mode expects 1/2/3/4 (Road/Rail/Air/Ship), not the label."""
    mode = (ewaybill.mode or '').strip()
    if mode in _TALLY_TRANSPORT_MODES:
        return mode
    for code, label in _TALLY_TRANSPORT_MODES.items():
        if label.lower() == mode.lower():
            return code
    return mode or '1'


def _ewaybill_vehicle_type_value(ewaybill):
    """Tally stores vehicle type as R / O, not the long label."""
    vtype = (ewaybill.vehicle_type or '').strip().upper()
    if vtype in _TALLY_VEHICLE_TYPE_CODES:
        return vtype
    for code, label in _TALLY_VEHICLE_TYPES.items():
        if label.lower() == (ewaybill.vehicle_type or '').strip().lower():
            return code
    if (ewaybill.mode or '1') == '1' and ewaybill.vehicle_no:
        return 'R'
    return vtype


def _gst_json_export_basename(move):
    """File stem for optional *_einvoice.json export (slashes → underscores)."""
    raw = (move.name or str(move.id)).strip()
    return re.sub(r'[\\/:*?"<>|]+', '_', raw)


def _load_einvoice_json_from_export_folder(move, export_path):
    """Load e-Invoice IRP response JSON from an optional on-disk export folder."""
    folder = (export_path or '').strip()
    if not folder or not os.path.isdir(folder):
        return {}
    basename = _gst_json_export_basename(move)
    candidates = [
        os.path.join(folder, f'{basename}_einvoice.json'),
        os.path.join(folder, f'{basename}.json'),
    ]
    for path in candidates:
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding='utf-8') as handle:
                data = json.load(handle)
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            _logger.warning(
                '[odoo_tally_connector] Could not read GST JSON %s: %s', path, exc
            )
    return {}


def _get_move_einvoice_response(move, export_path=''):
    """
    Return e-Invoice IRP response dict from Odoo attachment or optional JSON export.
    """
    resp = {}
    if hasattr(move, '_get_l10n_in_edi_response_json'):
        try:
            resp = move._get_l10n_in_edi_response_json() or {}
        except Exception:
            resp = {}
    if resp.get('Irn') or resp.get('IRN') or resp.get('AckNo'):
        return resp
    return _load_einvoice_json_from_export_folder(move, export_path)


def _parse_to_tally_date(value):
    """Parse Odoo / IRP date strings into Tally YYYYMMDD."""
    if not value:
        return ''
    coerced = _coerce_to_date(value)
    if coerced:
        return _format_tally_date(coerced)
    text = str(value).strip()
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y'):
        try:
            return _format_tally_date(datetime.strptime(text, fmt).date())
        except ValueError:
            continue
    if len(text) >= 10 and text[4] == '-' and text[7] == '-':
        return text[:10].replace('-', '')
    return ''


def _move_generated_ewaybill(move):
    """Return the first generated e-Way Bill linked to this invoice, if any."""
    if 'l10n_in_ewaybill_ids' not in move._fields:
        return False
    return move.l10n_in_ewaybill_ids.filtered(lambda e: e.state == 'generated')[:1]


def _append_voucher_einvoice_tags(voucher, move, einvoice_resp):
    """Add Tally e-Invoice tags (IRN, acknowledgement) to the voucher XML."""
    if not einvoice_resp:
        return False

    irn = (einvoice_resp.get('Irn') or einvoice_resp.get('IRN') or '').strip()
    ack_no = einvoice_resp.get('AckNo') or einvoice_resp.get('IRNAckNo')
    ack_dt = einvoice_resp.get('AckDt') or einvoice_resp.get('IRNAckDate')

    added = False
    if irn:
        _sub(voucher, 'IRN', irn)
        added = True
    if ack_no:
        _sub(voucher, 'IRNAckNo', str(ack_no).strip())
        added = True
    ack_date = _parse_to_tally_date(ack_dt)
    if ack_date:
        _sub(voucher, 'IRNAckDate', ack_date)
        added = True

    ewaybill = _move_generated_ewaybill(move)
    if ewaybill:
        ship_from, ship_to, bill_to = _resolve_ewaybill_partners(move, ewaybill)
        dispatch_place = _partner_place_label(ship_from)
        ship_place = _partner_place_label(ship_to)
        bill_place = _partner_place_label(bill_to)
    else:
        dispatch_place = _partner_place_label(
            move.partner_shipping_id or move.company_id.partner_id
        )
        ship_place = _partner_place_label(
            move.partner_shipping_id or move.partner_id
        )
        bill_place = _partner_place_label(move.partner_id)
    if bill_place:
        _sub(voucher, 'BILLTOPLACE', bill_place)
    if ship_place:
        _sub(voucher, 'SHIPTOPLACE', ship_place)
    if dispatch_place:
        _sub(voucher, 'DISPATCHFROMPLACE', dispatch_place)

    if added:
        _sub(voucher, 'IgnoreeInvValidation', 'Yes')
        _sub(voucher, 'IRNJSONExported', 'Yes')
    return added


def _append_voucher_ewaybill_tags(voucher, move, einvoice_resp, ewaybill):
    """
    Add Tally e-Way Bill aggregate (EWAYBILLDETAILS.LIST) to the voucher XML.
    """
    ewb_no = ''
    ewb_date = ''
    ewb_valid = ''

    if ewaybill:
        ewb_no = (ewaybill.name or '').strip()
        ewb_date = _format_tally_date(_coerce_to_date(ewaybill.ewaybill_date))
        ewb_valid = _format_tally_date(_coerce_to_date(ewaybill.ewaybill_expiry_date))
    elif einvoice_resp:
        ewb_no = str(einvoice_resp.get('EwbNo') or einvoice_resp.get('EWAYBILLNO') or '').strip()
        ewb_date = _parse_to_tally_date(einvoice_resp.get('EwbDt') or einvoice_resp.get('EwbDate'))
        ewb_valid = _parse_to_tally_date(
            einvoice_resp.get('EwbValidTill') or einvoice_resp.get('EwbExpiry')
        )

    _sub(voucher, 'ISEWAYBILLAPPLICABLE', 'Yes')

    dispatch_place = ''
    ship_place = ''
    ship_from = ship_to = bill_to = None
    if ewaybill:
        ship_from, ship_to, bill_to = _resolve_ewaybill_partners(move, ewaybill)
        dispatch_place = _partner_place_label(ship_from)
        ship_place = _partner_place_label(ship_to)
        bill_place = _partner_place_label(bill_to)
        if bill_place:
            _sub(voucher, 'BILLTOPLACE', bill_place)
        if ship_place:
            _sub(voucher, 'SHIPTOPLACE', ship_place)
        if dispatch_place:
            _sub(voucher, 'DISPATCHFROMPLACE', dispatch_place)

    details = ET.SubElement(voucher, 'EWAYBILLDETAILS.LIST')
    if dispatch_place or ship_place:
        _append_ewaybill_place_tags(details, dispatch_place, ship_place)
    ext = ET.SubElement(details, 'EXTENSIONDETAILS.LIST')
    _sub(ext, 'OVRDNEAYBILLAPPLICABILITY', 'Yes')

    if ewb_no:
        _sub(details, 'BILLNUMBER', ewb_no)
    if ewb_date:
        _sub(details, 'BILLDATE', ewb_date)
        _sub(details, 'EWAYBILLDATE', ewb_date)
    if ewb_valid:
        _sub(details, 'VALIDUPTO', ewb_valid)

    if ewaybill and ewaybill.state == 'generated':
        _sub(details, 'ISEWAYBILLGENERATED', 'Yes')
        _sub(details, 'EWAYBILLSTATUS', 'Generated')

    if ewaybill:
        if ewaybill.distance:
            _sub(ext, 'DISTANCE', str(int(ewaybill.distance)))

        mode_value = _ewaybill_transport_mode_value(ewaybill)
        if mode_value:
            _sub(ext, 'TRANSPORTMODE', mode_value)

        if ewaybill.vehicle_no:
            _sub(ext, 'VEHICLENUMBER', ewaybill.vehicle_no.strip())

        vehicle_code = _ewaybill_vehicle_type_value(ewaybill)
        vehicle_label = _TALLY_VEHICLE_TYPES.get(vehicle_code or '', '')
        if vehicle_label:
            _sub(ext, 'VEHICLETYPE', vehicle_label)
        elif vehicle_code:
            _sub(ext, 'VEHICLETYPE', vehicle_code)

        if ewaybill.transportation_doc_no:
            _sub(ext, 'DOCUMENTNUMBER', ewaybill.transportation_doc_no.strip())

        trans_doc_date = _format_tally_date(
            _coerce_to_date(ewaybill.transportation_doc_date)
        )
        if trans_doc_date:
            _sub(ext, 'DOCUMENTDATE', trans_doc_date)

        if ewaybill.document_number:
            _sub(details, 'DOCUMENTNUMBER', ewaybill.document_number.strip()[:50])
        doc_date = _format_tally_date(_coerce_to_date(ewaybill.document_date))
        if doc_date and not ewb_date:
            _sub(details, 'BILLDATE', doc_date)

        dispatch_ext = ET.SubElement(details, 'EXTENSIONDETAILS.LIST')
        _sub(dispatch_ext, 'OVRDNEAYBILLAPPLICABILITY', 'Yes')
        _append_tally_address_block(
            dispatch_ext, 'DISPATCHFROM', ship_from or ewaybill.partner_ship_from_id
        )

        ship_ext = ET.SubElement(details, 'EXTENSIONDETAILS.LIST')
        _sub(ship_ext, 'OVRDNEAYBILLAPPLICABILITY', 'Yes')
        _append_tally_address_block(
            ship_ext, 'SHIPTO', ship_to or ewaybill.partner_ship_to_id
        )

        transport = ET.SubElement(details, 'TRANSPORTDETAILS.LIST')
        transporter = ewaybill.transporter_id
        if transporter and transporter.vat:
            _sub(transport, 'TRANSPORTERID', transporter.vat.strip())
        if transporter and transporter.name:
            _sub(transport, 'TRANSPORTERNAME', transporter.name.strip()[:100])
        if mode_value:
            _sub(transport, 'TRANSPORTMODE', mode_value)
        if ewaybill.vehicle_no:
            _sub(transport, 'VEHICLENUMBER', ewaybill.vehicle_no.strip())
        vehicle_label = _TALLY_VEHICLE_TYPES.get(vehicle_code or '', '')
        if vehicle_code:
            _sub(transport, 'VEHICLETYPE', vehicle_code)
        if vehicle_label:
            _sub(transport, 'NEWVEHICLETYPE', vehicle_label)
            _sub(ext, 'VEHICLETYPE', vehicle_label)
        if ewaybill.transportation_doc_no:
            _sub(transport, 'DOCUMENTNUMBER', ewaybill.transportation_doc_no.strip())
        if trans_doc_date:
            _sub(transport, 'DOCUMENTDATE', trans_doc_date)
        elif ewb_date:
            _sub(transport, 'DOCUMENTDATE', ewb_date)
        if ewaybill.distance:
            _sub(transport, 'DISTANCE', str(int(ewaybill.distance)))

    _sub(details, 'IGNOREGENERATIONVALIDATION', 'Yes')
    _sub(details, 'IGNOREPARTBVALIDATION', 'Yes')
    _sub(details, 'IGNORETRANSIDVALIDATION', 'Yes')
    _sub(details, 'IGNOREEXTNVALIDATION', 'Yes')
    return True


def get_move_gst_compliance_snapshot(move, export_path=None):
    """
    Return e-Invoice / e-Way Bill values available on this invoice for Tally export.
    """
    if export_path is None:
        export_path = move.env['ir.config_parameter'].sudo().get_param(
            'tally_connector.gst_json_export_path', ''
        )
    einvoice_resp = _get_move_einvoice_response(move, export_path)
    ewaybill = _move_generated_ewaybill(move)

    irn = (einvoice_resp.get('Irn') or einvoice_resp.get('IRN') or '').strip()
    ack_no = str(
        einvoice_resp.get('AckNo') or einvoice_resp.get('IRNAckNo') or ''
    ).strip()
    ack_dt = einvoice_resp.get('AckDt') or einvoice_resp.get('IRNAckDate')

    ewb_no = ''
    ewb_date = ''
    ewb_valid = ''
    if ewaybill:
        ewb_no = (ewaybill.name or '').strip()
        ewb_date = _format_tally_date(ewaybill.ewaybill_date)
        ewb_valid = _format_tally_date(ewaybill.ewaybill_expiry_date)
    elif einvoice_resp:
        ewb_no = str(
            einvoice_resp.get('EwbNo') or einvoice_resp.get('EWAYBILLNO') or ''
        ).strip()
        ewb_date = _parse_to_tally_date(
            einvoice_resp.get('EwbDt') or einvoice_resp.get('EwbDate')
        )
        ewb_valid = _parse_to_tally_date(
            einvoice_resp.get('EwbValidTill') or einvoice_resp.get('EwbExpiry')
        )

    has_einvoice = bool(irn or ack_no)
    has_ewaybill = bool(ewb_no)
    snapshot = {
        'has_einvoice': has_einvoice,
        'has_ewaybill': has_ewaybill,
        'has_data': has_einvoice or has_ewaybill,
        'irn': irn,
        'irn_ack_no': ack_no,
        'irn_ack_date': _parse_to_tally_date(ack_dt),
        'ewaybill_no': ewb_no,
        'ewaybill_date': ewb_date,
        'ewaybill_valid_upto': ewb_valid,
        'dispatch_from': '',
        'ship_to': '',
        'transporter_id': '',
        'transporter_name': '',
        'transport_mode': '',
        'vehicle_no': '',
        'vehicle_type': '',
        'transport_doc_no': '',
        'transport_doc_date': '',
        'distance': '',
    }
    if ewaybill:
        ship_from, ship_to, _bill_to = _resolve_ewaybill_partners(move, ewaybill)
        snapshot.update({
            'dispatch_from': _partner_place_label(ship_from),
            'ship_to': _partner_place_label(ship_to),
            'transporter_id': (ewaybill.transporter_id.vat or '').strip()
            if ewaybill.transporter_id else '',
            'transporter_name': (ewaybill.transporter_id.name or '').strip()
            if ewaybill.transporter_id else '',
            'transport_mode': _ewaybill_transport_mode_value(ewaybill),
            'vehicle_no': (ewaybill.vehicle_no or '').strip(),
            'vehicle_type': _ewaybill_vehicle_type_value(ewaybill),
            'transport_doc_no': (ewaybill.transportation_doc_no or '').strip(),
            'transport_doc_date': _format_tally_date(
                _coerce_to_date(ewaybill.transportation_doc_date)
            ),
            'distance': str(int(ewaybill.distance or 0)),
        })
    return snapshot


def _append_voucher_gst_compliance_tags(voucher, move, force=False):
    """
    Push e-Invoice (IRN) and e-Way Bill details into the Tally voucher XML.
    """
    icp = move.env['ir.config_parameter'].sudo()
    if not force:
        include = icp.get_param('tally_connector.include_gst_compliance', 'True') in (
            'True', '1', 'true'
        )
        if not include:
            return {'einvoice': False, 'ewaybill': False}

    move_type = getattr(move, 'move_type', '')
    if move_type not in ('out_invoice', 'out_refund', 'out_receipt'):
        return {'einvoice': False, 'ewaybill': False}

    export_path = icp.get_param('tally_connector.gst_json_export_path', '')
    einvoice_resp = _get_move_einvoice_response(move, export_path)
    ewaybill = _move_generated_ewaybill(move)

    einvoice_added = _append_voucher_einvoice_tags(voucher, move, einvoice_resp)
    ewaybill_added = False
    if einvoice_added or ewaybill or einvoice_resp.get('EwbNo'):
        ewaybill_added = _append_voucher_ewaybill_tags(
            voucher, move, einvoice_resp, ewaybill
        )
    return {'einvoice': einvoice_added, 'ewaybill': ewaybill_added}


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

def _format_tally_date(date_obj):
    """Convert a Python date/datetime to Tally's YYYYMMDD format."""
    if not date_obj:
        return ''
    return date_obj.strftime('%Y%m%d')


def _sv_period_bounds(d):
    """First and last calendar day of month containing ``d`` (for SVFROMDATE / SVTODATE)."""
    d = _coerce_to_date(d) or date.today()
    last_day = monthrange(d.year, d.month)[1]
    return d.replace(day=1), d.replace(day=last_day)


def _snap_date_for_tally_edu(date_obj):
    """
    TallyPrime EDU often allows only the 1st, 2nd and last calendar day of each month.
    If ``date_obj`` falls on another day, return the 1st of the same month.

    Returns:
        tuple: (date used for Tally XML, bool snapped)
    """
    d = _coerce_to_date(date_obj)
    if not d:
        return None, False
    last_day = monthrange(d.year, d.month)[1]
    if d.day in (1, 2, last_day):
        return d, False
    return d.replace(day=1), True


def _get_tally_amount(debit, credit):
    """
    Return the signed amount string for a Tally ALLLEDGERENTRIES AMOUNT tag.

    Tally Rule:
        Debit  → negative value  e.g. -10000.00
        Credit → positive value  e.g.  10000.00

    Args:
        debit (float): Odoo move line debit value (0 if credit line).
        credit (float): Odoo move line credit value (0 if debit line).

    Returns:
        str: Amount formatted to 2 decimal places with correct sign.
    """
    if debit and debit > 0:
        return f'-{debit:.2f}'
    if credit and credit > 0:
        return f'{credit:.2f}'
    return '0.00'


def _is_deemed_positive(debit, credit):
    """
    Return the Tally ISDEEMEDPOSITIVE flag for a ledger entry.

    Tally uses this flag to determine the natural flow of the entry:
        Debit  → 'Yes'  (amount is flowing out / increasing asset)
        Credit → 'No'   (amount is flowing in / increasing liability)

    Args:
        debit (float): Odoo move line debit value.
        credit (float): Odoo move line credit value.

    Returns:
        str: 'Yes' for debit entries, 'No' for credit entries.
    """
    return 'Yes' if (debit and debit > 0) else 'No'


def _is_rounding_line(line):
    """Return whether an account move line is Odoo's cash-rounding adjustment."""
    return getattr(line, 'display_type', False) == 'rounding'


def _get_tally_round_off_entry(debit, credit):
    """
    Round Off on Tally item invoices.

    Keep the standard signed AMOUNT from Odoo (so Dr/Cr still balance) but always
    set ISDEEMEDPOSITIVE=No. With Yes, Tally treats the line as an extra charge
    (+0.46) instead of a reduction ((-0.46)).
    """
    return _get_tally_amount(debit, credit), 'No'


def _is_stock_invoice_line(line):
    """True when an invoice line should export as a Tally stock item row."""
    if not line.product_id:
        return False
    display_type = getattr(line, 'display_type', None)
    if display_type in ('line_section', 'line_subsection', 'line_note', 'payment_term'):
        return False
    return True


def move_has_stock_invoice_lines(move):
    """True when a posted invoice/bill has product lines to export to Tally."""
    if not move.is_invoice(include_receipts=True):
        return False
    invoice_lines = getattr(move, 'invoice_line_ids', None)
    if not invoice_lines:
        return False
    return bool(
        invoice_lines.filtered(
            lambda line: _is_stock_invoice_line(line)
            and _invoice_line_has_exportable_amount(line)
        )
    )


def _invoice_line_export_subtotal(inv_line):
    """Taxable line amount used for Tally stock rows and duplicate-ledger checks."""
    subtotal = abs(float(getattr(inv_line, 'price_subtotal', 0.0) or 0.0))
    if subtotal >= 0.005:
        return subtotal
    qty = float(
        getattr(inv_line, 'quantity', 0.0)
        or getattr(inv_line, 'product_uom_qty', 0.0)
        or getattr(inv_line, 'product_qty', 0.0)
        or 0.0
    )
    price = float(getattr(inv_line, 'price_unit', 0.0) or 0.0)
    return abs(qty * price)


def _invoice_line_has_exportable_amount(inv_line):
    """True when a stocked invoice line should appear on the Tally voucher."""
    return _invoice_line_export_subtotal(inv_line) >= 0.005


def _invoice_line_tally_subtotal(inv_line):
    """Amount credited to sales/purchase in Tally for this invoice line."""
    return _invoice_line_export_subtotal(inv_line)


def _invoice_accounts_where_all_lines_are_stocked(move):
    """
    Accounts used only by invoice document lines that all have ``product_id``.

    Used to drop a single consolidated income aml (sometimes without ``product_id``
    on the journal item) when every UI line on that account is a stocked product —
    the amounts are already in ALLINVENTORYENTRIES / ACCOUNTINGALLOCATIONS.
    """
    by_acc = {}
    for invl in move.invoice_line_ids:
        if invl.display_type in ('line_section', 'line_subsection', 'line_note'):
            continue
        if not invl.account_id:
            continue
        by_acc.setdefault(invl.account_id.id, []).append(invl)
    out = set()
    for acc_id, lines in by_acc.items():
        if lines and all(l.product_id for l in lines):
            out.add(acc_id)
    return out


def _skip_ledger_line_already_in_inventory(move, line, move_type, include_inventory):
    """
    When ALLINVENTORYENTRIES carry ACCOUNTINGALLOCATIONS, the matching income/expense
    aml must not be repeated in ALLLEDGERENTRIES.

    - Always skip journal items that *are* stocked invoice lines (``product_id`` on
      the document line).
    - Also skip other amls on the same account when **every** invoice line posting
      to that account is a stocked product (covers consolidated postings).

    Never skip tax, COGS, payment terms, sections, or explicit discount lines.
    """
    if not include_inventory or not move.is_invoice(include_receipts=True):
        return False
    stock_invoice_lines = move.invoice_line_ids.filtered(lambda l: l.product_id)
    if not stock_invoice_lines:
        return False
    if line.id in set(stock_invoice_lines.ids):
        return True
    if line.display_type in (
        'tax',
        'payment_term',
        'cogs',
        'line_section',
        'line_subsection',
        'line_note',
        'discount',
    ):
        return False
    if line.account_id.id not in _invoice_accounts_where_all_lines_are_stocked(move):
        return False
    if move_type == 'out_invoice':
        return bool(line.credit)
    if move_type == 'in_invoice':
        return bool(line.debit)
    if move_type == 'out_refund':
        return bool(line.debit)
    if move_type == 'in_refund':
        return bool(line.credit)
    return False


def _inventory_subtotal_by_ledger_name(move, ledger_map_dict, include_inventory):
    """
    Sum of ``price_subtotal`` per Tally sales/purchase ledger from stocked invoice lines.
    """
    if not include_inventory or not move.is_invoice(include_receipts=True):
        return {}
    by_name = {}
    inv_lines = move.invoice_line_ids.filtered(_is_stock_invoice_line)
    for inv_line in inv_lines:
        acc = inv_line.account_id
        if not acc:
            continue
        map_e = ledger_map_dict.get(acc.id)
        name = map_e['tally_ledger_name'] if map_e else acc.name
        by_name[name] = by_name.get(name, 0.0) + inv_line.price_subtotal
    return by_name


def _ledger_net_for_move_type(totals, move_type):
    """Signed net amount on this ledger row (positive = credit side for sales invoices)."""
    debit = totals.get('debit') or 0.0
    credit = totals.get('credit') or 0.0
    if move_type in ('out_invoice', 'in_refund', 'out_receipt'):
        return credit - debit
    if move_type in ('in_invoice', 'out_refund', 'in_receipt'):
        return debit - credit
    return credit - debit


def _is_tax_ledger_name(ledger_name):
    """True when the Tally ledger name represents a GST / tax duty head."""
    upper = (ledger_name or '').upper()
    return any(
        token in upper
        for token in ('IGST', 'CGST', 'SGST', 'UTGST', 'GST', 'CESS')
    )


def _ledger_group_is_tax(group_key, totals):
    """True when this aggregated ledger row is a tax line."""
    if group_key[1]:
        return True
    return _is_tax_ledger_name(totals.get('tally_ledger_name'))


def _ledger_group_is_round_off(totals, posting_lines):
    """True when this aggregated ledger row is Odoo cash rounding."""
    line_ids = totals.get('line_ids') or set()
    if line_ids:
        return any(
            _is_rounding_line(line)
            for line in posting_lines.filtered(lambda l: l.id in line_ids)
        )
    line = totals.get('line')
    return bool(line and _is_rounding_line(line))


def _classify_ledger_group(group_key, totals, posting_lines):
    """Classify a voucher ledger row for display ordering in Tally."""
    if totals.get('is_party'):
        return 'party'
    if _ledger_group_is_tax(group_key, totals):
        return 'tax'
    if _ledger_group_is_round_off(totals, posting_lines):
        return 'roundoff'
    return 'other'


def _voucher_ledger_kind_order(kind, item_invoice=False):
    """
    Tally item-invoice body order after stock lines:
    Party (header only) → GST → Round Off → others.
    """
    order = {
        'party': 0,
        'tax': 1,
        'roundoff': 2,
        'other': 3,
    }
    return order.get(kind, 9)


def _ledger_group_sort_key(group_key, totals, posting_lines, item_invoice=False):
    """Sort journal ledger rows; party stays first so Tally keeps it in the header."""
    ledger_name = totals.get('tally_ledger_name') or ''
    kind = _classify_ledger_group(group_key, totals, posting_lines)
    return (_voucher_ledger_kind_order(kind, item_invoice), ledger_name)


def _ledger_totals_skip_for_inventory(
    move,
    ledger_name,
    totals,
    move_type,
    include_inventory,
    posting_lines,
    inventory_subtotal_by_ledger,
):
    """True when this ALLLEDGERENTRIES row is already represented by stock lines."""
    if not include_inventory or totals.get('is_party'):
        return False

    line_ids = totals.get('line_ids') or set()
    if line_ids:
        lines = posting_lines.filtered(lambda l: l.id in line_ids)
        if lines and all(
            _skip_ledger_line_already_in_inventory(move, line, move_type, include_inventory)
            for line in lines
        ):
            return True

    # Stock lines already allocate this ledger in ALLINVENTORYENTRIES; skip duplicate
    inv_total = inventory_subtotal_by_ledger.get(ledger_name)
    if inv_total is not None and inv_total > 0:
        net = _ledger_net_for_move_type(totals, move_type)
        if abs(net - inv_total) < 0.02:
            return True

    if not line_ids:
        return _skip_ledger_line_already_in_inventory(
            move, totals['line'], move_type, include_inventory
        )
    return False


def _sub(parent, tag, text=''):
    """Create a sub-element with text content and return it."""
    el = ET.SubElement(parent, tag)
    el.text = _sanitize_xml_text(text)
    return el


def _append_udf_list(parent, tag, value, value_type='String', index=''):
    """Create a Tally UDF list block for custom TDL fields."""
    desc = f'`{tag}`'
    udf_list = ET.SubElement(parent, f'UDF:{tag}.LIST')
    udf_list.set('DESC', desc)
    udf_list.set('ISLIST', 'YES')
    udf_list.set('TYPE', value_type)
    if index:
        udf_list.set('INDEX', index)
    udf_value = ET.SubElement(udf_list, f'UDF:{tag}')
    udf_value.set('DESC', desc)
    udf_value.text = _sanitize_xml_text(value)
    return udf_list


def _prettify(element):
    """Return a prettified XML string for the given element."""
    rough = ET.tostring(element, encoding='unicode')
    reparsed = minidom.parseString(rough)
    return reparsed.toprettyxml(indent='  ', encoding=None)


def _decimal_places_from_uom_rounding(rounding):
    """Map Odoo uom.rounding to a Tally DECIMALPLACES integer (0–9)."""
    if rounding is None:
        return 3
    try:
        r = float(rounding)
    except (TypeError, ValueError):
        return 3
    if r <= 0 or r >= 1:
        return 0
    s = ('%.10f' % r).rstrip('0').rstrip('.')
    if '.' not in s:
        return 0
    return min(9, len(s.split('.')[1]))


# ---------------------------------------------------------------------------
# Envelope skeleton builders
# ---------------------------------------------------------------------------

def _build_import_envelope(
    company_name,
    report_name='Vouchers',
    sv_from_date=None,
    sv_to_date=None,
):
    """
    Build the outer ENVELOPE skeleton for an import request.

    Returns:
        tuple: (envelope_element, tallymessage_element)
            tallymessage_element is where VOUCHER or master nodes should be appended.
    """
    envelope = ET.Element('ENVELOPE')

    # HEADER
    header = ET.SubElement(envelope, 'HEADER')
    _sub(header, 'TALLYREQUEST', 'Import Data')

    # BODY
    body = ET.SubElement(envelope, 'BODY')
    importdata = ET.SubElement(body, 'IMPORTDATA')

    requestdesc = ET.SubElement(importdata, 'REQUESTDESC')
    _sub(requestdesc, 'REPORTNAME', report_name)
    staticvars = ET.SubElement(requestdesc, 'STATICVARIABLES')
    _sub(staticvars, 'SVCURRENTCOMPANY', company_name)
    if report_name == 'Vouchers':
        if not sv_from_date or not sv_to_date:
            raise ValueError(
                'Tally voucher import requires SVFROMDATE and SVTODATE (YYYYMMDD). '
                'This usually means the Odoo process is still running an outdated '
                'odoo_tally_connector: fully stop Odoo, start again, and upgrade '
                'the module once.'
            )
    if sv_from_date:
        _sub(staticvars, 'SVFROMDATE', sv_from_date)
    if sv_to_date:
        _sub(staticvars, 'SVTODATE', sv_to_date)

    requestdata = ET.SubElement(importdata, 'REQUESTDATA')
    tallymessage = ET.SubElement(requestdata, 'TALLYMESSAGE')
    tallymessage.set('xmlns:UDF', 'TallyUDF')

    return envelope, tallymessage


def _build_export_envelope(report_name='List of Companies'):
    """Build a minimal export request envelope (used for connection test)."""
    envelope = ET.Element('ENVELOPE')

    header = ET.SubElement(envelope, 'HEADER')
    _sub(header, 'TALLYREQUEST', 'Export Data')

    body = ET.SubElement(envelope, 'BODY')
    exportdata = ET.SubElement(body, 'EXPORTDATA')
    requestdesc = ET.SubElement(exportdata, 'REQUESTDESC')
    _sub(requestdesc, 'REPORTNAME', report_name)

    return envelope


# ---------------------------------------------------------------------------
# Test connection envelope
# ---------------------------------------------------------------------------

def build_test_connection_xml():
    """
    Build the XML string used to test connectivity with Tally.
    Requests the list of companies, which is always available.

    Returns:
        str: XML string to POST to Tally.
    """
    envelope = _build_export_envelope('List of Companies')
    return _prettify(envelope)


# ---------------------------------------------------------------------------
# Ledger Master envelope (auto-create party in Tally)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Ledger Master envelope (auto-create party in Tally)
# ---------------------------------------------------------------------------

def build_ledger_master_xml(
    partner,
    tally_group,
    company_name,
    action='Create',
    push_gst_details=True,
    ledger_name_override=None,
    consignee_mode=False,
    extra_address_partners=None,
):

    envelope, tallymessage = _build_import_envelope(
        company_name,
        'All Masters'
    )

    ledger_name = (ledger_name_override or partner.name).strip()[:100]

    ledger = ET.SubElement(tallymessage, 'LEDGER')
    # Action must always be 'Alter' to act as an Upsert (creates if missing, updates if existing)
    action = 'Alter'
    
    ledger.set('NAME', ledger_name)
    ledger.set('ACTION', action)

    _sub(ledger, 'NAME', ledger_name)
    _sub(ledger, 'PARENT', tally_group)
    _sub(ledger, 'ISBILLWISEON', 'Yes')
    _sub(ledger, 'ISCOSTCENTRESON', 'No')

    # Tally expects these contact fields directly under LEDGER. Keep the
    # CONTACTDETAILS.LIST below as well so the number appears as the primary
    # mobile/WhatsApp contact in Tally Prime.
    email = str(getattr(partner, 'email', None) or '').strip()
    if email:
        _sub(ledger, 'EMAIL', email)

    country_name = _partner_country_for_address(partner) or (
        partner.country_id.name if partner.country_id else ''
    )
    if consignee_mode:
        country_name = _partner_country_label(partner) or country_name
    if not country_name:
        country_name = 'India'
    _sub(ledger, 'COUNTRYOFRESIDENCE', country_name)

    phone = _partner_phone_for_tally(partner)
    isd_code = _partner_isd_code_for_tally(partner)
    if phone:
        _sub(ledger, 'LEDGERMOBILE', phone)
        _sub(ledger, 'LEDGERCOUNTRYISDCODE', isd_code)

    # Income Tax Number (PAN)
    pan = ''
    if hasattr(partner, 'l10n_in_pan') and partner.l10n_in_pan:
        pan = partner.l10n_in_pan.strip()
    elif partner.vat and len(partner.vat.strip()) == 15:
        vat_clean = partner.vat.strip()
        if vat_clean[:2].isdigit():
            pan = vat_clean[2:12]
    if pan:
        _sub(ledger, 'INCOMETAXNUMBER', pan)

    # GST Registration Details
    if push_gst_details and partner.vat:
        gst = str(partner.vat).strip()
        gst_details = ET.SubElement(ledger, 'LEDGSTREGDETAILS.LIST')
        
        # Calculate dynamic Indian Financial Year Start
        today_val = date.today()
        fy_year = today_val.year if today_val.month >= 4 else today_val.year - 1
        applicable_from = f"{fy_year}0401"
        
        _sub(gst_details, 'APPLICABLEFROM', applicable_from)
        
        gst_treatment = getattr(partner, 'l10n_in_gst_treatment', False)
        tally_gst_type = 'Regular'
        if gst_treatment:
            mapping = {
                'regular': 'Regular',
                'composition': 'Composition',
                'unregistered': 'Unregistered',
                'consumer': 'Consumer',
                'overseas': 'Overseas',
            }
            tally_gst_type = mapping.get(gst_treatment, 'Regular')
            
        _sub(gst_details, 'GSTREGISTRATIONTYPE', tally_gst_type)
        
        state_name = ''
        if partner.state_id:
            state_name = partner.state_id.name.split(' (')[0]
        pos_state = state_name or _partner_state_for_address(partner)
        if pos_state:
            _sub(gst_details, 'PLACEOFSUPPLY', pos_state)
        elif country_name != 'India':
            _sub(gst_details, 'PLACEOFSUPPLY', country_name)
        else:
            _sub(gst_details, 'PLACEOFSUPPLY', 'Maharashtra')
        _sub(gst_details, 'GSTIN', gst)
        _sub(gst_details, 'ISOTHTERRITORYASSESSEE', 'No')
        _sub(gst_details, 'CONSIDERPURCHASEFOREXPORT', 'No')
        _sub(gst_details, 'ISTRANSPORTER', 'No')
        _sub(gst_details, 'ISCOMMONPARTY', 'No')

    # Mailing details
    mailing_details = ET.SubElement(ledger, 'LEDMAILINGDETAILS.LIST')

    if consignee_mode:
        mail_lines = _partner_own_address_lines(partner)
        if not mail_lines:
            mail_lines = _partner_display_address_lines(partner)
    elif partner.parent_id and not partner.is_company:
        mail_lines = _partner_consignee_address_lines(partner)
    else:
        mail_lines = _partner_address_lines(partner)
    addr = ET.SubElement(mailing_details, 'ADDRESS.LIST')
    addr.set('TYPE', 'String')
    for line in mail_lines:
        _sub(addr, 'ADDRESS', line)
    if not mail_lines:
        if partner.street:
            _sub(addr, 'ADDRESS', partner.street)
        if partner.street2:
            _sub(addr, 'ADDRESS', partner.street2)
        if partner.city:
            _sub(addr, 'ADDRESS', partner.city)
        
    # Applicable from
    today_val = date.today()
    fy_year = today_val.year if today_val.month >= 4 else today_val.year - 1
    applicable_from = f"{fy_year}0401"
    _sub(mailing_details, 'APPLICABLEFROM', applicable_from)
    
    pin_code = _partner_pincode(partner) if consignee_mode else (partner.zip or '')
    if pin_code:
        _sub(mailing_details, 'PINCODE', pin_code)
        
    mailing_label = (partner.name or ledger_name).strip()[:100]
    _sub(mailing_details, 'MAILINGNAME', mailing_label)
    
    if consignee_mode:
        state_name = _partner_state_label(partner)
    else:
        state_name = _partner_state_for_address(partner) or (
            partner.state_id.name.split(' (')[0] if partner.state_id else ''
        )
    if state_name:
        _sub(mailing_details, 'STATE', state_name)
    elif country_name == 'India':
        _sub(mailing_details, 'STATE', 'Maharashtra')
    
    _sub(mailing_details, 'COUNTRY', country_name)

    # Delivery contacts as multi-address on commercial partner ledger (not consignee ledger).
    if not consignee_mode:
        commercial = getattr(partner, 'commercial_partner_id', None) or partner
        address_children = commercial.child_ids.filtered(
            lambda c: c.type in ('delivery', 'invoice', 'other', 'contact')
        )
        for child in address_children:
            child_name = (child.name or '').strip()
            if child_name:
                _append_ledger_multi_address_block(
                    ledger, child, child_name, bill_partner=partner,
                )
        for extra in extra_address_partners or []:
            if not extra:
                continue
            extra_name = (extra.name or '').strip()
            if not extra_name:
                continue
            _append_ledger_multi_address_block(
                ledger, extra, extra_name, bill_partner=partner,
            )

    # Contact details
    if phone:
        contact_details = ET.SubElement(ledger, 'CONTACTDETAILS.LIST')
        _sub(contact_details, 'NAME', 'Primary Mobile No.')
        _sub(contact_details, 'PHONENUMBER', phone)
        _sub(contact_details, 'COUNTRYISDCODE', isd_code)
        _sub(contact_details, 'ISDEFAULTWHATSAPPNUM', 'Yes')

    return _prettify(envelope)

# ---------------------------------------------------------------------------
# Simple unit of measure (UOM) master — must exist before STOCKITEM.BASEUNITS
# ---------------------------------------------------------------------------

def build_simple_unit_xml(unit_symbol, company_name, original_name=None, decimal_places=3):
    """
    Build XML to create a simple Unit master in Tally (All Masters).

    Tally expects ISSIMPLEUNIT = Yes for simple units; NAME is the symbol used
    in STOCKITEM.BASEUNITS and voucher quantities.

    Args:
        unit_symbol (str): Short symbol (e.g. Nos, pcs) — must match BASEUNITS.
        company_name (str): Tally company name.
        original_name (str): Optional formal name (defaults to symbol).
        decimal_places (int): DECIMALPLACES for the unit (0–9).

    Returns:
        str: XML string to POST to Tally.
    """
    symbol = (unit_symbol or '').strip()
    if not symbol:
        raise ValueError('unit_symbol is required for Tally UNIT import.')

    envelope, tallymessage = _build_import_envelope(company_name, 'All Masters')

    unit_el = ET.SubElement(tallymessage, 'UNIT')
    unit_el.set('NAME', symbol)
    unit_el.set('ACTION', 'Create')

    _sub(unit_el, 'NAME', symbol)
    _sub(unit_el, 'ISSIMPLEUNIT', 'Yes')
    _sub(unit_el, 'ORIGINALNAME', (original_name or symbol).strip() or symbol)
    _sub(unit_el, 'DECIMALPLACES', str(max(0, min(9, int(decimal_places)))))

    return _prettify(envelope)


def build_simple_ledger_master_xml(ledger_name, parent_group, company_name):
    """Create or update a simple Tally ledger (e.g. Indirect Expense or Duty)."""
    ledger_name = (ledger_name or '').strip()[:100]
    parent_group = (parent_group or 'Indirect Expenses').strip()
    envelope, tallymessage = _build_import_envelope(company_name, 'All Masters')

    ledger = ET.SubElement(tallymessage, 'LEDGER')
    ledger.set('NAME', ledger_name)
    ledger.set('ACTION', 'Alter')

    _sub(ledger, 'NAME', ledger_name)
    _sub(ledger, 'PARENT', parent_group)
    _sub(ledger, 'ISBILLWISEON', 'No')
    _sub(ledger, 'ISCOSTCENTRESON', 'No')

    return _prettify(envelope)


# ---------------------------------------------------------------------------
# Stock Item Master envelope (auto-create product in Tally)
# ---------------------------------------------------------------------------

def _product_template_hsncode(product):
    """Return HSN/SAC string if the template has l10n_in_hsn_code (India GST)."""
    tmpl = getattr(product, 'product_tmpl_id', None)
    if not tmpl or 'l10n_in_hsn_code' not in tmpl._fields:
        return ''
    return (tmpl.l10n_in_hsn_code or '').strip()


def _product_hsn_description(product):
    """Tally HSN/SAC description from mapping table or product custom fields."""
    if hasattr(product, '_resolve_tally_hsn_description'):
        desc = product._resolve_tally_hsn_description()
        if desc:
            return desc[:200]

    hsn_code = _product_template_hsncode(product)
    if not hsn_code:
        return ''

    mapping = product.env['tally.hsn.description.map'].sudo().search([
        ('hsn_code', '=', hsn_code),
        ('active', '=', True),
    ], limit=1)
    if mapping and (mapping.tally_hsn_description or '').strip():
        return mapping.tally_hsn_description.strip()[:200]

    tmpl = getattr(product, 'product_tmpl_id', None)
    if tmpl:
        for field_name in (
            'l10n_in_hsn_description',
            'hsn_description',
            'x_hsn_description',
        ):
            if field_name not in tmpl._fields:
                continue
            value = getattr(tmpl, field_name, None)
            if value and str(value).strip():
                return str(value).strip()[:200]
    return ''


def _leaf_percent_tax_amounts(tax):
    """Yield percentage amounts from account.tax (expand tax groups)."""
    if not tax:
        return
    if tax.amount_type == 'group':
        for child in tax.children_tax_ids:
            yield from _leaf_percent_tax_amounts(child)
        return
    if tax.amount_type == 'percent' and tax.amount:
        yield float(tax.amount)


def _product_sale_tax_combined_percent(product):
    """
    Combined sales tax % from the product template.
    Uses the bulletproof extraction method to guarantee we get the rate.
    """
    tmpl = getattr(product, 'product_tmpl_id', product)
    taxes = getattr(tmpl, 'taxes_id', False)
    if not taxes:
        return None
        
    if hasattr(taxes, '_filter_taxes_by_company'):
        taxes = taxes._filter_taxes_by_company(product.env.company)
        
    tax_pct = 0.0
    for tax in taxes:
        if getattr(tax, 'amount_type', '') == 'group':
            tax_pct += sum(abs(getattr(child, 'amount', 0.0)) for child in getattr(tax, 'children_tax_ids', []))
        else:
            tax_pct += abs(getattr(tax, 'amount', 0.0))
            
    # Ultimate Fallback: Extract number directly from the name (e.g., "5% GST S" -> 5)
    if tax_pct == 0.0:
        import re
        for tax in taxes:
            match = re.search(r'(\d+[\.\d]*)\s*%', getattr(tax, 'name', ''))
            if match:
                tax_pct += float(match.group(1))
                
    return tax_pct if tax_pct > 0 else None


def _get_product_category_name(product):
    """Get Odoo product category full path for Tally Stock Group."""
    category = getattr(product, "categ_id", False)

    if not category and getattr(product, "product_tmpl_id", False):
        category = getattr(product.product_tmpl_id, "categ_id", False)

    if category:
        # display_name fetches the full "Parent / Child" string with slashes!
        display_name = getattr(category, "display_name", False)
        if display_name:
            return display_name.strip()
            
        # Fallback just in case display_name is empty
        elif category.name:
            return category.name.strip()

    return "Primary"


def _append_stockitem_gst_statutory(item_el, product, push_gst_details):
    """Add GST/HSN statutory details for Tally Stock Item."""
    if not push_gst_details:
        return

    from datetime import date
    import re

    hsn = _product_template_hsncode(product)

    rate = 0.0
    tmpl = getattr(product, "product_tmpl_id", product)
    taxes = getattr(tmpl, "taxes_id", False)

    if taxes:
        if hasattr(taxes, "_filter_taxes_by_company"):
            taxes = taxes._filter_taxes_by_company(product.env.company)

        for tax in taxes:
            if getattr(tax, "amount_type", "") == "group":
                for child in tax.children_tax_ids:
                    rate += abs(getattr(child, "amount", 0.0))
            else:
                rate += abs(getattr(tax, "amount", 0.0))

        if rate == 0.0:
            for tax in taxes:
                match = re.search(r"(\d+(\.\d+)?)\s*%", tax.name or "")
                if match:
                    rate += float(match.group(1))

    product_type = getattr(product, "detailed_type", getattr(product, "type", "consu"))
    supply_type = "Services" if product_type == "service" else "Goods"

    if not hsn and not rate:
        return

    today_val = date.today()
    fy_year = today_val.year if today_val.month >= 4 else today_val.year - 1
    applicable_from = f"{fy_year}0401"

    _sub(item_el, "GSTAPPLICABLE", "Applicable")
    _sub(item_el, "GSTTYPEOFSUPPLY", supply_type)

    if hsn:
        hsn_desc = _product_hsn_description(product)
        hsn_list = ET.SubElement(item_el, "HSNDETAILS.LIST")
        _sub(hsn_list, "SRCOFHSNDETAILS", "Specify Details Here")
        _sub(hsn_list, "APPLICABLEFROM", applicable_from)
        _sub(hsn_list, "HSNCODE", hsn)
        if hsn_desc:
            _sub(hsn_list, "HSN", hsn_desc)

    if rate > 0:
        half_rate = rate / 2.0

        gst_list = ET.SubElement(item_el, "GSTDETAILS.LIST")
        _sub(gst_list, "APPLICABLEFROM", applicable_from)
        _sub(gst_list, "TAXABILITY", "Taxable")
        _sub(gst_list, "SRCOFGSTDETAILS", "Specify Details Here")
        _sub(gst_list, "GSTCALCSLABONMRP", "No")
        _sub(gst_list, "ISREVERSECHARGEAPPLICABLE", "No")
        _sub(gst_list, "ISNONGSTGOODS", "No")
        _sub(gst_list, "GSTINELIGIBLEITC", "No")
        _sub(gst_list, "INCLUDEEXPFORSLABCALC", "No")

        state_details = ET.SubElement(gst_list, "STATEWISEDETAILS.LIST")
        _sub(state_details, "STATENAME", "Any")

        for duty_head, duty_rate in [
            ("CGST", half_rate),
            ("SGST/UTGST", half_rate),
            ("IGST", rate),
            ("Cess", 0),
            ("State Cess", 0),
        ]:
            rate_details = ET.SubElement(state_details, "RATEDETAILS.LIST")
            _sub(rate_details, "GSTRATEDUTYHEAD", duty_head)

            if duty_head == "Cess":
                _sub(rate_details, "GSTRATEVALUATIONTYPE", "Not Applicable")
            else:
                _sub(rate_details, "GSTRATEVALUATIONTYPE", "Based on Value")

            _sub(rate_details, "GSTRATE", f"{duty_rate:g}")

        ET.SubElement(state_details, "GSTSLABRATES.LIST")
        ET.SubElement(gst_list, "TEMPGSTITEMSLABRATES.LIST")
        ET.SubElement(gst_list, "TEMPGSTDETAILSLABRATES.LIST")


def build_stock_group_xml(category_name, company_name, action="Alter", parent_name=None):
    """Create/Alter Tally Stock Group from Odoo product category."""
    envelope, tallymessage = _build_import_envelope(company_name, "All Masters")

    category_name = (category_name or "Primary").strip()

    group = ET.SubElement(tallymessage, "STOCKGROUP")
    group.set("NAME", category_name)
    # Action="Alter" is Tally's Upsert: Creates if missing, updates if exists!
    group.set("ACTION", action)

    _sub(group, "NAME", category_name)
    parent_name = (parent_name or "").strip()
    _sub(group, "PARENT", "" if parent_name.lower() == "primary" else parent_name)
    _sub(group, "ISSUBLEDGER", "No")
    _sub(group, "ISADDABLE", "No")

    return _prettify(envelope)


def build_stock_item_xml(
    product,
    tally_uom_symbol,
    company_name,
    stock_group_parent=None,
    stock_group_under=None,
    action="Alter",
    push_gst_details=True,
    sales_ledger_name="Local Sales",
):
    """Build XML envelope to create/alter Stock Item master in Tally."""
    envelope, tallymessage = _build_import_envelope(company_name, "All Masters")

    category_name = (stock_group_parent or "Primary").strip()

    # --- BUNDLED HACK: CREATE THE STOCK GROUP IN THE SAME PAYLOAD ---
    if category_name and category_name != "Primary":
        # Tally reads top-to-bottom. This creates the Group instantly before the Item!
        group = ET.SubElement(tallymessage, "STOCKGROUP")
        group.set("NAME", category_name)
        group.set("ACTION", "Alter")  # Upsert: Create if missing, ignore if exists
        _sub(group, "NAME", category_name)
        group_under = (stock_group_under or "").strip()
        _sub(group, "PARENT", "" if group_under.lower() == "primary" else group_under)
        _sub(group, "ISSUBLEDGER", "No")
        _sub(group, "ISADDABLE", "No")

    # --- NOW CREATE THE STOCK ITEM ---
    item = ET.SubElement(tallymessage, "STOCKITEM")
    item.set("NAME", product.name)
    item.set("ACTION", action)

    _sub(item, "NAME", product.name)
    
    # Map the item to the group we just created above
    _sub(item, "PARENT", "" if category_name == "Primary" else category_name)
    _sub(item, "BASEUNITS", tally_uom_symbol)
    # Tally item invoices fail with "No Accounting Allocations for ''!" when the
    # stock item has a blank default sales ledger.
    if sales_ledger_name:
        _sub(item, "LEDGERNAME", sales_ledger_name)

    if getattr(product, "default_code", False):
        _sub(item, "ALIAS", product.default_code)

    _append_stockitem_gst_statutory(item, product, push_gst_details)

    return _prettify(envelope)


# ---------------------------------------------------------------------------
# Main voucher envelope builder
# ---------------------------------------------------------------------------

def build_voucher_xml(move, company_name, ledger_map_dict, voucher_type,
                      persisted_view='Invoice Voucher View',
                      uom_map_dict=None, include_inventory=False,
                      voucher_action='Create', minimal=False,
                      godown_name='Main Location', batch_name='Primary Batch'):
    """
    Build a Tally Import Voucher XML envelope for a posted account.move.

    This is the main function called by account_move.py during sync.

    Sign Convention enforced here:
        For every account.move.line:
            if line.debit > 0:  AMOUNT = -debit,  ISDEEMEDPOSITIVE = Yes
            if line.credit > 0: AMOUNT = +credit,  ISDEEMEDPOSITIVE = No

    Args:
        move (account.move): The posted Odoo invoice/bill to sync.
        company_name (str): Tally company name (exact match required).
        ledger_map_dict (dict): {account_id.id: {'tally_ledger_name': str,
                                                   'is_party_account': bool}}
        voucher_type (str): Tally voucher type string (e.g., 'Sales', 'Purchase').
        persisted_view (str): Tally form view type.
        uom_map_dict (dict): {uom_id.id: tally_symbol} — optional.
        include_inventory (bool): Whether to add ALLINVENTORYENTRIES.LIST tags.
        voucher_action (str): ``Create`` or ``Alter`` — use ``Alter`` when re-posting a voucher
            that already exists in Tally (e.g. forced sync with ``tally_guid`` set).

    Returns:
        str: Complete XML string ready to POST to Tally.

    Raises:
        ValueError: If a move line's account is not found in ledger_map_dict.
    """
    if uom_map_dict is None:
        uom_map_dict = {}

    if move._name != 'account.move':
        raise ValueError(
            'Tally voucher XML is only built for posted accounting entries (account.move). '
            'Sale orders and purchase orders are not synced by this connector.'
        )

    _logger.info(
        '[odoo_tally_connector] build_voucher_xml start name=%s model=%s move_type=%r',
        move.name,
        move._name,
        getattr(move, 'move_type', None),
    )

    party_name = _resolve_party_name(move, ledger_map_dict)
    move_type = getattr(move, 'move_type', '')
    vch_num = (move.name or str(move.id)).strip()
    d_src = _voucher_accounting_date(move)
    edu_snap = move.env['ir.config_parameter'].sudo().get_param(
        'tally_connector.edu_snap_voucher_dates', 'False'
    ) in ('True', '1', 'true')
    d_obj, edu_snapped = (
        _snap_date_for_tally_edu(d_src) if edu_snap else (d_src, False)
    )
    if edu_snapped:
        _logger.warning(
            '[odoo_tally_connector] EDU snap (Tally XML only): move %s Odoo voucher date %s -> %s',
            move.name,
            d_src,
            d_obj,
        )
    tally_date = _format_tally_date(d_obj)
    if not tally_date:
        d_obj = date.today()
        tally_date = d_obj.strftime('%Y%m%d')
    sv_lo, sv_hi = _sv_period_bounds(d_obj)
    sv_from = _format_tally_date(sv_lo)
    sv_to = _format_tally_date(sv_hi)
    envelope, tallymessage = _build_import_envelope(
        company_name,
        'Vouchers',
        sv_from_date=sv_from,
        sv_to_date=sv_to,
    )
    _logger.warning(
        '[odoo_tally_connector] voucher XML header SVFROMDATE=%r SVTODATE=%r '
        'voucher_DATE=%r move=%s',
        sv_from,
        sv_to,
        tally_date,
        move.name,
    )

    # ------------------------------------------------------------------ #
    # VOUCHER element — tag order aligned with Tally “Sales as Invoice” XML samples.
    # Missing PARTYNAME / BASIC* / INVOICEORDERLIST often yields a generic
    # “Voucher date is missing” on TallyPrime (incl. EDU) even when <DATE> is set.
    # ------------------------------------------------------------------ #
    voucher = ET.SubElement(tallymessage, 'VOUCHER')
    voucher.set('REMOTEID', vch_num)
    voucher.set('VCHTYPE', voucher_type)
    voucher.set('ACTION', voucher_action or 'Create')
    voucher.set('OBJVIEW', persisted_view)

    _sub(voucher, 'DATE', tally_date)
    _sub(voucher, 'NARRATION', _voucher_narration_text(move))
    _sub(voucher, 'PARTYNAME', party_name)
    _sub(voucher, 'VOUCHERTYPENAME', voucher_type)
    ref_no = _voucher_reference_text(move)
    _sub(voucher, 'REFERENCE', ref_no)
    if not minimal:
        _sub(voucher, 'PARTYLEDGERNAME', party_name)
        _sub(voucher, 'PERSISTEDVIEW', persisted_view)
        _append_voucher_invoice_party_details(voucher, move)
        if move_type in ('in_invoice', 'in_refund'):
            _append_voucher_purchase_party_details(voucher, move)
        _sub(voucher, 'VOUCHERTYPEORIGNAME', voucher_type)
        _sub(voucher, 'EFFECTIVEDATE', tally_date)
        _sub(voucher, 'REFERENCEDATE', tally_date)
        # Credit invoices/bills use a party ledger, not cash. Tally rejects
        # Invoice Voucher View imports when HASCASHFLOW=Yes with no cash ledger.
        _sub(voucher, 'HASCASHFLOW', 'No')

    if move_type in ('out_invoice', 'in_invoice', 'out_refund', 'in_refund'):
        _sub(voucher, 'ISINVOICE', 'Yes')
    else:
        _sub(voucher, 'ISINVOICE', 'No')

    if include_inventory and move.is_invoice(include_receipts=True):
        stock_lines = move.invoice_line_ids.filtered(_is_stock_invoice_line)
        if stock_lines:
            _sub(voucher, 'VCHENTRYMODE', 'Item Invoice')

    due_d = _coerce_to_date(getattr(move, 'invoice_date_due', None))
    if edu_snap and due_d:
        due_d, _ = _snap_date_for_tally_edu(due_d)
    due = _format_tally_date(due_d)
    if due:
        _sub(voucher, 'DUEDATE', due)

    # GUID must be Tally’s internal id (from a prior export/sync), not the invoice number.
    # Sending VOUCHERNUMBER/REMOTEID text as <GUID> breaks Create/Alter and often yields
    # RESPONSE with EXCEPTIONS=1 and no LINEERROR.
    action = (voucher_action or 'Create').strip()
    tally_uid = (getattr(move, 'tally_guid', None) or '').strip()
    if action == 'Alter' and tally_uid and tally_uid != vch_num:
        _sub(voucher, 'GUID', tally_uid)

    _sub(voucher, 'VOUCHERNUMBER', vch_num)

    gst_compliance_flags = _append_voucher_gst_compliance_tags(voucher, move)

    if not minimal:
        if move_type in ('out_invoice', 'in_invoice'):
            inv_order = ET.SubElement(voucher, 'INVOICEORDERLIST.LIST')
            _sub(inv_order, 'BASICORDERDATE', tally_date)
            order_ref = (move.ref or move.payment_reference or move.name or str(move.id))[:40]
            _sub(inv_order, 'BASICPURCHASEORDERNO', order_ref)

    # ------------------------------------------------------------------ #
    # Ledger entries from account.move.line                                #
    # ------------------------------------------------------------------ #
    ledger_entries_added = 0
    inventory_entries_added = 0
    missing_accounts = []
    
    tally_running_sum = 0.0
    party_lines_count = 0
    primary_bill_line_id = None

    Line = move.env['account.move.line'].sudo()
    posting_lines = Line.search([
        ('move_id', '=', move.id),
        ('account_id', '!=', False),
        ('display_type', 'not in', ('line_section', 'line_subsection', 'line_note')),
    ], order='id')

    party_lines_for_bill = []
    for line in posting_lines:
        map_entry = ledger_map_dict.get(line.account_id.id)
        if map_entry and map_entry.get('is_party_account'):
            party_lines_for_bill.append(line)
    party_lines_count = len(party_lines_for_bill)
    if party_lines_for_bill:
        primary_bill_line_id = min(party_lines_for_bill, key=lambda l: l.id).id
        if party_lines_count > 1:
            _logger.warning(
                '[odoo_tally_connector] %s: %s Odoo lines are mapped as party accounts; '
                'Tally often rejects multiple BILLALLOCATIONS with the same New Ref name. '
                'Bill-wise block is attached only to journal item id=%s.',
                move.name,
                party_lines_count,
                primary_bill_line_id,
            )

    # 1. Aggregate all ledger entries by Tally Ledger Name
    ledger_totals = {}
    for line in posting_lines:
        account_id = line.account_id.id
        map_entry = ledger_map_dict.get(account_id)
        if not map_entry:
            missing_accounts.append(f'{line.account_id.code} ({line.account_id.name})')
            continue
        
        ledger_name = map_entry.get('tally_ledger_name', '')
        if map_entry.get('is_party_account') and move.partner_id:
            ledger_name = _party_name_for_move(move)
                    
        if not ledger_name:
            ledger_name = line.account_id.name or ''

        tax_id = line.tax_line_id.id if getattr(line, 'tax_line_id', None) else False
        group_key = (ledger_name, tax_id)

        if group_key not in ledger_totals:
            ledger_totals[group_key] = {
                'tally_ledger_name': ledger_name,
                'debit': 0.0,
                'credit': 0.0,
                'is_party': map_entry.get('is_party_account'),
                'line': line,
                'line_ids': set(),
            }
        
        ledger_totals[group_key]['debit'] += line.debit
        ledger_totals[group_key]['credit'] += line.credit
        ledger_totals[group_key]['line_ids'].add(line.id)

    inventory_subtotal_by_ledger = _inventory_subtotal_by_ledger_name(
        move, ledger_map_dict, include_inventory
    )

    # ====================================================================
    # THE PURE ITEM INVOICE STRUCTURE
    # ====================================================================

    # 1. GENERATE ALL ITEMS (With perfectly decoupled nested accounting)
    if include_inventory:
        inventory_lines = getattr(move, 'invoice_line_ids', None) or getattr(move, 'order_line', None)
        if inventory_lines:
            valid_inv_lines = inventory_lines.filtered(
                lambda l: _is_stock_invoice_line(l)
                and _invoice_line_has_exportable_amount(l)
            )

            for line_number, inv_line in enumerate(valid_inv_lines, start=1):
                uom_id = getattr(getattr(inv_line, 'product_uom_id', getattr(inv_line, 'product_uom', None)), 'id', None)
                uom_symbol = uom_map_dict.get(uom_id, 'Nos')

                item_name = inv_line.product_id.name
                if item_name:
                    item_name = str(item_name).split('\n')[0].strip()[:100]

                price = getattr(inv_line, 'price_unit', 0.0)
                subtotal = _invoice_line_tally_subtotal(inv_line)
                qty = getattr(inv_line, 'quantity', 0.0) or getattr(inv_line, 'product_uom_qty', 0.0) or getattr(inv_line, 'product_qty', 0.0)

                discount_pct = getattr(inv_line, 'discount', 0.0)

                tax_pct = 0.0
                if getattr(inv_line, 'tax_ids', False):
                    for tax in inv_line.tax_ids:
                        children = getattr(tax, 'children_tax_ids', False)
                        if children:
                            tax_pct += sum(abs(getattr(child, 'amount', 0.0)) for child in children)
                        else:
                            tax_pct += abs(getattr(tax, 'amount', 0.0))

                    if tax_pct == 0.0:
                        for tax in inv_line.tax_ids:
                            match = re.search(r'(\d+[\.\d]*)\s*%', getattr(tax, 'name', ''))
                            if match:
                                tax_pct += float(match.group(1))

                if move_type in ('out_invoice', 'out_receipt', 'in_refund'):
                    deemed = 'No'
                    item_amt_str = f'{subtotal:.2f}'
                    acc_amt_str = f'{subtotal:.2f}'
                else:
                    deemed = 'Yes'
                    item_amt_str = f'-{subtotal:.2f}'
                    acc_amt_str = f'-{subtotal:.2f}'

                inv_entry = ET.SubElement(voucher, 'ALLINVENTORYENTRIES.LIST')
                inventory_entries_added += 1
                _sub(inv_entry, 'STOCKITEMNAME', item_name)

                _sub(inv_entry, 'ISDEEMEDPOSITIVE', deemed)
                _sub(inv_entry, 'BILLEDQTY', f'{qty:.3f} {uom_symbol}')
                _sub(inv_entry, 'ACTUALQTY', f'{qty:.3f} {uom_symbol}')
                _sub(inv_entry, 'RATE', f'{price:.2f}/{uom_symbol}')

                product = inv_line.product_id
                product_code = (
                    getattr(product, 'default_code', '')
                    or getattr(product, 'barcode', '')
                    or ''
                )
                hsn_code = (
                    getattr(inv_line, 'l10n_in_hsn_code', '')
                    or _product_template_hsncode(product)
                    or ''
                )
                dtl_values = {
                    'DTLINVSLNO': str(line_number),
                    'DTLINVPARTNO': product_code,
                    'DTLINVPRODUCT': item_name,
                    'DTLINVHSN': hsn_code,
                    'DTLINVGSTRATE': f'{tax_pct:g} %' if tax_pct else '',
                    'DTLINVUOM': uom_symbol,
                    'DTLINVQTY': f'{qty:g}',
                    'DTLINVRATE': f'{price:.2f}',
                    'DTLINVDISC': f'{discount_pct:g}' if discount_pct else '',
                    'DTLINVAMOUNT': item_amt_str,
                }
                for dtl_tag, dtl_value in dtl_values.items():
                    if dtl_value in (None, ''):
                        continue
                    _sub(inv_entry, dtl_tag, dtl_value)
                    _append_udf_list(inv_entry, dtl_tag, dtl_value)

                if discount_pct > 0:
                    _sub(inv_entry, 'DISCOUNT', f'{discount_pct:.2f}')

                # Do not send GSTRATE/IGSTRATE on inventory lines. Tally GST then
                # looks up duty-head ledgers and fails with
                # "No Accounting Allocations for ''!" when classification is empty.
                # CGST/SGST/IGST are already posted as LEDGERENTRIES.

                _sub(inv_entry, 'AMOUNT', item_amt_str)

                if not minimal:
                    batch = ET.SubElement(inv_entry, 'BATCHALLOCATIONS.LIST')
                    _sub(batch, 'GODOWNNAME', (godown_name or 'Main Location').strip())
                    _sub(batch, 'BATCHNAME', (batch_name or 'Primary Batch').strip())
                    _sub(batch, 'BILLEDQTY', f'{qty:.3f} {uom_symbol}')
                    _sub(batch, 'ACTUALQTY', f'{qty:.3f} {uom_symbol}')
                    _sub(batch, 'AMOUNT', item_amt_str)

                acc_alloc = ET.SubElement(inv_entry, 'ACCOUNTINGALLOCATIONS.LIST')
                acc = getattr(inv_line, 'account_id', None)
                if acc:
                    map_e = ledger_map_dict.get(acc.id)
                    item_ledger = map_e['tally_ledger_name'] if map_e else acc.name
                else:
                    item_ledger = "Sales" if move_type.startswith('out_') else "Purchase"

                _sub(acc_alloc, 'LEDGERNAME', item_ledger)
                _sub(acc_alloc, 'ISDEEMEDPOSITIVE', deemed)
                _sub(acc_alloc, 'AMOUNT', acc_amt_str)

                try:
                    tally_running_sum += float(acc_amt_str)
                except ValueError:
                    pass

    if (
        inventory_entries_added > 0
        and not minimal
    ):
        first_stock_line = move.invoice_line_ids.filtered(_is_stock_invoice_line)[:1]
        if first_stock_line:
            acc = first_stock_line.account_id
            if acc:
                map_e = ledger_map_dict.get(acc.id)
                item_header_ledger = (
                    map_e['tally_ledger_name'] if map_e else acc.name
                )
                if item_header_ledger:
                    if move_type in ('in_invoice', 'in_refund', 'in_receipt'):
                        _sub(voucher, 'PURCHASELEDGERNAME', item_header_ledger)
                    elif move_type in ('out_invoice', 'out_refund', 'out_receipt'):
                        _sub(voucher, 'SALESLEDGERNAME', item_header_ledger)

    # 2. GENERATE LEDGER ENTRIES — party first, then GST / round off.
    item_invoice_ledgers = inventory_entries_added > 0
    pending_ledger_entries = []

    for group_key in ledger_totals.keys():
        totals = ledger_totals[group_key]
        ledger_name = totals['tally_ledger_name']

        if _ledger_totals_skip_for_inventory(
            move,
            ledger_name,
            totals,
            move_type,
            include_inventory and (inventory_entries_added > 0),
            posting_lines,
            inventory_subtotal_by_ledger,
        ):
            continue

        debit = totals['debit']
        credit = totals['credit']
        is_round_off = _ledger_group_is_round_off(totals, posting_lines)
        if is_round_off:
            amount_str, deemed_positive = _get_tally_round_off_entry(debit, credit)
        else:
            amount_str = _get_tally_amount(debit, credit)
            deemed_positive = _is_deemed_positive(debit, credit)

        kind = _classify_ledger_group(group_key, totals, posting_lines)
        pending_ledger_entries.append({
            'kind': kind,
            'sort_name': ledger_name,
            'ledger_name': ledger_name,
            'amount_str': amount_str,
            'deemed_positive': deemed_positive,
            'is_party': bool(totals.get('is_party')),
            'line_ids': totals.get('line_ids') or set(),
            'debit': debit,
            'credit': credit,
        })

    pending_ledger_entries.sort(
        key=lambda row: (
            _voucher_ledger_kind_order(row['kind'], item_invoice_ledgers),
            row['sort_name'],
        )
    )

    entry_tag = (
        'LEDGERENTRIES.LIST' if inventory_entries_added > 0 else 'ALLLEDGERENTRIES.LIST'
    )
    for row in pending_ledger_entries:
        tally_running_sum += (row['credit'] - row['debit'])

        entry = ET.SubElement(voucher, entry_tag)
        _sub(entry, 'LEDGERNAME', row['ledger_name'])
        _sub(entry, 'ISDEEMEDPOSITIVE', row['deemed_positive'])
        _sub(entry, 'ISPARTYLEDGER', 'Yes' if row['is_party'] else 'No')
        _sub(entry, 'AMOUNT', row['amount_str'])

        if (
            row['is_party']
            and primary_bill_line_id is not None
            and primary_bill_line_id in row['line_ids']
        ):
            billalloc = ET.SubElement(entry, 'BILLALLOCATIONS.LIST')
            payment = getattr(move, 'origin_payment_id', None)
            if payment:
                bill_reference = (
                    getattr(payment, 'memo', None)
                    or getattr(payment, 'payment_reference', None)
                    or getattr(move, 'ref', None)
                    or vch_num
                )
                _sub(billalloc, 'NAME', bill_reference)
                _sub(billalloc, 'BILLTYPE', 'Agst Ref')
            else:
                _sub(billalloc, 'NAME', vch_num)
                _sub(billalloc, 'BILLTYPE', 'New Ref')
            _sub(billalloc, 'AMOUNT', row['amount_str'])

        ledger_entries_added += 1

    if missing_accounts:
        details = '\n  • '.join(missing_accounts)
        raise ValueError(f'Missing Tally Ledger Mapping for accounts:\n  • {details}')

    if ledger_entries_added == 0:
        raise ValueError('No ledger entries generated for sync.')

    # Party address tail: buyer lines, then consignee name/address (order matters).
    if not minimal and move_type in ('out_invoice', 'out_refund', 'out_receipt'):
        _append_voucher_party_address_tail(voucher, move)
        _append_voucher_consignee_party_details(voucher, move)

    out = _prettify(envelope)
    # region agent log
    try:
        from odoo.addons.odoo_tally_connector.utils.tally_http import (
            _agent_debug_log as _agent_dbg,
        )

        _dates = re.findall(r'<DATE>([^<]*)</DATE>', out)
        _ledger_names = re.findall(r'<LEDGERNAME>([^<]*)</LEDGERNAME>', out)
        _mt = getattr(move, 'move_type', None)
        _isinv_log = 'No'
        if _mt in ('out_invoice', 'in_invoice'):
            _isinv_log = 'Yes'
        _agent_dbg(
            'build_voucher_xml output',
            {
                'move_name': move.name,
                'res_model': move._name,
                'vch_num_resolved': vch_num,
                'vch_num_has_slash': ('/' in vch_num),
                'vch_num_len': len(vch_num or ''),
                'move_type': _mt if _mt is not None else 'n/a',
                'invoice_date': str(getattr(move, 'invoice_date', '')),
                'move_date': str(getattr(move, 'date', getattr(move, 'date_order', ''))),
                'invoice_date_due': str(getattr(move, 'invoice_date_due', '')),
                'edu_snap_enabled': edu_snap,
                'edu_snapped': edu_snapped,
                'd_src_accounting_date': str(d_src),
                'tally_date_used': tally_date,
                'sv_from_yyyymmdd': sv_from,
                'sv_to_yyyymmdd': sv_to,
                'company_name_param': company_name,
                'voucher_action': voucher_action,
                'isinvoice': _isinv_log,
                'voucher_type': voucher_type,
                'persisted_view': persisted_view,
                'party_name_resolved': party_name,
                'consignee_ledger': _resolve_consignee_ledger_name(move),
                'consignee_lines': _move_consignee_address_lines(move),
                'party_lines_mapped_count': party_lines_count,
                'bill_allocation_line_id': primary_bill_line_id,
                'tally_amount_sum': (
                    round(tally_running_sum, 4)
                    if tally_running_sum is not None
                    else None
                ),
                'ledger_entries_added': ledger_entries_added,
                'inventory_entries_added': inventory_entries_added,
                'gst_einvoice_in_xml': gst_compliance_flags.get('einvoice'),
                'gst_ewaybill_in_xml': gst_compliance_flags.get('ewaybill'),
                'ledger_names_in_xml': _ledger_names,
                'DATE_tags_in_final_xml': _dates,
                'final_xml_len': len(out),
                'final_xml_full': out,
            },
            'H1',
            'xml_builder.py:build_voucher_xml',
        )
    except Exception:
        pass
    # endregion
    return out


def build_gst_compliance_voucher_xml(
    move,
    company_name,
    voucher_type,
    persisted_view='Invoice Voucher View',
    voucher_action='Alter',
):
    """
    Build a minimal Tally voucher XML envelope with only e-Invoice / e-Way Bill fields.

    Used by the dedicated GST sync action (separate from full invoice sync).
    """
    if move._name != 'account.move':
        raise ValueError(
            'GST compliance XML is only built for posted accounting entries (account.move).'
        )

    move_type = getattr(move, 'move_type', '')
    if move_type not in ('out_invoice', 'out_refund', 'out_receipt'):
        raise ValueError(
            f'Document type "{move_type}" does not support e-Invoice / e-Way Bill sync.'
        )

    snapshot = get_move_gst_compliance_snapshot(move)
    if not snapshot['has_data']:
        raise ValueError(
            'No e-Invoice (IRN) or e-Way Bill number found on this invoice. '
            'Generate them in Odoo first, then sync to Tally.'
        )

    persisted_view = 'Invoice Voucher View'
    party_name = _party_name_for_move(move) if move.partner_id else ''
    vch_num = (move.name or str(move.id)).strip()
    d_src = _voucher_accounting_date(move)
    edu_snap = move.env['ir.config_parameter'].sudo().get_param(
        'tally_connector.edu_snap_voucher_dates', 'False'
    ) in ('True', '1', 'true')
    d_obj, _ = _snap_date_for_tally_edu(d_src) if edu_snap else (d_src, False)
    tally_date = _format_tally_date(d_obj)
    if not tally_date:
        tally_date = date.today().strftime('%Y%m%d')
    sv_lo, sv_hi = _sv_period_bounds(d_obj or d_src)
    envelope, tallymessage = _build_import_envelope(
        company_name,
        'Vouchers',
        sv_from_date=_format_tally_date(sv_lo),
        sv_to_date=_format_tally_date(sv_hi),
    )

    voucher = ET.SubElement(tallymessage, 'VOUCHER')
    voucher.set('REMOTEID', vch_num)
    voucher.set('VCHTYPE', voucher_type)
    voucher.set('ACTION', voucher_action or 'Alter')
    voucher.set('OBJVIEW', persisted_view)

    _sub(voucher, 'DATE', tally_date)
    _sub(voucher, 'PARTYNAME', party_name)
    _sub(voucher, 'VOUCHERTYPENAME', voucher_type)
    _sub(voucher, 'PARTYLEDGERNAME', party_name)
    _sub(voucher, 'PERSISTEDVIEW', persisted_view)
    _sub(voucher, 'VOUCHERNUMBER', vch_num)
    if move_type in ('out_invoice', 'out_refund', 'in_invoice', 'in_refund'):
        _sub(voucher, 'ISINVOICE', 'Yes')
        stock_lines = move.invoice_line_ids.filtered(_is_stock_invoice_line)
        if stock_lines:
            _sub(voucher, 'VCHENTRYMODE', 'Item Invoice')

    tally_uid = (getattr(move, 'tally_guid', None) or '').strip()
    action = (voucher_action or 'Alter').strip()
    if action == 'Alter' and tally_uid and tally_uid != vch_num:
        _sub(voucher, 'GUID', tally_uid)

    flags = _append_voucher_gst_compliance_tags(voucher, move, force=True)
    if not flags.get('einvoice') and not flags.get('ewaybill'):
        raise ValueError(
            'e-Invoice / e-Way Bill data was found but could not be encoded for Tally XML.'
        )

    return _prettify(envelope), flags, snapshot


# ---------------------------------------------------------------------------
# Helper: resolve party name
# ---------------------------------------------------------------------------

def _resolve_party_name(move, ledger_map_dict):
    """
    Determine the party ledger name to use in the Tally PARTYLEDGERNAME tag.

    Priority:
      1. Partner name (if move has a partner and the AR/AP account is flagged
         as is_party_account in the ledger map).
      2. Mapped tally_ledger_name for the AR/AP account.
      3. Partner name as fallback.

    Args:
        move (account.move): The Odoo invoice/bill.
        ledger_map_dict (dict): Ledger map entries.

    Returns:
        str: Ledger name to use as PARTYLEDGERNAME.
    """
    if move.partner_id:
        return _party_name_for_move(move)

    # Fallback: find an AR/AP line and use the mapped name
    for line in move.line_ids:
        entry = ledger_map_dict.get(line.account_id.id)
        if entry and entry.get('is_party_account'):
            return entry['tally_ledger_name']

    return ''
