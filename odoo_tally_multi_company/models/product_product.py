# -*- coding: utf-8 -*-
import logging
from odoo import _, fields, models
from odoo.exceptions import UserError
from odoo.addons.odoo_tally_connector.utils import xml_builder, tally_http

_logger = logging.getLogger(__name__)


class ProductProduct(models.Model):
    _inherit = "product.product"

    def _get_tally_stock_group(self):
        """Safely determine Tally Stock Group, defaulting cleanly to 'Finished Goods'."""
        group_name, parent_name = super()._get_tally_stock_group()
        if not group_name or group_name.lower() == "primary":
            group_name = self.env.context.get("tally_stock_group") or (self.categ_id.name if self.categ_id else "Primary")
        return group_name, parent_name

    def action_sync_to_tally(self):
        """Sync product master to ALL active connected Tally companies."""
        active_companies = self.env["tally.company"].search([("active", "=", True)])
        if not active_companies:
            raise UserError(_("No active Tally Prime companies found. Please configure a company in Tally Prime Companies."))

        synced_companies = []
        for product in self:
            for tally_comp in active_companies:
                succ = product._sync_to_tally_item_for_company(tally_comp)
                if succ and tally_comp.name not in synced_companies:
                    synced_companies.append(tally_comp.name)

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Product Multi-Company Sync"),
                "message": _("Product '%s' synchronized to: %s.") % (self.display_name, ", ".join(synced_companies) if synced_companies else "Tally"),
                "type": "success",
                "sticky": False,
            },
        }

    def _tally_auto_sync_product_after_change(self, vals):
        """Broadcast auto-sync product master across all active connected Tally companies."""
        ICP = self.env["ir.config_parameter"].sudo()
        if ICP.get_param("tally_connector.auto_sync_product", "False") not in ("True", "1", "true"):
            return

        active_companies = self.env["tally.company"].search([("active", "=", True)])
        if not active_companies:
            return

        for product in self:
            for tally_comp in active_companies:
                try:
                    product._sync_to_tally_item_for_company(tally_comp)
                except Exception as exc:
                    _logger.warning("[TallyMultiCompany] Broadcast product sync error for %s to %s: %s", product.name, tally_comp.name, exc)

    def _sync_to_tally_item_for_company(self, tally_company, collect_errors=None, unit_cache=None):
        """Sync product to a specific Tally company."""
        self.ensure_one()
        url = (tally_company.server_url or "").strip()
        company_name = tally_company._get_target_tally_company_name()
        stock_group, stock_group_under = self._get_tally_stock_group()

        if self.type in ("service", "combo"):
            return False

        if not (self.name or "").strip():
            err = _("Product has no name; cannot create a Tally stock item.")
            if collect_errors is not None:
                collect_errors.append(f"{self.display_name} — {err}")
            return False

        # 1. Ensure stock group in Tally
        group_xml = xml_builder.build_stock_group_xml(
            stock_group,
            company_name,
            parent_name=stock_group_under,
        )
        group_success, group_response, _group_guid, group_error = tally_http.post_to_tally(group_xml, url)

        # 2. Get UoM mapping and ensure simple unit
        uom_map = self.env["tally.uom.map"].sudo().search([("uom_id", "=", self.uom_id.id)], limit=1)
        tally_uom = (uom_map.tally_symbol if uom_map else (self.uom_id.name if self.uom_id else "Nos")) or "Nos"

        self._ensure_tally_simple_unit(
            tally_uom,
            company_name,
            url,
            collect_errors=collect_errors,
            unit_cache=unit_cache,
        )

        # 3. Build & post Stock Item XML
        ICP = self.env["ir.config_parameter"].sudo()
        push_gst = ICP.get_param("tally_connector.master_push_gst", "True") in ("True", "1", "true")
        action = "Alter" if (self.tally_guid or self.tally_last_sync) else "Create"

        item_xml = xml_builder.build_stock_item_xml(
            self,
            tally_uom,
            company_name,
            stock_group_parent=stock_group,
            stock_group_under=stock_group_under,
            action=action,
            push_gst_details=push_gst,
        )

        success, response_xml, guid, error = tally_http.post_to_tally(item_xml, url)
        status = "success" if (success or tally_http.is_likely_duplicate_master_error(error)) else "failed"

        self.env["tally.sync.log"].sudo().create({
            "tally_company_id": tally_company.id,
            "move_name": f"PRODUCT: {self.display_name}",
            "status": status,
            "tally_guid": guid or "",
            "request_xml": item_xml,
            "response_xml": response_xml or "",
            "error_message": error or "",
            "tally_server_url": url,
        })

        if success or tally_http.is_likely_duplicate_master_error(error):
            self.with_context(skip_tally_product_sync=True).sudo().write({
                "tally_guid": guid or self.tally_guid or self.default_code or self.name,
                "tally_last_sync": fields.Datetime.now(),
            })
            return True
        else:
            if collect_errors is not None and error:
                collect_errors.append(f"{self.display_name} — {error}")
            return False


class ProductTemplate(models.Model):
    _inherit = "product.template"

    def action_sync_to_tally(self):
        """Sync product template variants to ALL active connected Tally companies."""
        for template in self:
            template.product_variant_ids.action_sync_to_tally()
        return True
