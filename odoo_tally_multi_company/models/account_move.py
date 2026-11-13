# -*- coding: utf-8 -*-
import logging
from odoo import _, api, fields, models
from odoo.exceptions import UserError
# pyrefly: ignore [missing-import]
from odoo.addons.odoo_tally_connector.utils import xml_builder, tally_http

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = "account.move"

    tally_company_id = fields.Many2one(
        "tally.company",
        string="Assigned Tally Company",
        compute="_compute_tally_company_id",
        store=True,
        readonly=False,
        index=True,
        tracking=True,
        help="Target Tally Prime company for this document (derived from partner or selected manually).",
    )

    @api.depends("partner_id", "partner_id.tally_company_id", "partner_id.commercial_partner_id.tally_company_id", "line_ids.partner_id")
    def _compute_tally_company_id(self):
        for move in self:
            partner = move.partner_id or (move.line_ids.filtered(lambda l: l.partner_id)[:1].partner_id if move.line_ids else False)
            if partner:
                move.tally_company_id = partner._get_effective_tally_company()
            elif not move.tally_company_id:
                # Default to first active Tally company if no partner
                move.tally_company_id = self.env["tally.company"].search([("active", "=", True)], limit=1)

    def _is_tally_syncable(self):
        """Allow invoices, bills, credit notes, receipts, payments, and manual journal entries."""
        self.ensure_one()
        return super()._is_tally_syncable() or self.move_type == "entry"

    def _get_voucher_type(self):
        """
        Dynamically determine the exact persisted view based on whether the document
        contains physical stock invoice lines or pure ledger lines.
        """
        voucher_type, persisted_view = super()._get_voucher_type()
        if self.move_type == "entry" and not self.origin_payment_id:
            voucher_type = "Journal"
            persisted_view = "Accounting Voucher View"
        elif not xml_builder.move_has_stock_invoice_lines(self):
            persisted_view = "Accounting Voucher View"
        else:
            persisted_view = "Invoice Voucher View"
        return voucher_type, persisted_view

    def _ensure_partner_in_tally(self, url, company_name, ledger_map_dict):
        """Override to sync the partner and delivery-address children directly to the assigned Tally company."""
        partner = self.partner_id or (self.line_ids.filtered(lambda l: l.partner_id)[:1].partner_id if self.line_ids else False)
        if not partner:
            return
        tally_comp = self.tally_company_id or partner._get_effective_tally_company()
        if not tally_comp:
            return super()._ensure_partner_in_tally(url, company_name, ledger_map_dict)

        ledger_partner = partner._tally_ledger_partner()
        ledger_partner._sync_to_tally_ledger_for_company(tally_comp, move=self)

        ship = self.partner_shipping_id
        if ship and ship.id != partner.id:
            ship._sync_to_tally_ledger_for_company(tally_comp, move=self)

    def _ensure_products_in_tally(self, url, company_name, uom_map_dict):
        """Override to sync all invoice line stock items directly to the assigned Tally company."""
        partner = self.partner_id or (self.line_ids.filtered(lambda l: l.partner_id)[:1].partner_id if self.line_ids else False)
        tally_comp = self.tally_company_id or (partner and partner._get_effective_tally_company())
        if not tally_comp:
            return super()._ensure_products_in_tally(url, company_name, uom_map_dict)

        for line in self.invoice_line_ids.filtered(lambda l: xml_builder._is_stock_invoice_line(l)):
            if line.product_id:
                line.product_id._sync_to_tally_item_for_company(tally_comp)

    def action_sync_to_tally(self):
        """Manual sync button on Invoice / Bill / Journal Entry form."""
        for move in self:
            partner = move.partner_id or (move.line_ids.filtered(lambda l: l.partner_id)[:1].partner_id if move.line_ids else False)
            tally_comp = move.tally_company_id or (partner and partner._get_effective_tally_company()) or self.env["tally.company"].search([("active", "=", True)], limit=1)
            if not tally_comp:
                return {
                    "type": "ir.actions.client",
                    "tag": "display_notification",
                    "params": {
                        "title": _("Cannot Sync to Tally"),
                        "message": _(
                            "Please select an Assigned Tally Company in the Tally Integration tab before syncing."
                        ),
                        "type": "warning",
                        "sticky": True,
                    },
                }
            if not move._is_tally_syncable():
                raise UserError(
                    f'Document type "{move.move_type}" is not eligible for Tally sync.\n'
                    f"Only invoices, credit notes, receipts, payments, and journal entries can be synced."
                )
            if move.state != "posted":
                raise UserError(
                    "Only posted (confirmed) documents can be synced to Tally.\n"
                    f'"{move.name}" is currently in state: {move.state}.'
                )
            move._sync_to_tally(force=True)

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Tally Sync"),
                "message": _("Sync completed for %s document(s). Check Sync Logs for details.") % len(self),
                "type": "info",
                "sticky": False,
            },
        }

    def _sync_to_tally(self, force=False):
        """Dynamic multi-company sync dispatcher for posted moves with smart fallback."""
        self.ensure_one()
        # For manual journal entries without a header partner, pull from the journal lines in memory
        partner = self.partner_id or (self.line_ids.filtered(lambda l: l.partner_id)[:1].partner_id if self.line_ids else False)
        tally_comp = self.tally_company_id or (partner and partner._get_effective_tally_company()) or self.env["tally.company"].search([("active", "=", True)], limit=1)
        if not tally_comp:
            msg = _("Sync skipped: No Tally Company assigned to document '%s'.") % self.name
            _logger.warning("[TallyMultiCompany] %s", msg)
            self.sudo().write({"tally_sync_status": "skipped"})
            self._write_log("skipped", "", "", "", msg)
            return

        if not tally_comp.active:
            msg = _("Sync skipped: Assigned Tally Company '%s' is inactive.") % tally_comp.name
            _logger.warning("[TallyMultiCompany] %s for move %s", msg, self.name)
            self.sudo().write({"tally_sync_status": "skipped"})
            self._write_log("skipped", "", "", "", msg)
            return

        url = (tally_comp.server_url or "").strip()
        company_name = tally_comp._get_target_tally_company_name()

        # 1. Pre-flight ensure partner and products exist in target Tally company
        ledger_map_dict = self._get_ledger_map_dict()
        if partner:
            self._ensure_partner_in_tally(url, company_name, ledger_map_dict)
        if hasattr(self, "invoice_line_ids") and self.invoice_line_ids:
            self._ensure_products_in_tally(url, company_name, self._get_uom_map_dict())

        _logger.info(
            "[TallyMultiCompany] Syncing move %s to Tally Company '%s' at '%s'",
            self.name, company_name, url
        )

        # 2. Main sync execution (with partner city mapped to Tally destination)
        ship_partner = getattr(self, "partner_shipping_id", None)
        dest = (ship_partner and getattr(ship_partner, "city", False))
        if not dest:
            dest_partner = getattr(self, "partner_id", None)
            dest = (dest_partner and getattr(dest_partner, "city", False))
        dest = dest.strip() if dest and isinstance(dest, str) else False

        orig_post = getattr(tally_http, "post_to_tally", None)

        def _custom_post_to_tally(xml_data, post_url, **kwargs):
            if dest and isinstance(xml_data, str) and "<VOUCHER" in xml_data:
                import re
                import xml.sax.saxutils as saxutils
                escaped_dest = saxutils.escape(dest)
                if "<BASICFINALDESTINATION>" in xml_data:
                    xml_data = re.sub(
                        r"<BASICFINALDESTINATION>.*?</BASICFINALDESTINATION>",
                        f"<BASICFINALDESTINATION>{escaped_dest}</BASICFINALDESTINATION>",
                        xml_data,
                    )
                elif "</VOUCHER>" in xml_data:
                    xml_data = xml_data.replace(
                        "</VOUCHER>",
                        f"<BASICFINALDESTINATION>{escaped_dest}</BASICFINALDESTINATION></VOUCHER>",
                    )
            return orig_post(xml_data, post_url, **kwargs)

        try:
            if orig_post:
                tally_http.post_to_tally = _custom_post_to_tally
            res = super(
                AccountMove,
                self.with_context(
                    tally_server_url=url,
                    tally_company_name=company_name,
                    tally_company_id=tally_comp.id,
                ),
            )._sync_to_tally(force=force)
        finally:
            if orig_post:
                tally_http.post_to_tally = orig_post

        # 3. Smart Accounting Fallback: Only for non-stock documents / pure accounting entries
        has_stock = xml_builder.move_has_stock_invoice_lines(self)
        if self.tally_sync_status == "failed" and not has_stock and self.move_type in ("out_refund", "in_refund", "out_invoice", "in_invoice", "entry"):
            voucher_type, _ = self._get_voucher_type()
            try:
                xml_fallback = xml_builder.build_voucher_xml(
                    move=self,
                    company_name=company_name,
                    ledger_map_dict=ledger_map_dict,
                    voucher_type=voucher_type,
                    persisted_view="Accounting Voucher View",
                    include_inventory=False,
                    voucher_action="Create",
                    minimal=True,
                )
                if xml_fallback:
                    succ, resp, guid, err = tally_http.post_to_tally(xml_fallback, url)
                    if succ:
                        self.sudo().write({
                            "tally_sync_status": "synced",
                            "tally_last_sync": fields.Datetime.now(),
                            "tally_guid": guid or self.name,
                        })
                        self._write_log("success", xml_fallback, resp, guid, "(Synced via Accounting Fallback)")
                        _logger.info("[TallyMultiCompany] %s successfully synced via accounting fallback.", self.name)
            except Exception as exc:
                _logger.warning("[TallyMultiCompany] Fallback sync error for %s: %s", self.name, exc)

        return res

    def _write_log(self, status, request_xml, response_xml, guid, error_message=""):
        """Override to tag tally_company_id and specific URL on all sync logs."""
        partner = self.partner_id or (self.line_ids.filtered(lambda l: l.partner_id)[:1].partner_id if self.line_ids else False)
        tally_comp = self.tally_company_id or (partner and partner._get_effective_tally_company()) or self.env["tally.company"].search([("active", "=", True)], limit=1)
        url = tally_comp.server_url if tally_comp else self.env.context.get("tally_server_url", "")
        self.env["tally.sync.log"].sudo().create(
            {
                "tally_company_id": tally_comp.id if tally_comp else False,
                "move_id": self.id,
                "move_name": self.name,
                "status": status,
                "tally_guid": guid or "",
                "request_xml": request_xml or "",
                "response_xml": response_xml or "",
                "error_message": error_message or "",
                "tally_server_url": url,
            }
        )
