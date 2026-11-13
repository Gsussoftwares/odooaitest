# -*- coding: utf-8 -*-
import datetime
import logging
import re
import xml.sax.saxutils as saxutils
from odoo import api, fields, models

_logger = logging.getLogger(__name__)

try:
    from odoo.addons.odoo_tally_connector.utils import tally_http
except ImportError:
    tally_http = None


class AccountMoveTallyVendorCode(models.Model):
    _inherit = "account.move"

    def _get_tally_vendor_code_ref(self):
        """
        Extract and format Customer's Vendor Code for Tally's 'Other References' field.
        Sources checked in priority order:
        1. partner_id.partner_seq
        2. partner_id.commercial_partner_id.partner_seq
        3. partner_id.parent_id.partner_seq
        4. partner_id.vendor_code / ref (fallback)
        """
        self.ensure_one()
        partner = self.partner_id
        if not partner:
            return False

        code = (
            getattr(partner, "partner_seq", False)
            or getattr(partner.commercial_partner_id, "partner_seq", False)
            or getattr(partner.parent_id, "partner_seq", False)
            or getattr(partner, "vendor_code", False)
            or getattr(partner.commercial_partner_id, "vendor_code", False)
        )

        if not code and getattr(partner, "ref", False):
            ref_val = str(partner.ref).strip()
            # If ref looks like a code (e.g. 2697 or alphanumeric)
            if ref_val and len(ref_val) <= 20:
                code = ref_val

        if code and str(code).strip():
            clean_code = str(code).strip()
            if clean_code.upper().startswith("VENDOR CODE"):
                return clean_code
            return f"VENDOR CODE: {clean_code}"

        return False

    def _get_tally_buyer_order_details(self):
        """
        Resolve Buyer's Order No and PO Date for Tally's 'Order No(s)' and 'Date' fields.
        Checks:
        1. Linked Sales Order: so.customer_po_no & so.customer_po_date
        2. move.ref (Customer Reference) fallback
        3. move.invoice_date fallback
        """
        self.ensure_one()
        so = False

        # 1. Try to locate linked Sales Order dynamically from invoice_origin
        if self.invoice_origin:
            origin_str = str(self.invoice_origin).strip()
            # Support comma-separated SO origins dynamically
            origin_parts = [p.strip() for p in origin_str.split(",") if p.strip()] or [origin_str]
            for part in origin_parts:
                so = self.env["sale.order"].sudo().search([("name", "=", part)], limit=1)
                if not so:
                    so = self.env["sale.order"].sudo().search([("name", "ilike", part)], limit=1)
                if so:
                    break

        # 2. Dynamic fallback to invoice line sale_line_ids
        if not so:
            lines = getattr(self, "invoice_line_ids", False) or getattr(self, "line_ids", False)
            if lines and hasattr(lines, "sale_line_ids"):
                so_records = lines.mapped("sale_line_ids.order_id")
                if so_records:
                    so = so_records[0]

        order_no = False
        if so and getattr(so, "customer_po_no", False):
            order_no = str(so.customer_po_no).strip()

        if not order_no and self.ref:
            order_no = str(self.ref).strip()

        order_date_str = False
        order_date = False
        if so and getattr(so, "customer_po_date", False):
            order_date = so.customer_po_date
        elif self.invoice_date:
            order_date = self.invoice_date

        if order_date:
            if isinstance(order_date, (datetime.date, datetime.datetime)):
                order_date_str = order_date.strftime("%Y%m%d")
            else:
                order_date_str = str(order_date).replace("-", "")[:8]

        return order_no, order_date_str

    def _sync_to_tally(self, force=False):
        """
        Inject:
        1. <BASICORDERREF>VENDOR CODE: 2697</BASICORDERREF> (Other References)
        2. <BASICPURCHASEORDERNO>00001</BASICPURCHASEORDERNO> (Order No(s))
        3. <BASICORDERDATE>20261020</BASICORDERDATE> (Order Date)
        into Tally XML before posting to Tally Prime.
        """
        self.ensure_one()
        vendor_ref = self._get_tally_vendor_code_ref()
        buyer_order_no, buyer_order_date_str = self._get_tally_buyer_order_details()

        if not tally_http or not hasattr(tally_http, "post_to_tally"):
            return super()._sync_to_tally(force=force)

        orig_post = getattr(tally_http, "post_to_tally", None)

        def _custom_order_details_post(xml_data, post_url, **kwargs):
            if isinstance(xml_data, str) and "<VOUCHER" in xml_data:
                # 1. Inject / Replace Vendor Code in <BASICORDERREF>
                if vendor_ref:
                    escaped_vendor_ref = saxutils.escape(vendor_ref)
                    if "<BASICORDERREF>" in xml_data:
                        xml_data = re.sub(
                            r"<BASICORDERREF>.*?</BASICORDERREF>",
                            f"<BASICORDERREF>{escaped_vendor_ref}</BASICORDERREF>",
                            xml_data,
                        )
                    elif "</VOUCHER>" in xml_data:
                        xml_data = xml_data.replace(
                            "</VOUCHER>",
                            f"<BASICORDERREF>{escaped_vendor_ref}</BASICORDERREF></VOUCHER>",
                        )
                    _logger.info(
                        "[TallySync] Injected <BASICORDERREF>%s</BASICORDERREF> for Move %s",
                        escaped_vendor_ref,
                        self.name,
                    )

                # 2. Inject / Replace Buyer's Order No & Date in <INVOICEORDERLIST.LIST>
                if buyer_order_no:
                    escaped_order_no = saxutils.escape(buyer_order_no)
                    date_tag = (
                        f"<BASICORDERDATE>{buyer_order_date_str}</BASICORDERDATE>"
                        if buyer_order_date_str
                        else ""
                    )
                    new_order_list = (
                        f"<INVOICEORDERLIST.LIST>"
                        f"{date_tag}"
                        f"<BASICPURCHASEORDERNO>{escaped_order_no}</BASICPURCHASEORDERNO>"
                        f"</INVOICEORDERLIST.LIST>"
                    )

                    if "<INVOICEORDERLIST.LIST>" in xml_data:
                        # Replace the entire existing list to ensure correct order of tags
                        xml_data = re.sub(
                            r"<INVOICEORDERLIST\.LIST>.*?</INVOICEORDERLIST\.LIST>",
                            new_order_list,
                            xml_data,
                            flags=re.DOTALL,
                        )
                    elif "<VOUCHERNUMBER>" in xml_data:
                        # Insert right after VOUCHERNUMBER for standard Tally header order
                        xml_data = re.sub(
                            r"(<VOUCHERNUMBER>.*?</VOUCHERNUMBER>)",
                            r"\1\n            " + new_order_list,
                            xml_data,
                            count=1,
                        )
                    elif "</VOUCHER>" in xml_data:
                        xml_data = xml_data.replace("</VOUCHER>", f"{new_order_list}</VOUCHER>")

                    _logger.info(
                        "[TallySync] Injected Buyer Order No '%s' & Date '%s' for Move %s",
                        escaped_order_no,
                        buyer_order_date_str,
                        self.name,
                    )

            return orig_post(xml_data, post_url, **kwargs)

        try:
            tally_http.post_to_tally = _custom_order_details_post
            return super()._sync_to_tally(force=force)
        finally:
            tally_http.post_to_tally = orig_post
