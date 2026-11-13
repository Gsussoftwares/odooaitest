# -*- coding: utf-8 -*-
# Part of GSUS AI. See LICENSE file for full copyright and licensing details.

import json
import logging
from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class GsusAiTool(models.Model):
    _name = 'gsus.ai.tool'
    _description = 'GSUS AI Business Tool Registry'
    _order = 'sequence, name'

    name = fields.Char(string='Tool Name', required=True)
    code = fields.Char(string='Tool Identifier', required=True, index=True)
    sequence = fields.Integer(string='Sequence', default=10)
    domain_category = fields.Selection([
        ('sales', 'Sales & CRM'),
        ('finance', 'Accounting & Invoicing'),
        ('inventory', 'Inventory & Products'),
        ('purchase', 'Purchase & Vendors'),
        ('project', 'Projects & Tasks'),
        ('support', 'Helpdesk & Support'),
        ('marketing', 'Marketing & Livechat'),
        ('general', 'General Odoo Tools'),
    ], string='Domain Category', required=True, default='general')

    description = fields.Text(string='Tool Description', required=True, help='Prompt instructions given to AI about what this tool does')
    operation_type = fields.Selection([
        ('read', 'Read-Only (Automatic Execution)'),
        ('mutate', 'Mutating Operation (Requires Approval)'),
    ], string='Operation Type', required=True, default='read')

    requires_confirmation = fields.Boolean(
        string='Require User Confirmation',
        default=False,
        help='If checked, the AI proposal must be confirmed by the user before changing database state.',
    )

    json_schema_text = fields.Text(
        string='JSON Schema (Parameters)',
        default='{\n  "type": "object",\n  "properties": {},\n  "required": []\n}',
        help='JSON schema defining input parameters accepted by this tool.',
    )

    json_schema = fields.Json(
        string='Computed JSON Schema',
        compute='_compute_json_schema',
        store=False,
    )

    is_active = fields.Boolean(string='Active', default=True)
    use_in_ai = fields.Boolean(
        string='Use in AI',
        default=True,
        help='Check or uncheck to enable or disable this tool in AI function calling.',
    )
    is_readonly = fields.Boolean(
        string='Readonly tool',
        compute='_compute_is_readonly',
        store=True,
        help='Indicates whether this tool is read-only (discovery) vs state-mutating.',
    )
    skill_ids = fields.Many2many(
        'gsus.ai.skill',
        'gsus_ai_skill_tool_rel',
        'tool_id',
        'skill_id',
        string='Skills',
    )
    execution_count = fields.Integer(string='Times Executed', default=0, readonly=True)

    _unique_code = models.Constraint(
        'UNIQUE (code)',
        'The tool identifier code must be unique!',
    )

    @api.depends('operation_type')
    def _compute_is_readonly(self):
        for record in self:
            record.is_readonly = (record.operation_type == 'read')

    @api.depends('json_schema_text')
    def _compute_json_schema(self):
        for record in self:
            try:
                record.json_schema = json.loads(record.json_schema_text) if record.json_schema_text else {}
            except Exception:
                record.json_schema = {'type': 'object', 'properties': {}}

    def execute_tool(self, arguments: dict, conversation_id: int = None) -> dict:
        """Execute the tool safely through the ToolExecutor service."""
        self.ensure_one()
        executor = self.env['gsus.ai.tool.executor']
        self.sudo().execution_count += 1
        return executor.execute(self, arguments, conversation_id=conversation_id)
