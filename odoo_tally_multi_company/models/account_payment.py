# -*- coding: utf-8 -*-
import logging
from odoo import _, api, Command, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AccountPayment(models.Model):
    _inherit = "account.payment"

    tally_company_id = fields.Many2one(
        "tally.company",
        string="Assigned Tally Company",
        compute="_compute_tally_company_id",
        store=True,
        readonly=False,
        index=True,
        tracking=True,
        help="Target Tally Prime company for this payment (derived from customer / vendor).",
    )
    tally_sync_status = fields.Selection(
        selection=[
            ("pending", "Pending"),
            ("synced", "Synced"),
            ("failed", "Failed"),
            ("skipped", "Skipped"),
        ],
        string="Tally Status",
        compute="_compute_tally_payment_status",
        readonly=True,
    )
    tally_guid = fields.Char(
        string="Tally GUID",
        compute="_compute_tally_payment_status",
        readonly=True,
    )
    tally_last_sync = fields.Datetime(
        string="Last Tally Sync",
        compute="_compute_tally_payment_status",
        readonly=True,
    )
    tally_sync_log_count = fields.Integer(
        string="Tally Logs Count",
        compute="_compute_tally_sync_log_count",
    )

    @api.depends("partner_id", "partner_id.tally_company_id", "partner_id.commercial_partner_id.tally_company_id")
    def _compute_tally_company_id(self):
        for payment in self:
            if payment.partner_id:
                payment.tally_company_id = payment.partner_id._get_effective_tally_company()
            else:
                payment.tally_company_id = False

    def _get_payment_move(self):
        """
        Robustly resolve or create the underlying posted account.move for this payment in Odoo 19.
        Guarantees that an account.move always exists for any payment type (standalone or invoice-linked).
        """
        self.ensure_one()
        if self.move_id:
            if self.move_id.state == "draft":
                self.move_id.action_post()
            return self.move_id

        # 1. Look via origin_payment_id backreference
        move = self.env["account.move"].sudo().search([("origin_payment_id", "=", self.id)], limit=1)
        if move:
            if move.state == "draft":
                move.action_post()
            self.sudo().write({"move_id": move.id})
            return move

        # 2. Look via payment number
        if self.name:
            move = self.env["account.move"].sudo().search([
                ("name", "=", self.name),
                ("company_id", "=", self.company_id.id),
            ], limit=1)
            if move:
                if move.state == "draft":
                    move.action_post()
                self.sudo().write({"move_id": move.id})
                return move

        # 3. Trigger native Odoo payment move generator if available
        if hasattr(self, "_generate_journal_entry"):
            try:
                self._generate_journal_entry()
                if self.move_id:
                    if self.move_id.state == "draft":
                        self.move_id.action_post()
                    return self.move_id
            except Exception as exc:
                _logger.warning("[TallyMultiCompany] Native _generate_journal_entry skipped: %s", exc)

        # 4. Direct Entry Generator: Create the balanced journal entry for Tally sync
        try:
            liquidity_account = (
                getattr(self, "outstanding_account_id", None)
                or self.journal_id.default_account_id
                or self.env["account.account"].with_company(self.company_id).search([
                    *self.env["account.account"]._check_company_domain(self.company_id),
                    ("account_type", "in", ("asset_cash", "asset_current")),
                ], limit=1)
            )
            destination_account = (
                getattr(self, "destination_account_id", None)
                or (
                    self.partner_id.with_company(self.company_id).property_account_receivable_id
                    if self.partner_type == "customer"
                    else self.partner_id.with_company(self.company_id).property_account_payable_id
                )
            )

            if not liquidity_account or not destination_account:
                _logger.error("[TallyMultiCompany] Cannot determine accounts for payment %s", self.name)
                return False

            amount = abs(self.amount)
            curr = self.currency_id or self.company_id.currency_id

            if self.payment_type == "inbound":  # Customer Receipt
                lines = [
                    Command.create({
                        "name": self.memo or self.name or _("Customer Payment"),
                        "account_id": liquidity_account.id,
                        "partner_id": self.partner_id.id,
                        "debit": amount,
                        "credit": 0.0,
                        "currency_id": curr.id,
                    }),
                    Command.create({
                        "name": self.memo or self.name or _("Customer Payment Counterpart"),
                        "account_id": destination_account.id,
                        "partner_id": self.partner_id.id,
                        "debit": 0.0,
                        "credit": amount,
                        "currency_id": curr.id,
                    }),
                ]
            else:  # Vendor Payment
                lines = [
                    Command.create({
                        "name": self.memo or self.name or _("Vendor Payment"),
                        "account_id": destination_account.id,
                        "partner_id": self.partner_id.id,
                        "debit": amount,
                        "credit": 0.0,
                        "currency_id": curr.id,
                    }),
                    Command.create({
                        "name": self.memo or self.name or _("Vendor Payment Counterpart"),
                        "account_id": liquidity_account.id,
                        "partner_id": self.partner_id.id,
                        "debit": 0.0,
                        "credit": amount,
                        "currency_id": curr.id,
                    }),
                ]

            move_vals = {
                "move_type": "entry",
                "name": self.name or "/",
                "ref": self.memo or self.name,
                "date": self.date or fields.Date.context_today(self),
                "journal_id": self.journal_id.id,
                "company_id": self.company_id.id,
                "partner_id": self.partner_id.id,
                "currency_id": curr.id,
                "origin_payment_id": self.id,
                "line_ids": lines,
            }

            move = self.env["account.move"].sudo().create(move_vals)
            move.action_post()
            self.sudo().write({"move_id": move.id})
            return move
        except Exception as exc:
            _logger.exception("[TallyMultiCompany] Error creating direct move for payment %s: %s", self.name, exc)

        return False

    def _compute_tally_payment_status(self):
        for payment in self:
            move = payment.move_id or self.env["account.move"].sudo().search([("origin_payment_id", "=", payment.id)], limit=1)
            if move:
                payment.tally_sync_status = move.tally_sync_status or "pending"
                payment.tally_guid = move.tally_guid or ""
                payment.tally_last_sync = move.tally_last_sync or False
            else:
                payment.tally_sync_status = "pending"
                payment.tally_guid = ""
                payment.tally_last_sync = False

    def _compute_tally_sync_log_count(self):
        Log = self.env["tally.sync.log"].sudo()
        for payment in self:
            move = payment.move_id or self.env["account.move"].sudo().search([("origin_payment_id", "=", payment.id)], limit=1)
            move_ids = [move.id] if move else []
            names = [payment.name]
            if move and move.name:
                names.append(move.name)

            payment.tally_sync_log_count = Log.search_count([
                "|",
                ("move_id", "in", move_ids),
                ("move_name", "in", names),
            ])

    def action_test_tally_connection(self):
        """Test live XML connection to the assigned Tally company."""
        self.ensure_one()
        tally_comp = self.tally_company_id or (self.partner_id and self.partner_id._get_effective_tally_company())
        if not tally_comp:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("No Tally Company Assigned"),
                    "message": _("Please select an Assigned Tally Company before testing connection."),
                    "type": "warning",
                    "sticky": True,
                },
            }
        return tally_comp.action_test_connection()

    def action_sync_to_tally(self):
        """Push payment / receipt to Tally Prime with full multi-company routing."""
        for payment in self:
            move = payment._get_payment_move()
            if not move:
                raise UserError(
                    _("Could not create or find the journal entry for payment %s. Please check bank/cash accounts.")
                    % payment.name
                )

            tally_comp = payment.tally_company_id or (payment.partner_id and payment.partner_id._get_effective_tally_company())
            if not tally_comp:
                return {
                    "type": "ir.actions.client",
                    "tag": "display_notification",
                    "params": {
                        "title": _("Cannot Sync Payment"),
                        "message": _(
                            "Partner '%s' has no assigned Tally Company. "
                            "Please assign a Tally Company in the Tally Integration tab before syncing."
                        )
                        % (payment.partner_id.display_name if payment.partner_id else payment.name),
                        "type": "warning",
                        "sticky": True,
                    },
                }

            # Ensure partner exists in target Tally company before sending payment
            ledger_map_dict = move._get_ledger_map_dict()
            url = (tally_comp.server_url or "").strip()
            company_name = tally_comp._get_target_tally_company_name()
            move._ensure_partner_in_tally(url, company_name, ledger_map_dict)

            # Route sync via underlying account.move
            move.with_context(
                tally_server_url=url,
                tally_company_name=company_name,
                tally_company_id=tally_comp.id,
            ).action_sync_to_tally()

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Tally Payment Sync"),
                "message": _("Sync completed for %s payment(s). Check Tally Logs for details.") % len(self),
                "type": "info",
                "sticky": False,
            },
        }

    def action_view_tally_logs(self):
        """Open Tally sync logs for this payment."""
        self.ensure_one()
        move = self.move_id or self.env["account.move"].sudo().search([("origin_payment_id", "=", self.id)], limit=1)
        move_ids = [move.id] if move else []
        names = [self.name]
        if move and move.name:
            names.append(move.name)

        domain = ["|", ("move_id", "in", move_ids), ("move_name", "in", names)]
        return {
            "name": _("Tally Logs — %s") % self.name,
            "type": "ir.actions.act_window",
            "res_model": "tally.sync.log",
            "view_mode": "list,form",
            "domain": domain,
            "context": {"default_move_name": self.name, "default_move_id": move.id if move else False},
        }
