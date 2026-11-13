# -*- coding: utf-8 -*-
# Part of GSUS Bank AI. See LICENSE file for full copyright and licensing details.

from odoo import models, fields, api


class GsusBankAiJob(models.Model):
    _name = 'gsus.bank.ai.job'
    _description = 'Bank Statement AI Background Processing Job'
    _order = 'create_date desc, id desc'

    name = fields.Char(string='Job Reference', default=lambda self: f"JOB-{fields.Datetime.now().strftime('%Y%m%d%H%M%S')}")
    statement_id = fields.Many2one('gsus.bank.statement.ai', string='Statement Session', ondelete='cascade', index=True)
    company_id = fields.Many2one('res.company', string='Company', required=True, default=lambda self: self.env.company)

    state = fields.Selection([
        ('queued', 'Queued in Engine'),
        ('reading', 'Reading & Decrypting Document'),
        ('extracting', 'AI Multimodal Vision Extraction'),
        ('verifying', 'Arithmetic Cross-Checking'),
        ('matching', 'Semantic Ledger & Partner Mapping'),
        ('done', 'Extraction Complete'),
        ('failed', 'Processing Failed')
    ], string='Job Stage', default='queued', tracking=True)

    provider_name = fields.Char(string='Provider Engine', default='Google Gemini Flash')
    total_pages = fields.Integer(string='Total Pages', default=0)
    chunks_total = fields.Integer(string='Total Chunks', default=0)
    chunks_completed = fields.Integer(string='Completed Chunks', default=0)
    progress_percent = fields.Integer(string='Progress %', default=0)

    extracted_lines_count = fields.Integer(string='Extracted Lines Count', default=0)
    error_message = fields.Text(string='Failure Reason')
    encrypted_temp_password = fields.Char(string='Encrypted Temp Password')
    execution_time_seconds = fields.Float(string='Duration (s)', default=0.0)

    def set_stage(self, stage, progress=None, chunks_done=None, error=None):
        vals = {'state': stage}
        if progress is not None:
            vals['progress_percent'] = progress
        if chunks_done is not None:
            vals['chunks_completed'] = chunks_done
        if error:
            vals['error_message'] = error
        self.write(vals)

