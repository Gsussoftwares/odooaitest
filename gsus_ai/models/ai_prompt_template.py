# -*- coding: utf-8 -*-
# Part of GSUS AI. See LICENSE file for full copyright and licensing details.

from odoo import models, fields, api


class GsusAiPromptTemplate(models.Model):
    _name = 'gsus.ai.prompt.template'
    _description = 'GSUS AI Prompt Template Library'
    _order = 'sequence, name'

    name = fields.Char(string='Template Title', required=True)
    sequence = fields.Integer(string='Sequence', default=10)
    category = fields.Selection([
        ('sales', 'Sales & CRM'),
        ('finance', 'Accounting & Invoicing'),
        ('inventory', 'Inventory & Operations'),
        ('support', 'Customer Support'),
        ('developer', 'Technical & Code'),
        ('general', 'General'),
    ], string='Category', required=True, default='general')

    description = fields.Char(string='Description', help='Brief explanation of when to use this prompt')
    content = fields.Text(string='Prompt Instructions', required=True)
    is_active = fields.Boolean(string='Active', default=True)

    def render_prompt(self, context_vars: dict = None) -> str:
        """Replace {{variable}} placeholders with provided context values."""
        self.ensure_one()
        rendered = self.content
        context_vars = context_vars or {}
        context_vars.setdefault('user_name', self.env.user.name)
        context_vars.setdefault('company_name', self.env.company.name)
        for key, val in context_vars.items():
            rendered = rendered.replace(f"{{{{{key}}}}}", str(val))
        return rendered
