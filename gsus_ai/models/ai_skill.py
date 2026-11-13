# -*- coding: utf-8 -*-
# Part of GSUS AI. See LICENSE file for full copyright and licensing details.

from odoo import models, fields, api


class GsusAiSkill(models.Model):
    _name = 'gsus.ai.skill'
    _description = 'GSUS AI Capability Skill'
    _order = 'sequence, name'

    name = fields.Char(string='Title', required=True)
    code = fields.Char(string='Code Identifier', required=True, index=True)
    sequence = fields.Integer(string='Sequence', default=10)
    color = fields.Integer(string='Color Index', default=0)
    description = fields.Text(string='Description', help='Documentation on what this skill enables the AI to do.')

    tool_ids = fields.Many2many(
        'gsus.ai.tool',
        'gsus_ai_skill_tool_rel',
        'skill_id',
        'tool_id',
        string='Included Tools',
        help='Tools grouped under this skill.',
    )

    agent_ids = fields.Many2many(
        'gsus.ai.agent',
        'gsus_ai_agent_skill_rel',
        'skill_id',
        'agent_id',
        string='Assigned Agents',
    )

    is_active = fields.Boolean(
        string='Active',
        default=True,
        help='Check or uncheck to enable or disable this skill across assigned agents.',
    )

    tool_count = fields.Integer(
        string='Tools Count',
        compute='_compute_tool_count',
        store=False,
    )

    _unique_code = models.Constraint(
        'UNIQUE (code)',
        'The skill code identifier must be unique!',
    )

    @api.depends('tool_ids')
    def _compute_tool_count(self):
        for record in self:
            record.tool_count = len(record.tool_ids)
