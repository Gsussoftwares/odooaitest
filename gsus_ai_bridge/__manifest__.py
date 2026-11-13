# -*- coding: utf-8 -*-
{
    'name': 'GSUS AI Bridge',
    'version': '20.0.1.0.0',
    'category': 'Productivity/Artificial Intelligence',
    'summary': 'Integration Engine & API Protocol Bridge for Groq, Claude, and Gemini',
    'description': """
GSUS AI Bridge
==============
The core AI integration and interoperability platform for Odoo 20:
- Native Groq Ultra-Fast API Provider Adapter (/openai/v1)
- Native Google Gemini API Provider Adapter (v1beta)
- Native Anthropic Claude API Provider Adapter (/v1/messages)
- AES-256 Symmetric Secret Vault & Key Masking
- Rate-limiting, retry policy, and usage telemetry
- Zero paid subscription requirement for base installation

Developer: Vignesh M
Company: GSUS Softwares
Website: https://www.gsussoftwares.com/
    """,
    'author': 'Vignesh M (GSUS Softwares)',
    'website': 'https://www.gsussoftwares.com/',
    'license': 'LGPL-3',
    'depends': ['base', 'web'],
    'icon': '/gsus_ai_bridge/static/description/icon_3d.png',
    'data': [
        'security/ir.access.csv',
        'views/ai_provider_views.xml',
        'views/bridge_menus.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
