# -*- coding: utf-8 -*-
# Part of GSUS AI. See LICENSE file for full copyright and licensing details.

from odoo import models, fields


class GsusAiAuditLog(models.Model):
    _name = 'gsus.ai.audit.log'
    _description = 'GSUS AI Tool Execution Audit Trail'
    _order = 'create_date desc'

    tool_id = fields.Many2one('gsus.ai.tool', string='Tool Executed', ondelete='set null')
    tool_code = fields.Char(string='Tool Code', required=True)
    user_id = fields.Many2one('res.users', string='Executing User', default=lambda self: self.env.user, required=True, index=True)
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company, required=True)
    conversation_id = fields.Many2one('gsus.ai.conversation', string='Conversation', ondelete='set null')

    arguments_json = fields.Text(string='Arguments Provided')
    result_status = fields.Selection([
        ('success', 'Success'),
        ('error', 'Execution Error'),
    ], string='Status', required=True, default='success', index=True)

    result_summary = fields.Text(string='Result / Output')
    duration_ms = fields.Float(string='Duration (ms)')
