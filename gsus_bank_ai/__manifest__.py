# -*- coding: utf-8 -*-
{
    'name': 'GSUS Bank Statement AI',
    'version': '20.0.1.0.47',
    'category': 'Accounting/Banking',
    'summary': 'Automatic Bank Statement AI Processing, Creative OWL 3 Workbench, Auto-Reconciliation & 1-Click Push',
    'description': """
GSUS Bank Statement AI for Odoo 20
==================================
Transform bank statement processing with intelligent AI automation:
- Generic Multi-Bank PDF & Document Ingestion (Axis, SBI, HDFC, ICICI, etc.)
- Creative OWL 3 Interactive Staging Workbench with Dynamic Odometer Counters
- Kinetic 60/120 FPS Virtualized Table Scrolling & Sticky Glassmorphism Header
- AI Auto-Assign with Confidence Scores & Group Smart Resolution
- In-Workbench Natural Language Statement Chat Copilot
- Anomaly & Duplicate Detection Alerts
- Automatic Open Invoice & Bill Reconciliation (account.move)
- 1-Click Push to Odoo Bank Statements & Instant 1-Click Rollback / Revert
- Universal Database Execution Context (Zero Permission Blockers)

Developer: Vignesh M
Company: GSUS Softwares
Website: https://www.gsussoftwares.com/
    """,
    'author': 'GSUS Star Software Solution',
    'website': 'https://www.gsussoftwares.com/',
    'license': 'LGPL-3',
    'price': 0.0,
    'currency': 'EUR',
    'images': [
        'static/description/banner.gif',
        'static/description/banner.png',
        'static/description/bank_ai_demo.mp4',
        'static/description/icon.png',
        'static/description/screenshots/hero_workbench.png',
        'static/description/screenshots/dashboard_overview.png',
        'static/description/screenshots/advanced_vouchers.jpg',
    ],
    'depends': ['base', 'web', 'account', 'gsus_bank_ai_bridge'],
    'data': [
        'security/ir.access.csv',
        'report/statement_ai_report.xml',
        'wizard/bank_statement_upload_wizard_views.xml',
        'views/bank_statement_ai_views.xml',
        'views/bank_ai_rule_views.xml',
        'views/bank_ai_menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'gsus_bank_ai/static/src/scss/bank_workbench.scss',
            'gsus_bank_ai/static/src/components/bank_workbench/bank_workbench.js',
            'gsus_bank_ai/static/src/components/bank_workbench/bank_workbench.xml',
            'gsus_bank_ai/static/src/components/systray_ai_engine/systray_ai_engine.scss',
            'gsus_bank_ai/static/src/components/systray_ai_engine/systray_ai_engine.js',
            'gsus_bank_ai/static/src/components/systray_ai_engine/systray_ai_engine.xml',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
}
