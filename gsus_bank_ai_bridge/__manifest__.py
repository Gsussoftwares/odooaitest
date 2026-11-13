# -*- coding: utf-8 -*-
{
    'name': 'GSUS Bank AI Bridge',
    'version': '20.0.1.0.4',
    'category': 'Accounting/Artificial Intelligence',
    'summary': 'High-Speed Multimodal Document Parsing & LLM Bridge for Bank Statements (Groq, Gemini, Claude)',
    'description': """
GSUS Bank AI Bridge
===================
Dedicated, high-performance integration and multimodal document vision engine for Bank Statement AI:
- Ultra-Fast Google Gemini 3.5 Flash-Lite & Gemini 2.5 Flash Multimodal Vision
- Ultra-Fast Groq API Engine (Qwen 3.8 27B / LLaMA)
- Anthropic Claude 3.5 Sonnet & Haiku Integration
- Parallel Multi-Page PDF Chunking & Structured Table JSON Extraction
- AES-256 Symmetric API Key Secret Vault
- In-Memory Semantic Partner & Chart of Accounts Fuzzy Matcher
- Universal Database Execution Context (Superuser Access)

Developer: Vignesh M
Company: GSUS Softwares
Website: https://www.gsussoftwares.com/
    """,
    'author': 'Vignesh M (GSUS Softwares)',
    'website': 'https://www.gsussoftwares.com/',
    'license': 'LGPL-3',
    'depends': ['base', 'account'],
    'data': [
        'security/ir.access.csv',
        'views/bank_ai_provider_views.xml',
        'views/bank_bridge_menus.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
