# -*- coding: utf-8 -*-
# Part of GSUS AI. See LICENSE file for full copyright and licensing details.

from odoo import models, fields, api


class GsusAiDefaultPrompt(models.Model):
    _name = 'gsus.ai.default.prompt'
    _description = 'GSUS AI Contextual Default Prompt'
    _order = 'sequence, name'

    name = fields.Char(string='Name', required=True)
    action = fields.Char(string='Action', required=True, help='Action description or trigger intent')
    agent_id = fields.Many2one('gsus.ai.agent', string='Agent', ondelete='set null')
    sequence = fields.Integer(string='Sequence', default=10)

    target_component = fields.Selection([
        ('composer', 'Mail/Note Composer'),
        ('html', 'Record HTML Fields'),
        ('text', 'Text Selector'),
        ('chatter', 'Chatter Helper'),
        ('file_viewer', 'File Viewer Helper'),
        ('voice', 'Voice Transcription'),
        ('media', 'Media Manager'),
        ('general', 'General / Ask AI'),
    ], string='Target Component', default='general', required=True)

    description = fields.Text(string='Prompt Instructions / Prompt Content')
    is_active = fields.Boolean(string='Active', default=True, help='Check or uncheck to enable/disable this prompt.')
