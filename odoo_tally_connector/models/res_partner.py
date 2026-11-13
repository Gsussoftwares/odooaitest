# -*- coding: utf-8 -*-
import logging
from odoo import _, api, fields, models
from odoo.addons.odoo_tally_connector.utils import xml_builder, tally_http

_logger = logging.getLogger(__name__)

_PARTNER_AUTO_SYNC_FIELD_WATCH = frozenset({
    'vat', 'name', 'phone', 'mobile', 'email', 'country_id',
    'street', 'street2', 'city', 'zip', 'state_id',
    'customer_rank', 'supplier_rank',
})


class ResPartner(models.Model):
    _inherit = 'res.partner'

    tally_guid = fields.Char(
        string='Tally GUID',
        copy=False,
        readonly=True,
        index=True,
        help='Unique identifier in Tally Prime.'
    )
    tally_last_sync = fields.Datetime(
        string='Last Tally Sync',
        copy=False,
        readonly=True
    )

    def action_sync_to_tally(self):
        """Individual sync button on Partner form."""
        for partner in self:
            partner._sync_to_tally_ledger()
        return True

    @api.model_create_multi
    def create(self, vals_list):
        partners = super().create(vals_list)
        partners._tally_auto_sync_after_change(None)
        return partners

    def write(self, vals):
        res = super().write(vals)
        if self.env.context.get('skip_tally_partner_sync'):
            return res
        if _PARTNER_AUTO_SYNC_FIELD_WATCH.intersection(vals):
            self._tally_auto_sync_after_change(vals)
        return res

    def _tally_auto_sync_after_change(self, vals):
        """If settings allow, push partner master to Tally (non-blocking on errors)."""
        ICP = self.env['ir.config_parameter'].sudo()
        if ICP.get_param('tally_connector.auto_sync_partner', 'False') not in (
            'True', '1', 'true',
        ):
            return
        company_name = (ICP.get_param('tally_connector.company_name') or '').strip()
        if not company_name:
            return
        for partner in self:
            if not partner.active or not (partner.name or '').strip():
                continue
            if partner.customer_rank <= 0 and partner.supplier_rank <= 0:
                continue
            try:
                partner._sync_to_tally_ledger()
            except Exception as exc:  # noqa: BLE001
                _logger.warning(
                    '[TallySync] Auto partner sync skipped for %s: %s',
                    partner.display_name, exc,
                )

    def _tally_master_log(self, status, request_xml, response_xml, guid, error_message, url):
        """Write a sync log row for partner master sync (no account.move)."""
        self.env['tally.sync.log'].sudo().create({
            'move_name': f'MASTER: {self.name or self.id}',
            'status': status,
            'tally_guid': guid or '',
            'request_xml': request_xml,
            'response_xml': response_xml,
            'error_message': error_message,
            'tally_server_url': url,
        })

    def _tally_ledger_partner(self):
        """Commercial partner that owns the Tally party ledger (not delivery contacts)."""
        self.ensure_one()
        if self.parent_id and not self.is_company:
            return self.commercial_partner_id or self
        return self

    def _sync_to_tally_ledger(
        self,
        force=False,
        collect_errors=None,
        consignee_mode=False,
        extra_address_partners=None,
        move=None,
    ):
        """Core logic to push a Partner as a Ledger to Tally."""
        self.ensure_one()
        if not consignee_mode:
            ledger_partner = self._tally_ledger_partner()
            if ledger_partner != self:
                return ledger_partner._sync_to_tally_ledger(
                    force=force,
                    collect_errors=collect_errors,
                    extra_address_partners=extra_address_partners,
                )
        
        ICP = self.env['ir.config_parameter'].sudo()
        url = ICP.get_param('tally_connector.server_url', 'http://localhost:9000')
        company_name = ICP.get_param('tally_connector.company_name', '')

        if not company_name:
            err = _(
                'Tally Company Name is not configured. Open Settings → Tally Connector '
                'and set the name exactly as in Tally Prime.'
            )
            self._tally_master_log('failed', '', '', '', err, url)
            if collect_errors is not None:
                collect_errors.append('%s — %s' % (self.display_name, err))
            return False

        if not (self.name or '').strip():
            err = _('Partner has no name; cannot create a Tally ledger.')
            self._tally_master_log('skipped', '', '', '', err, url)
            if collect_errors is not None:
                collect_errors.append('%s — %s' % (self.display_name, err))
            return False

        # Determine Tally Group
        is_customer = self.customer_rank > 0
        is_supplier = self.supplier_rank > 0

        # If ranks are 0 but no clear indication, default to Debtors
        if not is_customer and not is_supplier:
            is_customer = True

        ledgers_to_create = []
        move_type = getattr(move, 'move_type', '') if move else ''
        vendor_move = move_type in ('in_invoice', 'in_refund', 'in_receipt')
        customer_move = move_type in ('out_invoice', 'out_refund', 'out_receipt')

        if vendor_move:
            ledgers_to_create.append(('Sundry Creditors', self.name))
        elif customer_move:
            ledgers_to_create.append(('Sundry Debtors', self.name))
        elif is_customer and is_supplier:
            ledgers_to_create.append(('Sundry Debtors', self.name))
        elif is_supplier:
            ledgers_to_create.append(('Sundry Creditors', self.name))
        else:
            ledgers_to_create.append(('Sundry Debtors', self.name))

        push_gst = ICP.get_param('tally_connector.master_push_gst', 'True') in (
            'True', '1', 'true',
        )
        action = (
            'Alter' if (self.tally_guid or self.tally_last_sync) else 'Create'
        )

        try:
            all_success = True
            last_guid = ''
            
            for tally_group, override_name in ledgers_to_create:
                xml_str = xml_builder.build_ledger_master_xml(
                    self,
                    tally_group,
                    company_name,
                    action=action,
                    push_gst_details=push_gst and not consignee_mode,
                    ledger_name_override=override_name,
                    consignee_mode=consignee_mode,
                    extra_address_partners=extra_address_partners,
                )
                success, response_text, guid, error = tally_http.post_to_tally(xml_str, url)
                
                self._tally_master_log(
                    'success' if success else 'failed',
                    xml_str,
                    response_text,
                    guid,
                    error,
                    url,
                )
                
                if success:
                    last_guid = guid or override_name
                else:
                    all_success = False
                    if collect_errors is not None and error:
                        collect_errors.append('%s — %s' % (override_name, error))

            if all_success:
                self.with_context(skip_tally_partner_sync=True).write({
                    'tally_guid': last_guid,
                    'tally_last_sync': fields.Datetime.now()
                })
            return all_success
        except Exception as exc:
            _logger.error('[TallySync] Partner sync failed for %s: %s', self.name, exc)
            err_msg = str(exc)
            self._tally_master_log('failed', '', '', '', err_msg, url)
            if collect_errors is not None:
                collect_errors.append('%s — %s' % (self.display_name, err_msg))
            return False
