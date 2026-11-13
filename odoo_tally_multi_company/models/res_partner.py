# -*- coding: utf-8 -*-
import logging
from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ResPartner(models.Model):
    _inherit = "res.partner"

    tally_company_id = fields.Many2one(
        "tally.company",
        string="Assigned Tally Company",
        index=True,
        tracking=True,
        help="The primary Tally Prime company to which invoices, bills, and payments for this partner will be synced.",
    )

    def _default_tally_partner_group(self):
        search_mode = self.env.context.get("res_partner_search_mode")
        if (
            search_mode == "supplier"
            or bool(self.env.context.get("default_supplier_rank"))
            or bool(self.env.context.get("search_default_supplier"))
        ):
            return "creditor"
        if (
            search_mode == "customer"
            or bool(self.env.context.get("default_customer_rank"))
            or bool(self.env.context.get("search_default_customer"))
        ):
            return "debtor"
        return "auto"

    tally_partner_group = fields.Selection(
        [
            ("auto", "Auto Detect"),
            ("creditor", "Sundry Creditors (Vendor)"),
            ("debtor", "Sundry Debtors (Customer)"),
        ],
        default=_default_tally_partner_group,
        string="Tally Ledger Group",
        tracking=True,
        help="Choose whether this contact is created under Sundry Creditors (Vendor) or Sundry Debtors (Customer) in Tally Prime.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        search_mode = self.env.context.get("res_partner_search_mode")
        is_vendor_ctx = (
            search_mode == "supplier"
            or bool(self.env.context.get("default_supplier_rank"))
            or bool(self.env.context.get("search_default_supplier"))
        )
        is_customer_ctx = (
            search_mode == "customer"
            or bool(self.env.context.get("default_customer_rank"))
            or bool(self.env.context.get("search_default_customer"))
        )
        for vals in vals_list:
            if not vals.get("tally_partner_group") or vals.get("tally_partner_group") == "auto":
                if is_vendor_ctx or vals.get("supplier_rank", 0) > vals.get("customer_rank", 0):
                    vals["tally_partner_group"] = "creditor"
                elif is_customer_ctx or vals.get("customer_rank", 0) > vals.get("supplier_rank", 0):
                    vals["tally_partner_group"] = "debtor"
        return super().create(vals_list)

    def _get_effective_tally_company(self):
        """Return the effective Tally company for this partner or its commercial parent."""
        self.ensure_one()
        if self.tally_company_id:
            return self.tally_company_id
        if self.commercial_partner_id and self.commercial_partner_id.tally_company_id:
            return self.commercial_partner_id.tally_company_id
        if self.parent_id and self.parent_id.tally_company_id:
            return self.parent_id.tally_company_id
        # Fallback to the first active Tally company
        return self.env["tally.company"].search([("active", "=", True)], limit=1)

    def action_test_tally_connection(self):
        """Test connection to the assigned Tally company directly from the partner form."""
        self.ensure_one()
        tally_comp = self._get_effective_tally_company()
        if not tally_comp:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("No Tally Company Assigned"),
                    "message": _("Please select an Assigned Tally Company in the field above before testing connection."),
                    "type": "warning",
                    "sticky": True,
                },
            }
        return tally_comp.action_test_connection()

    def action_sync_to_tally(self):
        """Sync partner master to ALL active connected Tally companies."""
        active_companies = self.env["tally.company"].search([("active", "=", True)])
        if not active_companies:
            raise UserError(_("No active Tally Prime companies found. Please configure a company in Tally Prime Companies."))

        synced_companies = []
        for partner in self:
            for tally_comp in active_companies:
                succ = partner._sync_to_tally_ledger_for_company(tally_comp)
                if succ and tally_comp.name not in synced_companies:
                    synced_companies.append(tally_comp.name)

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Partner Multi-Company Sync"),
                "message": _("Partner '%s' synchronized to: %s.") % (self.display_name, ", ".join(synced_companies) if synced_companies else "Tally"),
                "type": "success",
                "sticky": False,
            },
        }

    def _tally_auto_sync_after_change(self, vals):
        """Broadcast auto-sync partner master across all active connected Tally companies."""
        ICP = self.env["ir.config_parameter"].sudo()
        if ICP.get_param("tally_connector.auto_sync_partner", "False") not in ("True", "1", "true"):
            return

        active_companies = self.env["tally.company"].search([("active", "=", True)])
        if not active_companies:
            return

        for partner in self:
            for tally_comp in active_companies:
                try:
                    partner._sync_to_tally_ledger_for_company(tally_comp)
                except Exception as exc:
                    _logger.warning("[TallyMultiCompany] Broadcast auto-sync error for partner %s to %s: %s", partner.name, tally_comp.name, exc)

    def _sync_to_tally_ledger_for_company(self, tally_company, move=None):
        """Sync this partner to a specific Tally company."""
        self.ensure_one()
        url = (tally_company.server_url or "").strip()
        company_name = tally_company._get_target_tally_company_name()

        _logger.info(
            "[TallyMultiCompany] Syncing partner '%s' to Tally Company '%s' at '%s'",
            self.display_name, company_name, url
        )

        from odoo.addons.odoo_tally_connector.utils import xml_builder, tally_http

        # Dynamically resolve group names from mapping configuration if available
        payable_acc = self.property_account_payable_id
        payable_map = self.env["tally.ledger.map"].sudo().search([("account_id", "=", payable_acc.id)], limit=1) if payable_acc else False
        creditor_group = (payable_map.tally_group if payable_map and payable_map.tally_group else "Sundry Creditors").strip()

        receivable_acc = self.property_account_receivable_id
        receivable_map = self.env["tally.ledger.map"].sudo().search([("account_id", "=", receivable_acc.id)], limit=1) if receivable_acc else False
        debtor_group = (receivable_map.tally_group if receivable_map and receivable_map.tally_group else "Sundry Debtors").strip()

        # Determine Tally Group based on explicit setting or dynamic detection
        move_type = getattr(move, "move_type", "") if move else ""
        payment = getattr(move, "origin_payment_id", None) if move else None
        if payment and getattr(payment, "partner_type", "") == "customer":
            tally_group = debtor_group
        elif payment and getattr(payment, "partner_type", "") == "supplier":
            tally_group = creditor_group
        elif move_type in ("in_invoice", "in_refund", "in_receipt"):
            tally_group = creditor_group
        elif move_type in ("out_invoice", "out_refund", "out_receipt"):
            tally_group = debtor_group
        elif self.tally_partner_group == "creditor":
            tally_group = creditor_group
        elif self.tally_partner_group == "debtor":
            tally_group = debtor_group
        elif self.supplier_rank > self.customer_rank or (self.supplier_rank > 0 and self.customer_rank <= 0):
            tally_group = creditor_group
        elif self.customer_rank > self.supplier_rank or (self.customer_rank > 0 and self.supplier_rank <= 0):
            tally_group = debtor_group
        else:
            search_mode = self.env.context.get("res_partner_search_mode")
            default_supplier = self.env.context.get("default_supplier_rank", 0) > 0 or self.env.context.get("search_default_supplier")
            is_vendor_context = search_mode == "supplier" or bool(default_supplier)
            if is_vendor_context:
                tally_group = creditor_group
            else:
                has_bills = self.env["account.move"].search_count([("partner_id", "=", self.id), ("move_type", "in", ("in_invoice", "in_refund"))])
                has_invoices = self.env["account.move"].search_count([("partner_id", "=", self.id), ("move_type", "in", ("out_invoice", "out_refund"))])
                if has_bills > has_invoices:
                    tally_group = creditor_group
                else:
                    tally_group = debtor_group

        xml_str = xml_builder.build_ledger_master_xml(
            partner=self,
            tally_group=tally_group,
            company_name=company_name,
        )

        success, response_xml, guid, error = tally_http.post_to_tally(xml_str, url)

        # Write log tagged with tally_company_id
        status = "success" if (success or tally_http.is_likely_duplicate_master_error(error)) else "failed"
        self.env["tally.sync.log"].sudo().create({
            "tally_company_id": tally_company.id,
            "move_name": f"Partner: {self.name}",
            "status": status,
            "request_xml": xml_str,
            "response_xml": response_xml or "",
            "error_message": error or "",
            "tally_guid": guid or "",
            "tally_server_url": url,
        })

        if success or tally_http.is_likely_duplicate_master_error(error):
            self.sudo().write({
                "tally_guid": guid or self.tally_guid or self.name,
                "tally_last_sync": fields.Datetime.now(),
            })
            _logger.info("[TallyMultiCompany] Partner '%s' synced successfully to '%s'.", self.name, company_name)
            return True
        else:
            _logger.warning("[TallyMultiCompany] Partner '%s' sync failed: %s", self.name, error)
            return False
