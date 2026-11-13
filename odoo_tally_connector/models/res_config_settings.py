from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    tally_server_url = fields.Char(
        string="Tally Server URL",
        config_parameter="tally_connector.server_url",
        help=(
            "URL of the Tally Prime XML HTTP Server. "
            "Default is http://localhost:9000 for a local Windows installation."
        ),
    )
    tally_company = fields.Char(
        string="Tally Company Name",
        config_parameter="tally_connector.company_name",
        help=(
            "The exact name of the company in Tally Prime (case-sensitive). "
            "This must match the company name shown in Tally exactly."
        ),
    )
    tally_stock_item_group = fields.Char(
        string="Tally Stock Group (for new items)",
        config_parameter="tally_connector.stock_item_group",
        help=(
            "Required for product sync: type the exact name of a Stock Group that already "
            "exists in Tally (Gateway of Tally → Inventory Info → Stock Groups), "
            "for example Finished Goods or Raw Materials. Leave empty only if you do not sync products."
        ),
    )
    tally_godown_name = fields.Char(
        string="Tally Godown Name",
        config_parameter="tally_connector.godown_name",
        default="Main Location",
        help=(
            "The exact name of the Godown in Tally Prime where inventory is booked. "
            "Standard Tally defaults are 'Main Location' or 'Primary'."
        ),
    )
    tally_batch_name = fields.Char(
        string="Tally Batch Name",
        config_parameter="tally_connector.batch_name",
        default="Primary Batch",
        help=(
            "The exact name of the Batch in Tally Prime. "
            "Standard Tally default is 'Primary Batch'."
        ),
    )
    tally_sync_active = fields.Boolean(
        string="Enable Automatic Tally Sync",
        config_parameter="tally_connector.sync_active",
        help=(
            "When enabled, invoices and bills are automatically synced to Tally "
            "when they are confirmed (posted). Payments are never auto-synced — "
            "use Sync to Tally on each payment manually."
        ),
    )
    tally_edu_snap_voucher_dates = fields.Boolean(
        string="Snap voucher dates for TallyPrime EDU",
        config_parameter="tally_connector.edu_snap_voucher_dates",
        help=(
            "TallyPrime EDU often rejects invoice days other than the 1st, 2nd and last day "
            "of the month (Tally may report “Voucher date is missing”). When enabled, dates "
            "sent in the Tally XML only are moved to the 1st of the same month when needed; "
            "Odoo invoice and accounting dates are not changed. Turn off for licensed Tally "
            "or when voucher dates in Tally must match Odoo exactly."
        ),
    )
    tally_include_inventory = fields.Boolean(
        string="Include Stock Item Entries",
        config_parameter="tally_connector.include_inventory",
        help=(
            "When enabled, invoice lines with products are sent as ALLINVENTORYENTRIES "
            "in Tally (full inventory tracking). When disabled, only ledger entries "
            "are sent (accounting-only mode, simpler)."
        ),
    )
    tally_auto_create_masters = fields.Boolean(
        string="Auto-Create Tally Masters",
        config_parameter="tally_connector.auto_create_masters",
        default=True,
        help=(
            "When enabled, missing Party Ledgers and Stock Items will be "
            "automatically created in Tally before the voucher is posted."
        ),
    )
    tally_auto_sync_partner = fields.Boolean(
        string="Auto-Sync Customers/Vendors to Tally",
        config_parameter="tally_connector.auto_sync_partner",
        help=(
            "When enabled, saving a customer or vendor (with customer/supplier activity) "
            "pushes or updates their party ledger in Tally (Create on first save, Alter when already synced)."
        ),
    )
    tally_auto_sync_product = fields.Boolean(
        string="Auto-Sync Goods to Tally",
        config_parameter="tally_connector.auto_sync_product",
        help=(
            "When enabled, saving a storable product (Goods) updates the stock item in Tally "
            "if the connector is configured (stock group, units, etc.)."
        ),
    )
    tally_master_push_gst = fields.Boolean(
        string="Include GST / Tax IDs in Tally Masters",
        config_parameter="tally_connector.master_push_gst",
        default=True,
        help=(
            "Partners: Tax ID / GSTIN on ledgers. Products: HSN when set (l10n_in) and "
            "combined Sales Tax %% from Odoo default taxes (taxes_id) as item GSTRATE/IGSTRATE in Tally. "
            "Turn off if your Tally build rejects these XML tags."
        ),
    )
    tally_include_gst_compliance = fields.Boolean(
        string="Include E-Invoice / E-Way Bill in Tally XML",
        config_parameter="tally_connector.include_gst_compliance",
        default=True,
        help=(
            "When enabled, IRN / acknowledgement and e-Way Bill number (plus transport "
            "details when available) are sent on sales vouchers. Data is read from Odoo "
            "e-Invoice and e-Way Bill records; optional JSON export folder is used as fallback."
        ),
    )
    tally_gst_json_export_path = fields.Char(
        string="GST JSON Export Folder (optional)",
        config_parameter="tally_connector.gst_json_export_path",
        help=(
            "Optional folder where e-Invoice response JSON files are saved "
            "(e.g. C:\\odoo_enterprice\\server\\eway). Files must be named like "
            "DBPL_26-27_00127_einvoice.json (invoice number with slashes replaced by _)."
        ),
    )

    def action_tally_test_connection(self):
        """
        Test the HTTP connection to the Tally Prime XML server.
        Shows a user-friendly notification with the result.
        """
        from odoo.addons.odoo_tally_connector.utils import tally_http

        # Save current form values first so the URL is up-to-date
        self.execute()

        ICP = self.env["ir.config_parameter"].sudo()
        url = ICP.get_param("tally_connector.server_url", "http://localhost:9000")

        success, message = tally_http.test_connection(url)

        if success:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": "Tally connection successful",
                    "message": message,
                    "type": "success",
                    "sticky": False,
                },
            }
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Tally connection failed",
                "message": message,
                "type": "danger",
                "sticky": True,
            },
        }
