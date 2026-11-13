{
    "name": "Tally Prime Connector",
    "version": "19.0.1.0.15",
    "category": "Accounting/Accounting",
    "summary": "Sync Invoices, Bills & Payments to Tally Prime via Direct XML (Port 9000)",
    "description": """
        Odoo Tally Prime Direct XML Connector
        ==========================================
        Synchronizes posted Customer Invoices, Vendor Bills, and Credit Notes
        to Tally Prime via its built-in HTTP XML interface on Port 9000.

        Features:
        - Configurable Tally server URL, company name, and active toggle
        - Ledger, Voucher Type, and UoM mapping tables
        - Automatic sync on invoice confirmation (action_post)
        - Manual "Sync to Tally" retry button on invoice/bill forms
        - Duplicate prevention via Tally GUID tracking
        - Detailed sync log with full Request/Response XML
        - Master data pre-flight: auto-creates Party & Stock Item in Tally if missing
        - Correct Tally Debit/Credit sign management (Debit=negative, Credit=positive)
    """,
    "author": "GSUS",
    "company": "GSUS",
    "maintainer": "GSUS",
    "website": "",
    "depends": [
        "account",
        "base_setup",
        "uom",
    ],
    "data": [
        # 1. Security must load first
        "security/ir.model.access.csv",
        # 2. Default seed data
        "data/default_voucher_map.xml",
        "data/default_uom_map.xml",
        "data/remove_order_voucher_maps.xml",
        # 3. Views & Menus
        "views/res_config_settings_views.xml",
        "views/tally_ledger_map_views.xml",
        "views/tally_voucher_map_views.xml",
        "views/tally_uom_map_views.xml",
        "views/tally_product_category_map_views.xml",
        "views/tally_hsn_description_map_views.xml",
        "views/tally_sync_log_views.xml",
        "views/tally_gst_sync_log_views.xml",
        "views/account_move_views.xml",
        "views/account_payment_views.xml",
        "views/res_partner_views.xml",
        "views/product_product_views.xml",
        # 4. Wizard (Actions must be defined before menus)
        "wizard/tally_test_connection_views.xml",
        "wizard/tally_master_sync_views.xml",
        "views/menus.xml",
    ],
    "external_dependencies": {
        "python": ["requests"],
    },
    "images": ["static/description/banner.png"],
    "installable": True,
    "application": False,
    "auto_install": False,
    "license": "LGPL-3",
}
