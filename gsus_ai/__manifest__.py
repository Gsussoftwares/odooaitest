# -*- coding: utf-8 -*-
{
    'name': 'GSUS AI',
    'version': '20.0.1.0.0',
    'category': 'Productivity/Artificial Intelligence',
    'summary': 'Unified Enterprise AI Platform for Odoo 20 (Groq, Gemini, Claude)',
    'description': """
GSUS AI — Complete Enterprise AI Platform for Odoo 20
=====================================================
Consolidates 50+ business AI functions across Sales, CRM, Finance, Purchase,
Inventory, Projects, Helpdesk, and Documents into a unified conversational
agent platform.

Powered directly by:
- Groq (Ultra-Fast Free AI - Qwen 3.8 27B, GPT-OSS)
- Google Gemini (Gemini 3.5 Flash-Lite, Gemini 2.5 Flash)
- Anthropic Claude (Claude 3.7 Sonnet, Claude 3.5 Haiku)

Features:
- OWL 3 responsive conversational interface
- Multi-session chat history and conversation drawer
- Whitelisted ORM tool registry with 100% server-side security
- Interactive action proposal confirmation for mutating changes
- Context-aware Odoo business records builder
- Zero-cost architecture without mandatory Odoo IAP credits

Developer: Vignesh M
Company: GSUS Softwares
Website: https://www.gsussoftwares.com/
    """,
    'author': 'Vignesh M (GSUS Softwares)',
    'website': 'https://www.gsussoftwares.com/',
    'license': 'LGPL-3',
    'depends': ['base', 'web', 'mail', 'gsus_ai_bridge'],
    'icon': '/gsus_ai/static/description/icon_3d.png',
    'data': [
        'security/gsus_ai_security.xml',
        'security/ir.access.csv',
        'data/ai_tool_data.xml',
        'data/ai_skills_data.xml',
        'data/ai_default_prompts_data.xml',
        'data/ai_agent_data.xml',
        'views/ai_skill_views.xml',
        'views/ai_default_prompt_views.xml',
        'views/ai_conversation_views.xml',
        'views/ai_agent_views.xml',
        'views/ai_tool_views.xml',
        'views/ai_action_proposal_views.xml',
        'views/ai_audit_log_views.xml',
        'views/gsus_ai_menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'gsus_ai/static/src/scss/gsus_ai.scss',
            'gsus_ai/static/src/utils/markdown.js',
            'gsus_ai/static/src/services/gsus_ai_service.js',
            'gsus_ai/static/src/components/chat_panel/chat_panel.js',
            'gsus_ai/static/src/components/chat_panel/chat_panel.xml',
            'gsus_ai/static/src/components/floating_panel/gsus_ai_floating_panel.js',
            'gsus_ai/static/src/components/floating_panel/gsus_ai_floating_panel.xml',
            'gsus_ai/static/src/components/systray/systray_item.js',
            'gsus_ai/static/src/components/systray/systray_item.xml',
        ],
        'web.assets_web_dark': [
            'gsus_ai/static/src/scss/gsus_ai.dark.scss',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
}
