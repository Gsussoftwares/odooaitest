# -*- coding: utf-8 -*-
import logging
from odoo import _, api, fields, models
from odoo.addons.odoo_tally_connector.utils import xml_builder, tally_http

_logger = logging.getLogger(__name__)

_PRODUCT_AUTO_SYNC_FIELD_WATCH = frozenset({
    'name', 'default_code', 'uom_id', 'active', 'product_tmpl_id', 'barcode', 'categ_id',
    'l10n_in_hsn_code',
})


class ProductProduct(models.Model):
    _inherit = 'product.product'

    tally_stock_group_name = fields.Char(
        string='Tally Stock Group',
        related='categ_id.tally_stock_group_name',
        readonly=True,
    )
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
    tally_hsn_description = fields.Char(
        string='Tally HSN Description',
        compute='_compute_tally_hsn_description',
        help='Resolved from HSN Description Mapping (by product HSN/SAC code).',
    )

    def action_sync_to_tally(self):
        """Individual sync button on Product form."""
        for product in self:
            product._sync_to_tally_item()
        return True

    @api.depends('product_tmpl_id')
    def _compute_tally_hsn_description(self):
        for product in self:
            product.tally_hsn_description = product._resolve_tally_hsn_description()

    def _resolve_tally_hsn_description(self):
        """HSN description text sent to Tally from mapping table."""
        self.ensure_one()
        tmpl = self.product_tmpl_id
        hsn_code = (
            getattr(self, 'l10n_in_hsn_code', False)
            or (getattr(tmpl, 'l10n_in_hsn_code', False) if tmpl else False)
            or ''
        )
        if isinstance(hsn_code, str):
            hsn_code = hsn_code.strip()
        else:
            hsn_code = ''
        if not hsn_code:
            return ''
        mapping = self.env['tally.hsn.description.map'].sudo().search([
            ('hsn_code', '=', hsn_code),
            ('active', '=', True),
        ], limit=1)
        if mapping and (mapping.tally_hsn_description or '').strip():
            return mapping.tally_hsn_description.strip()
        return ''

    @api.model_create_multi
    def create(self, vals_list):
        products = super().create(vals_list)
        products._tally_auto_sync_product_after_change(None)
        return products

    def write(self, vals):
        res = super().write(vals)
        if self.env.context.get('skip_tally_product_sync'):
            return res
        if _PRODUCT_AUTO_SYNC_FIELD_WATCH.intersection(vals):
            self._tally_auto_sync_product_after_change(vals)
        return res

    def _tally_auto_sync_product_after_change(self, vals):
        """If settings allow, push goods to Tally (non-blocking)."""
        ICP = self.env['ir.config_parameter'].sudo()
        if ICP.get_param('tally_connector.auto_sync_product', 'False') not in (
            'True', '1', 'true',
        ):
            return
        company_name = (ICP.get_param('tally_connector.company_name') or '').strip()
        if not company_name:
            return
        for product in self:
            if not product.active or product.type not in ('product', 'consu'):
                continue
            if not (product.name or '').strip():
                continue
            try:
                product._sync_to_tally_item()
            except Exception as exc:  # noqa: BLE001
                _logger.warning(
                    '[TallySync] Auto product sync skipped for %s: %s',
                    product.display_name, exc,
                )

    def _get_tally_stock_group(self):
        """Mapping table first, inherited category mapping next, then global setting."""
        self.ensure_one()
        category = self.categ_id
        mapping = self.env['tally.product.category.map'].sudo()
        category_mapping = mapping
        while category and not category_mapping:
            category_mapping = mapping.search([
                ('category_id', '=', category.id),
                ('active', '=', True),
            ], limit=1)
            if category_mapping:
                break
            category = category.parent_id
        group_name = (
            (category_mapping.tally_stock_group_name or '').strip()
            if category_mapping
            else ''
        )
        parent_name = (
            (category_mapping.tally_parent_stock_group_name or '').strip()
            if category_mapping
            else ''
        )
        if not group_name:
            group_name = (
                self.env['ir.config_parameter'].sudo().get_param(
                    'tally_connector.stock_item_group'
                ) or ''
            ).strip()
        return group_name, parent_name

    def _tally_product_log(self, status, request_xml, response_xml, guid, error_message, url):
        self.env['tally.sync.log'].sudo().create({
            'move_name': f'PRODUCT: {self.name or self.id}',
            'status': status,
            'tally_guid': guid or '',
            'request_xml': request_xml,
            'response_xml': response_xml,
            'error_message': error_message,
            'tally_server_url': url,
        })

    def _ensure_tally_simple_unit(
        self,
        unit_symbol,
        company_name,
        url,
        collect_errors=None,
        unit_cache=None,
    ):
        """
        Create a simple Tally UNIT master if missing (symbol must match STOCKITEM.BASEUNITS).

        Idempotent: duplicate / already-exists responses are treated as success.
        Optional ``unit_cache`` (set of symbols) avoids repeat HTTP calls in bulk sync.
        """
        symbol = (unit_symbol or '').strip()
        if not symbol:
            return False
        if unit_cache is not None and symbol in unit_cache:
            return True

        try:
            dec_places = xml_builder._decimal_places_from_uom_rounding(
                self.uom_id.rounding if self.uom_id else None
            )
            original = (self.uom_id.name if self.uom_id else '') or symbol
            xml_str = xml_builder.build_simple_unit_xml(
                symbol, company_name, original_name=original, decimal_places=dec_places
            )
        except Exception as exc:  # noqa: BLE001
            _logger.error('[TallySync] Unit XML build failed for %s: %s', symbol, exc)
            if collect_errors is not None:
                collect_errors.append(
                    _('Unit “%s”: %s') % (symbol, str(exc))
                )
            return False

        success, response_text, _guid, error = tally_http.post_to_tally(xml_str, url)
        if success or tally_http.is_likely_duplicate_master_error(error):
            if unit_cache is not None:
                unit_cache.add(symbol)
            if not success and error:
                _logger.info(
                    '[TallySync] Unit %s treated as existing: %s', symbol, error
                )
            return True

        _logger.warning('[TallySync] Could not create Tally unit %s: %s', symbol, error)
        if collect_errors is not None and error:
            collect_errors.append(_('Unit “%s”: %s') % (symbol, error))
        return False

    def _sync_to_tally_item(self, force=False, collect_errors=None):
        """Core logic to push a Product as a Stock Item to Tally."""
        self.ensure_one()
        
        ICP = self.env['ir.config_parameter'].sudo()
        url = ICP.get_param('tally_connector.server_url', 'http://localhost:9000')
        company_name = ICP.get_param('tally_connector.company_name', '')

        if not company_name:
            err = _(
                'Tally Company Name is not configured. Open Settings → Tally Connector.'
            )
            self._tally_product_log('failed', '', '', '', err, url)
            if collect_errors is not None:
                collect_errors.append('%s — %s' % (self.display_name, err))
            return False

        if not (self.name or '').strip():
            err = _('Product has no name; cannot create a Tally stock item.')
            self._tally_product_log('skipped', '', '', '', err, url)
            if collect_errors is not None:
                collect_errors.append('%s — %s' % (self.display_name, err))
            return False

        if self.type in ('service', 'combo'):
            msg = _(
                'Skipped: services and combo products are not created as Tally stock items.'
            )
            self._tally_product_log('skipped', '', '', '', msg, url)
            return False

        stock_group, stock_group_under = self._get_tally_stock_group()
        if not stock_group:
            err = _(
                'Tally Stock Group is not configured. In Settings → Tally Connector, '
                'set “Stock Group for new items” to the exact name of a Stock Group '
                'listed in Tally under Inventory Info → Stock Groups.'
            )
            self._tally_product_log('failed', '', '', '', err, url)
            if collect_errors is not None:
                collect_errors.append('%s — %s' % (self.display_name, err))
            return False
        if stock_group.lower() == 'primary':
            err = _(
                'Stock Group is “Primary” but Tally has no such stock group. '
                'Change Settings → Tally Connector → “Stock Group for new items” '
                'to a name that exists in Tally (e.g. Finished Goods).'
            )
            self._tally_product_log('failed', '', '', '', err, url)
            if collect_errors is not None:
                collect_errors.append('%s — %s' % (self.display_name, err))
            return False

        group_xml = xml_builder.build_stock_group_xml(
            stock_group,
            company_name,
            parent_name=stock_group_under,
        )
        group_success, group_response, _group_guid, group_error = tally_http.post_to_tally(
            group_xml, url
        )
        if not group_success and not tally_http.is_likely_duplicate_master_error(group_error):
            err = _('Could not create or update Tally Stock Group "%s": %s') % (
                stock_group, group_error,
            )
            self._tally_product_log('failed', group_xml, group_response, '', err, url)
            if collect_errors is not None:
                collect_errors.append('%s — %s' % (self.display_name, err))
            return False

        # Get UoM mapping
        uom_map = self.env['tally.uom.map'].sudo().search([('uom_id', '=', self.uom_id.id)], limit=1)
        tally_uom = uom_map.tally_symbol if uom_map else 'Nos'

        unit_cache = self.env.context.get('tally_unit_cache')
        if not self._ensure_tally_simple_unit(
            tally_uom,
            company_name,
            url,
            collect_errors=collect_errors,
            unit_cache=unit_cache,
        ):
            err = _('Could not create or verify unit “%s” in Tally.') % tally_uom
            self._tally_product_log('failed', '', '', '', err, url)
            return False

        push_gst = ICP.get_param('tally_connector.master_push_gst', 'True') in (
            'True', '1', 'true',
        )
        action = (
            'Alter' if (self.tally_guid or self.tally_last_sync) else 'Create'
        )

        try:
            xml_str = xml_builder.build_stock_item_xml(
                self,
                tally_uom,
                company_name,
                stock_group_parent=stock_group,
                stock_group_under=stock_group_under,
                action=action,
                push_gst_details=push_gst,
            )
            success, response_text, guid, error = tally_http.post_to_tally(xml_str, url)
            
            self._tally_product_log(
                'success' if success else 'failed',
                xml_str,
                response_text,
                guid,
                error,
                url,
            )

            if success:
                self.with_context(skip_tally_product_sync=True).write({
                    'tally_guid': guid or self.name,
                    'tally_last_sync': fields.Datetime.now()
                })
            elif collect_errors is not None and error:
                collect_errors.append('%s — %s' % (self.display_name, error))
            return success
        except Exception as exc:
            _logger.error('[TallySync] Product sync failed for %s: %s', self.name, exc)
            err_msg = str(exc)
            self._tally_product_log('failed', '', '', '', err_msg, url)
            if collect_errors is not None:
                collect_errors.append('%s — %s' % (self.display_name, err_msg))
            return False


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    # --- Add these two related fields ---
    tally_guid = fields.Char(
        string='Tally GUID',
        related='product_variant_id.tally_guid',
        readonly=True
    )
    tally_last_sync = fields.Datetime(
        string='Last Tally Sync',
        related='product_variant_id.tally_last_sync',
        readonly=True
    )
    tally_stock_group_name = fields.Char(
        string='Tally Stock Group',
        related='categ_id.tally_stock_group_name',
        readonly=True,
    )
    tally_hsn_description = fields.Char(
        string='Tally HSN Description',
        related='product_variant_id.tally_hsn_description',
        readonly=True,
    )
    # ------------------------------------

    _TEMPLATE_TALLY_WATCH = frozenset({
        'l10n_in_hsn_code', 'name', 'uom_id', 'type',
        'taxes_id', 'supplier_taxes_id', 'categ_id',
    })

    def write(self, vals):
        res = super().write(vals)
        if self.env.context.get('skip_tally_product_sync'):
            return res
        if self._TEMPLATE_TALLY_WATCH.intersection(vals):
            self.product_variant_ids._tally_auto_sync_product_after_change(vals)
        return res

    def action_sync_to_tally(self):
        """Button action for Product Template: syncs its underlying variants to Tally."""
        for template in self:
            for variant in template.product_variant_ids:
                variant._sync_to_tally_item()
        return True
