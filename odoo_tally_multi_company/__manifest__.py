# -*- coding: utf-8 -*-
{
    "name": "Tally Multi-Company Connector",
    "version": "19.0.1.0.0",
    "category": "Accounting/Accounting",
    "summary": "Connect multiple Tally Prime companies simultaneously and route sync based on partner assignment",
    "description": """
        Odoo Tally Multi-Company Integration
        ====================================
        Extends the Tally Prime Connector to allow connecting multiple Tally companies simultaneously:
        - Manage multiple Tally endpoints (different ports, same machine, or different servers/IPs).
        - Direct XML live connection testing per Tally company.
        - Assign Customers/Vendors to specific Tally companies.
        - Automatic routing of Invoices, Bills, Receipts, and Payments to the assigned Tally company.
        - Warning and sync prevention for transactions with unassigned partners.
        - Comprehensive multi-company audit logging.
    """,
    "author": "GSUS",
    "company": "GSUS",
    "maintainer": "GSUS",
    "website": "",
    "depends": [
        "account",
        "odoo_tally_connector",
    ],
    "data": [
        "security/ir.model.access.csv",
        "views/tally_company_views.xml",
        "views/res_partner_views.xml",
        "views/account_move_views.xml",
        "views/account_payment_views.xml",
        "views/tally_sync_log_views.xml",
        "views/tally_master_sync_views.xml",
        "views/res_config_settings_views.xml",
        "views/menus.xml",
    ],
    "images": ["static/description/banner.png"],
    "installable": True,
    "application": False,
    "auto_install": False,
    "license": "LGPL-3",
}
