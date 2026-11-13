# -*- coding: utf-8 -*-
"""
models/account_move.py

Extends account.move with Tally sync fields, auto-sync on action_post(),
manual retry button, and the full sync orchestration logic including
master data pre-flight checks.
"""

import logging
import re
from datetime import date
from calendar import monthrange

from odoo import api, fields, models
from odoo.exceptions import UserError

from odoo.addons.odoo_tally_connector.utils import xml_builder, tally_http

_logger = logging.getLogger(__name__)

# Document types that are eligible for Tally sync
SYNCABLE_MOVE_TYPES = {
    "out_invoice",  # Customer Invoice → Sales Voucher
    "in_invoice",  # Vendor Bill      → Purchase Voucher
    "out_refund",  # Customer Credit Note
    "in_refund",  # Vendor Credit Note / Debit Note (Purchase)
    "out_receipt",  # Sales Receipt (Odoo 19+)
    "in_receipt",  # Purchase Receipt (Odoo 19+)
}


class AccountMove(models.Model):
    _inherit = "account.move"

    def _is_tally_syncable(self):
        """Invoices/receipts plus standard Odoo payment journal entries."""
        self.ensure_one()
        return self.move_type in SYNCABLE_MOVE_TYPES or (
            self.move_type == "entry" and bool(self.origin_payment_id)
        )

    # ------------------------------------------------------------------ #
    # Tally Sync Fields                                                    #
    # ------------------------------------------------------------------ #

    tally_sync_status = fields.Selection(
        selection=[
            ("pending", "Pending"),
            ("synced", "Synced"),
            ("failed", "Failed"),
            ("skipped", "Skipped"),
        ],
        string="Tally Status",
        default="pending",
        copy=False,
        index=True,
        tracking=True,
        help="Current synchronization status with Tally Prime.",
    )
    tally_guid = fields.Char(
        string="Tally GUID",
        copy=False,
        readonly=True,
        index=True,
        help="Unique identifier returned by Tally on successful sync. "
        "If set, this document has been successfully sent to Tally.",
    )
    tally_last_sync = fields.Datetime(
        string="Last Tally Sync",
        copy=False,
        readonly=True,
    )
    tally_sync_log_ids = fields.One2many(
        comodel_name="tally.sync.log",
        inverse_name="move_id",
        string="Tally Sync Logs",
        readonly=True,
    )
    tally_sync_log_count = fields.Integer(
        string="Sync Logs",
        compute="_compute_tally_sync_log_count",
    )

    tally_gst_sync_status = fields.Selection(
        selection=[
            ("pending", "Pending"),
            ("synced", "Synced"),
            ("failed", "Failed"),
            ("skipped", "Skipped"),
        ],
        string="Tally GST Status",
        default="pending",
        copy=False,
        index=True,
        tracking=True,
        help="E-Invoice / e-Way Bill sync status with Tally Prime.",
    )
    tally_gst_last_sync = fields.Datetime(
        string="Last GST Tally Sync",
        copy=False,
        readonly=True,
    )
    tally_gst_sync_log_ids = fields.One2many(
        comodel_name="tally.gst.sync.log",
        inverse_name="move_id",
        string="Tally GST Sync Logs",
        readonly=True,
    )
    tally_gst_sync_log_count = fields.Integer(
        string="GST Sync Logs",
        compute="_compute_tally_gst_sync_log_count",
    )
    tally_has_gst_data = fields.Boolean(
        string="Has E-Invoice / E-Way Bill",
        compute="_compute_tally_has_gst_data",
    )

    # ------------------------------------------------------------------ #
    # Computed fields                                                      #
    # ------------------------------------------------------------------ #

    @api.depends("tally_gst_sync_log_ids")
    def _compute_tally_gst_sync_log_count(self):
        for move in self:
            move.tally_gst_sync_log_count = len(move.tally_gst_sync_log_ids)

    def _compute_tally_has_gst_data(self):
        from odoo.addons.odoo_tally_connector.utils.xml_builder import (
            get_move_gst_compliance_snapshot,
        )

        for move in self:
            if move.move_type not in ("out_invoice", "out_refund", "out_receipt"):
                move.tally_has_gst_data = False
                continue
            try:
                move.tally_has_gst_data = get_move_gst_compliance_snapshot(move)[
                    'has_data'
                ]
            except Exception:
                move.tally_has_gst_data = False

    @api.depends("tally_sync_log_ids")
    def _compute_tally_sync_log_count(self):
        for move in self:
            move.tally_sync_log_count = len(move.tally_sync_log_ids)

    # ------------------------------------------------------------------ #
    # Override action_post — trigger auto-sync on invoice confirmation    #
    # ------------------------------------------------------------------ #

    def action_post(self):
        """Override to automatically sync eligible moves to Tally after posting."""
        result = super().action_post()

        ICP = self.env["ir.config_parameter"].sudo()
        sync_active = ICP.get_param("tally_connector.sync_active", "False")

        if sync_active in ("True", "1", "true"):
            # Payments: manual "Sync to Tally" only — never auto-sync on post.
            sync_moves = self.filtered(
                lambda m: m._is_tally_syncable() and not m.origin_payment_id
            )
            for move in sync_moves:
                try:
                    move._sync_to_tally()
                except Exception as exc:  # noqa: BLE001
                    # Non-blocking: sync failure must NOT prevent invoice confirmation
                    _logger.error(
                        "[TallySync] Auto-sync failed for %s: %s", move.name, exc
                    )

        return result

    # ------------------------------------------------------------------ #
    # Manual sync button                                                   #
    # ------------------------------------------------------------------ #

    def action_sync_to_tally(self):
        """
        Manual 'Sync to Tally' button handler.
        Can be used for initial sync or retries on failed documents.
        """
        for move in self:
            if not move._is_tally_syncable():
                raise UserError(
                    f'Document type "{move.move_type}" is not eligible for Tally sync.\n'
                    f"Only invoices, credit notes, receipts, and payments can be synced."
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
                "title": "Tally Sync",
                "message": f"Sync completed for {len(self)} document(s). Check Sync Logs for details.",
                "type": "info",
                "sticky": False,
            },
        }

    def action_view_tally_logs(self):
        """Open the sync logs for this invoice."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": f"Tally Sync Logs — {self.name}",
            "res_model": "tally.sync.log",
            "view_mode": "list,form",
            "domain": [("move_id", "=", self.id)],
            "context": {"default_move_id": self.id},
        }

    def action_sync_gst_to_tally(self):
        """Push e-Invoice (IRN) and e-Way Bill details to Tally."""
        for move in self:
            if move.move_type not in ("out_invoice", "out_refund", "out_receipt"):
                raise UserError(
                    f'Document type "{move.move_type}" does not support '
                    "e-Invoice / e-Way Bill sync to Tally."
                )
            if move.state != "posted":
                raise UserError(
                    "Only posted invoices can sync e-Invoice / e-Way Bill to Tally.\n"
                    f'"{move.name}" is currently in state: {move.state}.'
                )
            move._sync_gst_to_tally(force=True)

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Tally GST Sync",
                "message": (
                    f"E-Invoice / e-Way Bill sync completed for {len(self)} document(s). "
                    "Check GST Sync Logs for details."
                ),
                "type": "info",
                "sticky": False,
            },
        }

    def action_view_tally_gst_logs(self):
        """Open e-Invoice / e-Way Bill sync logs for this invoice."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": f"Tally GST Logs — {self.name}",
            "res_model": "tally.gst.sync.log",
            "view_mode": "list,form",
            "domain": [("move_id", "=", self.id)],
            "context": {"default_move_id": self.id},
        }

    # ------------------------------------------------------------------ #
    # Core sync orchestrator                                               #
    # ------------------------------------------------------------------ #

    def _sync_to_tally(self, force=False):
        """
        Main sync orchestrator for a single account.move.

        Steps:
            1. Duplicate guard — skip if already synced (unless force=True).
            2. Load configuration parameters.
            3. Build ledger map and voucher type.
            4. Pre-flight: ensure partner ledger exists in Tally.
            5. Pre-flight: ensure stock items exist in Tally (if inventory mode).
            6. Build voucher XML.
            7. POST to Tally.
            8. Record result in tally.sync.log and update move fields.

        Args:
            force (bool): If True, re-sync even if tally_guid is already set.
        """
        self.ensure_one()

        _logger.debug(
            "[TallySync] Entering _sync_to_tally for move %s (id=%s, force=%s, state=%s)",
            self.name, self.id, force, self.state
        )

        # ---- 1. Duplicate guard ----------------------------------------
        if not force and self.tally_sync_status == "synced":
            _logger.info(
                "[TallySync] Skipping %s — already synced to Tally",
                self.name,
            )
            self._write_log(
                "skipped",
                "",
                "",
                "",
                "Skipped: document already synced. Use “Sync to Tally” again (it forces re-send) "
                "if you intentionally need to update Tally.",
            )
            return

        # ---- 2. Load config --------------------------------------------
        ICP = self.env["ir.config_parameter"].sudo()
        url = self.env.context.get("tally_server_url") or ICP.get_param("tally_connector.server_url", "http://localhost:9000")
        company_name = self.env.context.get("tally_company_name") or ICP.get_param("tally_connector.company_name", "")
        include_inventory = ICP.get_param(
            "tally_connector.include_inventory", "False"
        ) in ("True", "1", "true")
        auto_create_masters = ICP.get_param(
            "tally_connector.auto_create_masters", "True"
        ) in ("True", "1", "true")
        godown_name = ICP.get_param("tally_connector.godown_name", "Main Location")
        batch_name = ICP.get_param("tally_connector.batch_name", "Primary Batch")

        if not company_name:
            err = "Tally Company Name is not configured. Go to Settings → Tally Connector."
            self._write_log("failed", "", "", "", err)
            self.tally_sync_status = "failed"
            _logger.error("[TallySync] %s", err)
            return

        # ---- 3. Build mapping dicts ------------------------------------
        ledger_map_dict = self._get_ledger_map_dict()
        voucher_type, persisted_view = self._get_voucher_type()
        has_stock_lines = xml_builder.move_has_stock_invoice_lines(self)
        if has_stock_lines:
            include_inventory = True
            persisted_view = "Invoice Voucher View"
        uom_map_dict = self._get_uom_map_dict() if include_inventory else {}

        # ---- 4. Pre-flight: partner ledger in Tally --------------------
        if auto_create_masters and self.partner_id:
            self._ensure_partner_in_tally(url, company_name, ledger_map_dict)

        # ---- 5. Pre-flight: stock items in Tally -----------------------
        if auto_create_masters and include_inventory:
            self._ensure_products_in_tally(url, company_name, uom_map_dict)

        # ---- 6. Build voucher XML --------------------------------------
        recreate_note = ""
        try:
            # Alter works only when we have Tally's real internal GUID.
            # Without that GUID, Tally cannot identify which voucher to alter.
            tally_guid = (self.tally_guid or "").strip()
            has_real_tally_guid = bool(
                tally_guid and tally_guid != (self.name or "").strip()
            )
            already_synced = self.tally_sync_status == 'synced'
            # Tally does not refresh consignee party details on Alter unless the
            # voucher is identified by a stored internal id. Without that id,
            # re-import as Create (delete the old Tally voucher first).
            if force and already_synced and not has_real_tally_guid:
                voucher_action = "Create"
                recreate_note = (
                    "Re-created voucher in Tally (no stored voucher GUID). "
                    "Delete the previous Tally copy of this invoice if it still exists."
                )
            else:
                voucher_action = (
                    "Alter"
                    if has_real_tally_guid and (force or already_synced)
                    else "Create"
                )
            xml_str = xml_builder.build_voucher_xml(
                move=self,
                company_name=company_name,
                ledger_map_dict=ledger_map_dict,
                voucher_type=voucher_type,
                persisted_view=persisted_view,
                uom_map_dict=uom_map_dict,
                include_inventory=include_inventory,
                voucher_action=voucher_action,
                godown_name=godown_name,
                batch_name=batch_name,
            )
        except ValueError as exc:
            err = str(exc)
            _logger.error("[TallySync] XML build error for %s: %s", self.name, err)
            self._write_log("failed", "", "", "", err)
            self.tally_sync_status = "failed"
            return

        # ---- 7. POST to Tally (Multi-Stage Smart Sync) ------------------
        # Stage 1: Initial Attempt (Normal)
        success, response_text, guid, error = tally_http.post_to_tally(xml_str, url)

        # Track the first error (usually the most important inventory/master error)
        first_attempt_error = error if not success else ""
        status_note = recreate_note

        # Stage 2: Alter Retry (Handles duplicates)
        if (
            not success
            and voucher_action == "Create"
            and (has_real_tally_guid or force)
            and tally_http.voucher_import_retry_as_alter(response_text)
        ):
            try:
                xml_alter = xml_builder.build_voucher_xml(
                    move=self,
                    company_name=company_name,
                    ledger_map_dict=ledger_map_dict,
                    voucher_type=voucher_type,
                    persisted_view=persisted_view,
                    uom_map_dict=uom_map_dict,
                    include_inventory=include_inventory,
                    voucher_action="Alter",
                    minimal=False,
                    godown_name=godown_name,
                    batch_name=batch_name,
                )
                if xml_alter:
                    success, response_text, guid, error = tally_http.post_to_tally(
                        xml_alter, url
                    )
                    if success:
                        xml_str = xml_alter
                        status_note = "(Stage 2: Altered)"
            except Exception:
                pass

        # Stage 3: Minimal Retry (Stripping legacy/problematic tags)
        if not success and tally_http.voucher_import_retry_as_alter(response_text):
            try:
                xml_min = xml_builder.build_voucher_xml(
                    move=self,
                    company_name=company_name,
                    ledger_map_dict=ledger_map_dict,
                    voucher_type=voucher_type,
                    persisted_view=persisted_view,
                    uom_map_dict=uom_map_dict,
                    include_inventory=include_inventory,
                    voucher_action="Alter"
                    if (has_real_tally_guid or force)
                    else "Create",
                    minimal=True,
                    godown_name=godown_name,
                    batch_name=batch_name,
                )
                if xml_min:
                    success, response_text, guid, error = tally_http.post_to_tally(
                        xml_min, url
                    )
                    if success:
                        xml_str = xml_min
                        status_note = "(Stage 3: Minimal)"
            except Exception:
                pass

        # Stage 4: Minimal Journal Retry (Most compatible mode)
        # ONLY fallback if inventory is NOT required, otherwise we hide the real error
        if (
            not success
            and not include_inventory
            and not has_stock_lines
            and tally_http.voucher_import_retry_as_alter(response_text)
        ):
            try:
                xml_jou = xml_builder.build_voucher_xml(
                    move=self,
                    company_name=company_name,
                    ledger_map_dict=ledger_map_dict,
                    voucher_type=voucher_type,
                    persisted_view="Accounting Voucher View",
                    uom_map_dict=uom_map_dict,
                    include_inventory=False,
                    voucher_action="Create",
                    minimal=True,
                    godown_name=godown_name,
                    batch_name=batch_name,
                )
                if xml_jou:
                    success, response_text, guid, error = tally_http.post_to_tally(
                        xml_jou, url
                    )
                    if success:
                        xml_str = xml_jou
                        status_note = "(Stage 4 Fallback: Accounting Only)"
            except Exception:
                pass

        # ---- 8. Record result ------------------------------------------
        status = "success" if success else "failed"
        err_out = error or ""

        # If we succeeded via a fallback, include the reason Stage 1 failed
        if success and status_note:
            err_out = f"NOTE: {status_note}\n\nInitial Inventory Sync (Stage 1) failed with:\n{first_attempt_error}\n\n{err_out}"

        if not success:
            err_out = f"{err_out}\n\n{self._tally_request_diagnostics(xml_str)}"
        self._write_log(status, xml_str, response_text, guid, err_out)

        if success:
            self.write(
                {
                    "tally_sync_status": "synced",
                    "tally_guid": (guid or "").strip(),
                    "tally_last_sync": fields.Datetime.now(),
                }
            )
            _logger.info(
                "[TallySync] OK %s synced (Tally GUID: %s)",
                self.name,
                (guid or "").strip() or "(not returned in response)",
            )
        else:
            self.write({"tally_sync_status": "failed"})
            _logger.warning("[TallySync] FAILED %s failed: %s", self.name, error)

    def _sync_gst_to_tally(self, force=False):
        """Push only e-Invoice / e-Way Bill fields to an existing Tally voucher."""
        self.ensure_one()

        ICP = self.env["ir.config_parameter"].sudo()
        url = ICP.get_param("tally_connector.server_url", "http://localhost:9000")
        company_name = ICP.get_param("tally_connector.company_name", "")

        if not company_name:
            err = (
                "Tally Company Name is not configured. "
                "Go to Settings → Tally Connector."
            )
            self._write_gst_log(
                "failed", {}, "", "", "", False, False, err, url
            )
            self.tally_gst_sync_status = "failed"
            return

        if self.tally_sync_status != "synced" and not force:
            note = (
                "Invoice is not synced to Tally yet. Sync the full invoice first, "
                "then run e-Invoice / e-Way Bill sync."
            )
            self._write_gst_log(
                "skipped", {}, "", "", "", False, False, note, url
            )
            self.tally_gst_sync_status = "skipped"
            return

        voucher_type, _persisted_view = self._get_voucher_type()
        tally_guid = (self.tally_guid or "").strip()
        vch_num = (self.name or str(self.id)).strip()
        has_real_tally_guid = bool(tally_guid and tally_guid != vch_num)
        voucher_action = (
            "Alter"
            if force and (has_real_tally_guid or self.tally_sync_status == "synced")
            else "Create"
        )

        include_inventory = ICP.get_param(
            "tally_connector.include_inventory", "False"
        ) in ("True", "1", "true")
        stock_lines = self.invoice_line_ids.filtered(lambda l: l.product_id)
        inventory_note = ""
        if stock_lines and not include_inventory:
            inventory_note = (
                "NOTE: Tally shows “Provide GST/e-Way Bill details” only on "
                "**Item Invoice** vouchers (stock items). Enable "
                "“Include Stock Item Entries” in Tally Connector settings and "
                "Re-Sync the full invoice, then run GST sync again.\n\n"
            )

        snapshot = xml_builder.get_move_gst_compliance_snapshot(self)
        flags = {"einvoice": False, "ewaybill": False}

        try:
            # Minimal GST XML — no ledger / stock mappings required; sets
            # VCHENTRYMODE=Item Invoice when the invoice has product lines.
            xml_str, flags, snapshot = xml_builder.build_gst_compliance_voucher_xml(
                move=self,
                company_name=company_name,
                voucher_type=voucher_type,
                persisted_view="Invoice Voucher View",
                voucher_action=voucher_action,
            )
        except ValueError as exc:
            err = str(exc)
            _logger.error(
                "[TallyGstSync] XML build error for %s: %s", self.name, err
            )
            self._write_gst_log(
                "failed",
                snapshot,
                "",
                "",
                "",
                False,
                False,
                err,
                url,
            )
            self.tally_gst_sync_status = "failed"
            return

        success, response_text, guid, error = tally_http.post_to_tally(xml_str, url)

        if (
            not success
            and voucher_action == "Create"
            and tally_http.voucher_import_retry_as_alter(response_text)
        ):
            try:
                xml_alter, flags, snapshot = xml_builder.build_gst_compliance_voucher_xml(
                    move=self,
                    company_name=company_name,
                    voucher_type=voucher_type,
                    persisted_view="Invoice Voucher View",
                    voucher_action="Alter",
                )
                success, response_text, guid, error = tally_http.post_to_tally(
                    xml_alter, url
                )
                if success:
                    xml_str = xml_alter
            except Exception:
                pass

        status = "success" if success else "failed"
        err_out = error or ""
        if inventory_note:
            err_out = f"{inventory_note}{err_out}"
        if not success:
            err_out = f"{err_out}\n\n{self._tally_request_diagnostics(xml_str)}"

        self._write_gst_log(
            status,
            snapshot,
            xml_str,
            response_text,
            guid,
            flags.get("einvoice"),
            flags.get("ewaybill"),
            err_out,
            url,
        )

        if success:
            self.write(
                {
                    "tally_gst_sync_status": "synced",
                    "tally_gst_last_sync": fields.Datetime.now(),
                }
            )
            if guid and guid.strip() and guid.strip() != vch_num:
                self.tally_guid = guid.strip()
            _logger.info(
                "[TallyGstSync] OK %s GST fields synced (IRN/EWB)",
                self.name,
            )
        else:
            self.write({"tally_gst_sync_status": "failed"})
            _logger.warning(
                "[TallyGstSync] FAILED %s: %s", self.name, error
            )

    def _write_gst_log(
        self,
        status,
        snapshot,
        request_xml,
        response_xml,
        guid,
        einvoice_sent,
        ewaybill_sent,
        error_message="",
        tally_server_url="",
    ):
        """Create a tally.gst.sync.log entry for this move."""
        snap = snapshot or {}
        self.env["tally.gst.sync.log"].sudo().create(
            {
                "move_id": self.id,
                "move_name": self.name,
                "status": status,
                "irn": snap.get("irn") or "",
                "irn_ack_no": snap.get("irn_ack_no") or "",
                "ewaybill_no": snap.get("ewaybill_no") or "",
                "ewaybill_date": snap.get("ewaybill_date") or "",
                "dispatch_from": snap.get("dispatch_from") or "",
                "ship_to": snap.get("ship_to") or "",
                "transporter_id": snap.get("transporter_id") or "",
                "transporter_name": snap.get("transporter_name") or "",
                "transport_mode": snap.get("transport_mode") or "",
                "vehicle_no": snap.get("vehicle_no") or "",
                "vehicle_type": snap.get("vehicle_type") or "",
                "transport_doc_no": snap.get("transport_doc_no") or "",
                "transport_doc_date": snap.get("transport_doc_date") or "",
                "distance": snap.get("distance") or "",
                "einvoice_sent": bool(einvoice_sent),
                "ewaybill_sent": bool(ewaybill_sent),
                "tally_guid": guid or "",
                "request_xml": request_xml,
                "response_xml": response_xml,
                "error_message": error_message,
                "tally_server_url": tally_server_url,
            }
        )

    # ------------------------------------------------------------------ #
    # Mapping helpers                                                      #
    # ------------------------------------------------------------------ #

    def _get_ledger_map_dict(self):
        """
        Load all tally.ledger.map records and return as a lookup dict.

        Returns:
            dict: {account_id.id: {'tally_ledger_name': str, 'is_party_account': bool}}
        """
        maps = self.env["tally.ledger.map"].sudo().search([("active", "=", True)])
        ledger_map = {}
        for m in maps:
            acc_type = m.account_id.account_type if m.account_id else ""
            is_party = m.is_party_account or acc_type in (
                "asset_receivable",
                "liability_payable",
            )
            default_group = "Sundry Debtors"
            if acc_type == "liability_payable":
                default_group = "Sundry Creditors"
            elif acc_type in ("income", "income_other"):
                default_group = "Sales Accounts"
            elif acc_type in ("expense", "expense_direct_cost"):
                default_group = "Purchase Accounts"
            ledger_map[m.account_id.id] = {
                "tally_ledger_name": m.tally_ledger_name,
                "tally_group": m.tally_group or default_group,
                "is_party_account": is_party,
            }
        # Provide a default for configured rounding accounts, but preserve any
        # explicit Ledger Mapping entered by the user.
        rounding_accounts = self.env["account.cash.rounding"].sudo().search([]).mapped(
            "profit_account_id"
        ) | self.env["account.cash.rounding"].sudo().search([]).mapped(
            "loss_account_id"
        )
        for account in rounding_accounts:
            ledger_map.setdefault(
                account.id,
                {
                    "tally_ledger_name": "Round Off",
                    "tally_group": "Indirect Expenses",
                    "is_party_account": False,
                },
            )
        return ledger_map

    def _get_voucher_type(self):
        """
        Look up the Tally voucher type for this move's move_type.

        Returns:
            tuple: (voucher_type_str, persisted_view_str)
        """
        if self.origin_payment_id:
            voucher_type = (
                "Receipt"
                if self.origin_payment_id.payment_type == "inbound"
                else "Payment"
            )
            return voucher_type, "Accounting Voucher View"

        vmap = (
            self.env["tally.voucher.map"]
            .sudo()
            .search([("move_type", "=", self.move_type)], limit=1)
        )
        if not vmap:
            # Sensible fallbacks (override per company in Tally Connector → Voucher Mapping)
            defaults = {
                "out_invoice": ("Sales", "Invoice Voucher View"),
                "in_invoice": ("Purchase", "Invoice Voucher View"),
                "out_refund": ("Credit Note", "Invoice Voucher View"),
                "in_refund": ("Debit Note", "Invoice Voucher View"),
                "out_receipt": ("Receipt", "Accounting Voucher View"),
                "in_receipt": ("Payment", "Accounting Voucher View"),
            }
            return defaults.get(self.move_type, ("Journal", "Accounting Voucher View"))
        return vmap.tally_voucher_type, (
            vmap.tally_persistedview or "Invoice Voucher View"
        )

    def _get_uom_map_dict(self):
        """
        Load tally.uom.map and return as {uom_id: symbol}.

        Returns:
            dict: {uom.uom record id: tally_symbol_str}
        """
        maps = self.env["tally.uom.map"].sudo().search([])
        return {m.uom_id.id: m.tally_symbol for m in maps}

    # ------------------------------------------------------------------ #
    # Pre-flight: master creation                                          #
    # ------------------------------------------------------------------ #

    def _ensure_partner_in_tally(self, url, company_name, ledger_map_dict):
        """
        Create the partner ledger in Tally if it doesn't appear in the ledger map
        as a matched party account. Refresh delivery-address children on the ledger.
        """
        if not self.partner_id:
            return
        ledger_partner = self.partner_id._tally_ledger_partner()
        if self.move_type in ('in_invoice', 'in_refund', 'in_receipt'):
            ledger_partner._sync_to_tally_ledger(force=True, move=self)
            return
        ship = self.partner_shipping_id
        if (
            ship
            and ship.id != self.partner_id.id
        ):
            # Ship-to ledger first (address master), then buyer with multi-address.
            ship._sync_to_tally_ledger(force=True, consignee_mode=True)
            ledger_partner._sync_to_tally_ledger(
                force=True,
                extra_address_partners=[ship],
            )
        else:
            ledger_partner._sync_to_tally_ledger(force=True)

    def _ensure_products_in_tally(self, url, company_name, uom_map_dict):
        """
        Create stock items in Tally for all products on the invoice lines.
        """
        for line in self.invoice_line_ids.filtered(
            lambda l: xml_builder._is_stock_invoice_line(l)
        ):
            line.product_id._sync_to_tally_item()

    # ------------------------------------------------------------------ #
    # Log writer                                                           #
    # ------------------------------------------------------------------ #

    def _tally_request_diagnostics(self, xml_str):
        """Short evidence block stored on failed sync logs (visible in Odoo UI)."""
        if not xml_str:
            return (
                "[Connector diagnostics]\n"
                "- Request XML is empty (unexpected).\n"
                "- Restart Odoo and upgrade module odoo_tally_connector."
            )
        has_sv = "SVFROMDATE" in xml_str and "SVTODATE" in xml_str
        _dates = re.findall(r"<DATE>([^<]*)</DATE>", xml_str)
        _vnums = re.findall(r"<VOUCHERNUMBER>([^<]*)</VOUCHERNUMBER>", xml_str)
        _remoteids = re.findall(r'<VOUCHER[^>]*\bREMOTEID="([^"]+)"', xml_str)
        _svf = re.findall(r"<SVFROMDATE>([^<]*)</SVFROMDATE>", xml_str)
        _svt = re.findall(r"<SVTODATE>([^<]*)</SVTODATE>", xml_str)
        _isinv = re.findall(r"<ISINVOICE>([^<]*)</ISINVOICE>", xml_str)
        _act_m = re.search(r'<VOUCHER[^>]*\bACTION="([^"]+)"', xml_str)
        _action_xml = _act_m.group(1) if _act_m else "(unknown)"
        _n_bill = xml_str.count("<BILLALLOCATIONS.LIST>")
        _n_guid = xml_str.count("<GUID>")
        _n_inv = xml_str.count("ALLINVENTORYENTRIES.LIST")
        _n_irn = xml_str.count("<IRN>")
        _n_ewb = xml_str.count("<EWAYBILLDETAILS.LIST>")
        _ledgers = re.findall(r"<LEDGERNAME>([^<]*)</LEDGERNAME>", xml_str)
        _vchtn = re.findall(r"<VOUCHERTYPENAME>([^<]*)</VOUCHERTYPENAME>", xml_str)
        _amt_vals = []
        for m in re.finditer(
            r"<ALLLEDGERENTRIES\.LIST>.*?<AMOUNT>([^<]*)</AMOUNT>",
            xml_str,
            flags=re.S,
        ):
            try:
                _amt_vals.append(float((m.group(1) or "0").strip().replace(",", "")))
            except ValueError:
                pass
        _amt_sum = sum(_amt_vals) if _amt_vals else None
        lines = [
            "[Connector diagnostics]",
            f"- Request length: {len(xml_str)} characters",
            f"- Contains SVFROMDATE and SVTODATE: {has_sv}",
            f"- SVFROMDATE value(s): {_svf[:2]!r} (expect YYYYMMDD per Tally variable spec)",
            f"- SVTODATE value(s): {_svt[:2]!r}",
            f"- First <DATE> value(s): {_dates[:3]!r}",
            f"- <VOUCHERNUMBER> value(s): {_vnums[:3]!r}",
            f"- VOUCHERNUMBER contains slash: {bool(_vnums and '/' in (_vnums[0] or ''))}",
            f"- REMOTEID attr value(s): {_remoteids[:3]!r}",
            f"- Voucher ACTION in XML: {_action_xml}",
            f"- ISINVOICE values: {_isinv[:3]!r}",
            f"- BILLALLOCATIONS.LIST blocks: {_n_bill} (only one New Ref per voucher number is valid in Tally)",
            f"- ALLINVENTORYENTRIES.LIST blocks: {_n_inv}",
            f"- <IRN> tags in request: {_n_irn}",
            f"- EWAYBILLDETAILS.LIST blocks: {_n_ewb}",
            f"- <GUID> tags in request: {_n_guid} (only real Tally GUIDs should be sent)",
            f"- <LEDGERNAME> values (order): {_ledgers!r}",
            f"- <VOUCHERTYPENAME>: {_vchtn[:1]!r}",
        ]
        if _amt_sum is not None:
            _inv_hint = (
                " With ALLINVENTORYENTRIES, income ledgers (e.g. Sales) must not also appear "
                "in ALLLEDGERENTRIES or Tally reports “Voucher totals do not match”. "
                "Expect only party + tax ledgers here."
                if _n_inv
                else " (expect 0.00; non-zero usually means the voucher will not post in Tally)"
            )
            lines.append(
                f"- Sum of <AMOUNT> inside ALLLEDGERENTRIES.LIST blocks: {_amt_sum:.2f}.{_inv_hint}"
            )
        if _n_bill > 1:
            lines.append(
                "- Bill-wise: more than one BILLALLOCATIONS block — if sync still fails, ensure "
                "only one Odoo account is marked “Is Party Account?” per document, or upgrade "
                "this module so only one party line gets New Ref."
            )
        lines.append(
            "- Tally checklist: each LEDGERNAME must exist in company books with exact spelling; "
            "VOUCHERTYPENAME must match a Tally voucher type (e.g. Sales)."
        )
        if _action_xml == "Alter" and _n_guid == 0:
            lines.append(
                "- Alter without a real <GUID> cannot be matched by Tally; use Create unless "
                "you first capture Tally's internal voucher GUID."
            )
        if not has_sv:
            lines.append(
                "- Interpretation: this Python process is almost certainly still loading an "
                "older odoo_tally_connector without period tags in the envelope. "
                "Fully stop all Odoo processes, start again, and use "
                "-u odoo_tally_connector once."
            )
        else:
            lines.append(
                "- Period tags are present in YYYYMMDD form; if Tally still says "
                "“Voucher date is missing”, check Tally (EDU allowed dates, closed period, "
                "Books Beginning, licensed company)."
            )
        if _dates:
            m8 = re.fullmatch(r"(\d{8})", (_dates[0] or "").strip())
            if m8:
                y = int(m8.group(1)[:4])
                mo = int(m8.group(1)[4:6])
                d = int(m8.group(1)[6:8])
                last = monthrange(y, mo)[1]
                if d not in (1, 2, last):
                    lines.append(
                        "- Date hint: this voucher date is not the 1st, 2nd, or last day of "
                        "its month. TallyPrime **EDU** often rejects other days and may still "
                        "report “Voucher date is missing”. Try 1 / 2 / last day, or a licensed company."
                    )
                y = int(m8.group(1)[:4])
                if y > date.today().year:
                    lines.append(
                        f"- Date warning: the year {y} is in the future. Check if Tally company "
                        "period (Alt+F2) is opened for the 2026-27 financial year."
                    )
        return "\n".join(lines)

    def _write_log(self, status, request_xml, response_xml, guid, error_message=""):
        """Create a tally.sync.log entry for this move."""
        ICP = self.env["ir.config_parameter"].sudo()
        url = ICP.get_param("tally_connector.server_url", "")
        self.env["tally.sync.log"].sudo().create(
            {
                "move_id": self.id,
                "move_name": self.name,
                "status": status,
                "tally_guid": guid or "",
                "request_xml": request_xml,
                "response_xml": response_xml,
                "error_message": error_message,
                "tally_server_url": url,
            }
        )
