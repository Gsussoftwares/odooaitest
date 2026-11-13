# -*- coding: utf-8 -*-
import html
import logging
from odoo import _, api, fields, models
from odoo.exceptions import UserError
# pyrefly: ignore [missing-import]
from odoo.addons.odoo_tally_connector.utils import tally_http

_logger = logging.getLogger(__name__)


class TallyCompany(models.Model):
    _name = "tally.company"
    _description = "Tally Prime Company Connection"
    _order = "name asc"

    name = fields.Char(
        string="Configuration Name",
        required=True,
        help="A friendly identifier for this Tally connection in Odoo (e.g. Main Branch, Warehouse, Company A).",
    )
    tally_company_name = fields.Char(
        string="Tally Company Name",
        required=True,
        help="Exact case-sensitive name of the company open in Tally Prime.",
    )
    server_url = fields.Char(
        string="Tally Server URL",
        required=True,
        default="http://localhost:9000",
        help="URL of the Tally Prime XML Server (e.g. http://localhost:9000 or http://192.168.1.50:9000).",
    )
    active = fields.Boolean(
        string="Active",
        default=True,
        help="Set to inactive to disable syncing to this Tally company.",
    )
    connection_status = fields.Selection(
        [
            ("untested", "Not Tested"),
            ("connected", "Connected"),
            ("failed", "Connection Failed"),
        ],
        string="Connection Status",
        default="untested",
        readonly=True,
        copy=False,
    )
    last_connection_test = fields.Datetime(
        string="Last Tested On",
        readonly=True,
        copy=False,
    )
    last_connection_message = fields.Text(
        string="Connection Details",
        readonly=True,
        copy=False,
    )
    partner_ids = fields.One2many(
        "res.partner",
        "tally_company_id",
        string="Assigned Partners",
    )
    partner_count = fields.Integer(
        string="Partners Count",
        compute="_compute_partner_count",
    )
    sync_log_ids = fields.One2many(
        "tally.sync.log",
        "tally_company_id",
        string="Sync Logs",
    )
    sync_log_count = fields.Integer(
        string="Logs Count",
        compute="_compute_sync_log_count",
    )

    _sql_constraints = [
        (
            "unique_company_url",
            "unique(tally_company_name, server_url)",
            "A Tally Company connection with this exact Tally Company Name and Server URL already exists!",
        )
    ]

    @api.depends("partner_ids")
    def _compute_partner_count(self):
        for record in self:
            record.partner_count = len(record.partner_ids)

    @api.depends("sync_log_ids")
    def _compute_sync_log_count(self):
        for record in self:
            record.sync_log_count = len(record.sync_log_ids)

    def _get_target_tally_company_name(self):
        """Return the exact name to pass to Tally in XML envelopes."""
        self.ensure_one()
        return (self.tally_company_name or self.name or "").strip()

    def action_test_connection(self):
        """Test live XML connectivity to this specific Tally company and record full logs."""
        self.ensure_one()
        url = (self.server_url or "").strip()
        tally_company = self._get_target_tally_company_name()
        now = fields.Datetime.now()
        action_name = _("Test Connection - %s") % (self.name or tally_company)

        _logger.info("[TallyMultiCompany] Testing connection for '%s' at '%s'", tally_company, url)

        if not url:
            raise UserError(_("Please specify a Tally Server URL."))
        if not tally_company:
            raise UserError(_("Please specify a Tally Company Name."))

        # 1. Check basic TCP/HTTP reachability
        reachable, ping_msg = tally_http.test_connection(url)
        if not reachable:
            fail_msg = _("Server unreachable at %s:\n%s") % (url, ping_msg)
            self.write({
                "connection_status": "failed",
                "last_connection_test": now,
                "last_connection_message": fail_msg,
            })
            self.env["tally.sync.log"].sudo().create({
                "tally_company_id": self.id,
                "move_name": action_name,
                "tally_server_url": url,
                "request_xml": _("Ping HTTP GET / POST to %s") % url,
                "response_xml": ping_msg or "",
                "status": "failed",
                "error_message": fail_msg,
            })
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Connection Failed"),
                    "message": _("Could not reach Tally server at %s. Ensure Tally Prime XML server is enabled.") % url,
                    "type": "danger",
                    "sticky": True,
                },
            }

        # 2. Build Tally Prime Company-targeted query XML
        escaped_comp = html.escape(tally_company)
        xml_req = (
            '<?xml version="1.0" encoding="utf-8"?>\n'
            "<ENVELOPE>\n"
            "  <HEADER>\n"
            "    <VERSION>1</VERSION>\n"
            "    <TALLYREQUEST>Export</TALLYREQUEST>\n"
            "    <TYPE>Data</TYPE>\n"
            "    <ID>Ledger</ID>\n"
            "  </HEADER>\n"
            "  <BODY>\n"
            "    <DESC>\n"
            "      <STATICVARIABLES>\n"
            "        <SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>\n"
            f"        <SVCURRENTCOMPANY>{escaped_comp}</SVCURRENTCOMPANY>\n"
            "      </STATICVARIABLES>\n"
            "    </DESC>\n"
            "  </BODY>\n"
            "</ENVELOPE>"
        )

        success, response_xml, _guid, error = tally_http.post_to_tally(xml_req, url)

        # 3. Process Tally response
        if success or ("<ENVELOPE>" in (response_xml or "") and "<LINEERROR>" not in (response_xml or "")):
            success_msg = _(
                "Successfully connected to Tally server at %s.\nCompany '%s' is open and active in Tally Prime."
            ) % (url, tally_company)
            self.write({
                "connection_status": "connected",
                "last_connection_test": now,
                "last_connection_message": success_msg,
            })
            self.env["tally.sync.log"].sudo().create({
                "tally_company_id": self.id,
                "move_name": action_name,
                "tally_server_url": url,
                "request_xml": xml_req,
                "response_xml": response_xml or "",
                "status": "success",
                "error_message": success_msg,
            })
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Connection Successful"),
                    "message": _("Connected to Tally Prime (%s) — Company '%s' verified!") % (url, tally_company),
                    "type": "success",
                    "sticky": False,
                },
            }
        else:
            fail_msg = _(
                "Connected to Tally server at %s, but company '%s' is not loaded or responded with error:\n%s"
            ) % (url, tally_company, error or _("Company is not open in Tally Prime."))
            self.write({
                "connection_status": "failed",
                "last_connection_test": now,
                "last_connection_message": fail_msg,
            })
            self.env["tally.sync.log"].sudo().create({
                "tally_company_id": self.id,
                "move_name": action_name,
                "tally_server_url": url,
                "request_xml": xml_req,
                "response_xml": response_xml or "",
                "status": "failed",
                "error_message": fail_msg,
            })
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Company Not Open in Tally"),
                    "message": fail_msg,
                    "type": "warning",
                    "sticky": True,
                },
            }

    def action_view_partners(self):
        self.ensure_one()
        return {
            "name": _("Assigned Partners - %s") % self.name,
            "type": "ir.actions.act_window",
            "res_model": "res.partner",
            "view_mode": "list,form",
            "domain": [("tally_company_id", "=", self.id)],
            "context": {"default_tally_company_id": self.id},
        }

    def action_view_sync_logs(self):
        self.ensure_one()
        return {
            "name": _("Sync Logs - %s") % (self.tally_company_name or self.name),
            "type": "ir.actions.act_window",
            "res_model": "tally.sync.log",
            "view_mode": "list,form",
            "domain": [("tally_company_id", "=", self.id)],
            "context": {"default_tally_company_id": self.id},
        }
