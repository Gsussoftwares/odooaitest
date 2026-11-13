# -*- coding: utf-8 -*-
# Part of GSUS AI. See LICENSE file for full copyright and licensing details.

from odoo import models, fields, api


class GsusAiAgent(models.Model):
    _name = 'gsus.ai.agent'
    _description = 'GSUS AI Specialized Agent Persona'
    _order = 'sequence, name'

    name = fields.Char(string='Agent Name', required=True)
    code = fields.Char(string='Code Identifier', required=True)
    sequence = fields.Integer(string='Sequence', default=10)
    role_description = fields.Char(string='Tagline / Role', required=True)
    system_prompt = fields.Text(string='System Instructions', required=True)

    provider_id = fields.Many2one('gsus.ai.provider', string='Preferred Provider', ondelete='set null')
    model_override = fields.Char(string='Model Override', help='Optional specific model identifier')
    temperature = fields.Float(string='Temperature', default=0.7)

    skill_ids = fields.Many2many(
        'gsus.ai.skill',
        'gsus_ai_agent_skill_rel',
        'agent_id',
        'skill_id',
        string='Assigned Skills',
        help='High-level skills enabling groups of tools for this agent.',
    )

    tool_ids = fields.Many2many(
        'gsus.ai.tool',
        'gsus_ai_agent_tool_rel',
        'agent_id',
        'tool_id',
        string='Directly Assigned Tools',
        help='Specific tools directly authorized for this agent.',
    )

    def get_effective_tools(self):
        """Retrieve all active tools authorized for this agent from active skills and direct tools."""
        self.ensure_one()
        tools = self.env['gsus.ai.tool']
        for skill in self.skill_ids.filtered(lambda s: s.is_active):
            tools |= skill.tool_ids.filtered(lambda t: t.is_active and t.use_in_ai)
        tools |= self.tool_ids.filtered(lambda t: t.is_active and t.use_in_ai)
        return tools

    is_default = fields.Boolean(string='Default Agent for New Chats', default=False)
    is_active = fields.Boolean(string='Active', default=True)

    _unique_code = models.Constraint(
        'UNIQUE (code)',
        'The agent code must be unique!',
    )

    @api.model
    def get_default_agent(self):
        """Retrieve default agent or the first active agent."""
        agent = self.search([('is_default', '=', True), ('is_active', '=', True)], limit=1)
        if not agent:
            agent = self.search([('is_active', '=', True)], order='sequence, id', limit=1)
        return agent
