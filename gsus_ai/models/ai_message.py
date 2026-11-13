# -*- coding: utf-8 -*-
# Part of GSUS AI. See LICENSE file for full copyright and licensing details.

from odoo import models, fields


class GsusAiMessage(models.Model):
    _name = 'gsus.ai.message'
    _description = 'GSUS AI Message'
    _order = 'id asc'

    conversation_id = fields.Many2one('gsus.ai.conversation', string='Conversation', required=True, ondelete='cascade', index=True)
    role = fields.Selection([
        ('system', 'System Instructions'),
        ('user', 'User Query'),
        ('assistant', 'Assistant Response'),
        ('tool', 'Tool Result'),
    ], string='Role', required=True, default='user')

    content = fields.Text(string='Content')
    tool_call_id = fields.Char(string='Tool Call ID')
    tool_calls_json = fields.Text(string='Tool Calls Data')

    token_count = fields.Integer(string='Tokens', default=0)
    duration_seconds = fields.Float(string='Duration (s)', default=0.0)

    is_error = fields.Boolean(string='Is Error', default=False)
    error_text = fields.Text(string='Error Details')
