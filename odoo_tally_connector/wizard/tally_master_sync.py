# -*- coding: utf-8 -*-
import logging
from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Customers/vendors: own accounting rank OR contact/address under such a commercial entity
# (Invoicing → Customers often lists many rows; only the company usually has customer_rank.)
_PARTNER_SYNC_DOMAIN = [
    ('active', '=', True),
    '|',
    '|',
    '|',
    ('customer_rank', '>', 0),
    ('supplier_rank', '>', 0),
    ('commercial_partner_id.customer_rank', '>', 0),
    ('commercial_partner_id.supplier_rank', '>', 0),
]

# Only “Goods” become Tally stock items (not services / combos)
_PRODUCT_SYNC_DOMAIN = [
    ('active', '=', True),
    ('product_tmpl_id.type', '=', 'consu'),
]


class TallyMasterSync(models.TransientModel):
    _name = 'tally.master.sync'
    _description = 'Tally Bulk Master Sync'

    partner_count = fields.Integer(
        string='Partners to sync',
        compute='_compute_counts',
        help=(
            'Each Odoo customer/vendor row gets its own Tally party ledger '
            '(same display name as in Odoo, e.g. company + contact).'
        ),
    )
    product_count = fields.Integer(string='Product Count', compute='_compute_counts')

    @api.depends('create_date')
    def _compute_counts(self):
        Partner = self.env['res.partner']
        Product = self.env['product.product']
        partner_rows = Partner.search(_PARTNER_SYNC_DOMAIN)
        for wiz in self:
            wiz.partner_count = len(partner_rows)
            wiz.product_count = Product.search_count(_PRODUCT_SYNC_DOMAIN)

    def _require_tally_company_and_url(self):
        ICP = self.env['ir.config_parameter'].sudo()
        company = (ICP.get_param('tally_connector.company_name') or '').strip()
        url = (ICP.get_param('tally_connector.server_url') or '').strip()
        if not company:
            raise UserError(_(
                'Tally Company Name is not configured.\n'
                'Open Settings → Tally Connector and enter the company name '
                'exactly as it appears in Tally Prime (case-sensitive).'
            ))
        if not url:
            raise UserError(_(
                'Tally Server URL is empty. Set it in Settings → Tally Connector '
                '(e.g. http://localhost:9000).'
            ))
        return company, url

    def _require_tally_stock_item_group(self):
        """Product master sync needs a real Tally stock group name (no silent default)."""
        ICP = self.env['ir.config_parameter'].sudo()
        group = (ICP.get_param('tally_connector.stock_item_group') or '').strip()
        category_group = self.env['tally.product.category.map'].search_count([
            ('active', '=', True),
        ])
        if category_group:
            return group
        if not group:
            raise UserError(_(
                'Tally Stock Group is not set.\n\n'
                'Open Settings → Tally Prime Connector and fill in '
                '“Stock Group for new items” with the exact name of a group that '
                'already exists in Tally (Gateway of Tally → Inventory Info → Stock Groups).\n\n'
                'Example: if your items sit under “Finished Goods” in Tally, type Finished Goods here.'
            ))
        if group.lower() == 'primary':
            raise UserError(_(
                'Stock Group is still “Primary”, which your Tally data does not use.\n\n'
                'Open Tally → Gateway of Tally → Inventory Info → Stock Groups, '
                'copy an existing group name exactly, and paste it into '
                'Settings → Tally Connector → “Stock Group for new items”. '
                'Then save Settings and run bulk sync again.'
            ))
        return group

    def _notification_bulk_result(self, title, success_count, total, errors, noun):
        """Client notification: success / warning if nothing synced, include first errors."""
        if total == 0:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': title,
                    'message': _('No %s matched the sync rules.') % noun,
                    'type': 'info',
                    'sticky': False,
                },
            }
        if success_count == total:
            notif_type = 'success'
            message = _('Successfully synced %s out of %s %s.') % (success_count, total, noun)
        elif success_count == 0:
            notif_type = 'danger'
            message = _(
                'Synced 0 out of %s %s. Check Customers → Tally Connector → Sync Logs '
                'for details. Common causes: Tally not running, wrong company name, '
                'or XML server port blocked.'
            ) % (total, noun)
        else:
            notif_type = 'warning'
            message = _('Synced %s out of %s %s. See Sync Logs for failures.') % (
                success_count, total, noun,
            )
        if errors:
            sample = '\n'.join(errors[:3])
            if len(errors) > 3:
                sample += _('\n… and more (see Sync Logs).')
            message = '%s\n\n%s' % (message, sample)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': title,
                'message': message,
                'type': notif_type,
                'sticky': notif_type != 'success',
            },
        }

    def action_sync_all_customers(self):
        """Mass sync: one Tally ledger per matching res.partner row (not merged by company)."""
        self._require_tally_company_and_url()
        partners = self.env['res.partner'].search(_PARTNER_SYNC_DOMAIN)

        errors = []
        success_count = 0
        for partner in partners:
            if partner._sync_to_tally_ledger(collect_errors=errors):
                success_count += 1

        return self._notification_bulk_result(
            _('Bulk partner sync'),
            success_count,
            len(partners),
            errors,
            _('customers/vendors'),
        )

    def action_sync_all_products(self):
        """Mass sync all active products to Tally."""
        self._require_tally_company_and_url()
        self._require_tally_stock_item_group()
        products = self.env['product.product'].search(_PRODUCT_SYNC_DOMAIN)
        errors = []
        success_count = 0
        unit_cache = set()
        for product in products:
            if product.with_context(tally_unit_cache=unit_cache)._sync_to_tally_item(
                collect_errors=errors
            ):
                success_count += 1

        return self._notification_bulk_result(
            _('Bulk product sync'),
            success_count,
            len(products),
            errors,
            _('products'),
        )
