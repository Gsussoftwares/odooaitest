# -*- coding: utf-8 -*-
# Part of GSUS Bank AI. See LICENSE file for full copyright and licensing details.

import json
import logging
from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class GsusBankAiProvider(models.Model):
    _name = 'gsus.bank.ai.provider'
    _description = 'AI Parsing Engine Configuration'
    _order = 'is_active desc, sequence, id'

    name = fields.Char(string='Engine Name', required=True, default='Google Gemini Multimodal')
    sequence = fields.Integer(string='Sequence', default=10)
    is_active = fields.Boolean(string='Active for Bank Parsing', default=True)

    provider_type = fields.Selection([
        ('native', 'Native Python Engine (Zero Download · 100% Offline · Instant)'),
        ('gemini', 'Google Gemini (Multimodal Vision Recommended)'),
        ('openai', 'OpenAI (GPT-4o & GPT-4o-mini Vision)'),
    ], string='Engine Provider', required=True, default='native')

    base_url = fields.Char(string='Custom Base URL', help='Leave blank to use official API endpoints')
    api_key_encrypted = fields.Char(string='Encrypted API Key', readonly=True)
    api_key = fields.Char(
        string='API Secret Key',
        compute='_compute_api_key',
        inverse='_inverse_api_key',
        help='Your Gemini or OpenAI API Key. Stored securely with AES-256 encryption. (Not required for Native Python Engine)',
    )

    NATIVE_MODELS = [
        ('native-adaptive-v1', 'Native Adaptive Parser v1.0 (Embedded)'),
        ('native-fast-table', 'Native Fast Tabular OCR (Offline)'),
        ('custom', 'Custom Format Parser...'),
    ]

    GEMINI_MODELS = [
        ('gemini-3.8-flash', 'Gemini 3.8 Flash (Latest & Ultra-Fast)'),
        ('gemini-3.5-flash', 'Gemini 3.5 Flash (Recommended)'),
        ('gemini-3.5-flash-lite', 'Gemini 3.5 Flash-Lite (Fast, Active Quota)'),
        ('gemini-2.5-flash', 'Gemini 2.5 Flash (Fast & Precise Multimodal)'),
        ('gemini-2.0-flash', 'Gemini 2.0 Flash (Ultra-Fast)'),
        ('gemini-1.5-flash', 'Gemini 1.5 Flash (Standard)'),
        ('gemini-1.5-pro', 'Gemini 1.5 Pro (Deep Document Reasoning)'),
        ('custom', 'Custom Model...'),
    ]

    OPENAI_MODELS = [
        ('gpt-4o', 'GPT-4o (Omni Multimodal Vision & OCR)'),
        ('gpt-4o-mini', 'GPT-4o Mini (Fast & Cost Efficient)'),
        ('gpt-4-turbo', 'GPT-4 Turbo with Vision'),
        ('o1-mini', 'o1-mini (Reasoning & Extraction)'),
        ('custom', 'Custom Model...'),
    ]

    model_name = fields.Char(string='Model Code', required=True, default='native-adaptive-v1')
    native_model = fields.Selection(NATIVE_MODELS, string='Native Engine Strategy', default='native-adaptive-v1')
    gemini_model = fields.Selection(GEMINI_MODELS, string='Gemini Model', default='gemini-3.8-flash')
    openai_model = fields.Selection(OPENAI_MODELS, string='OpenAI Model', default='gpt-4o')

    temperature = fields.Float(string='Temperature', default=0.1, help='Lower temperature ensures deterministic JSON extraction')
    max_tokens = fields.Integer(string='Max Output Tokens', default=65536)
    timeout_seconds = fields.Integer(string='Timeout (Seconds)', default=120)

    # Telemetry
    total_parsed_pages = fields.Integer(string='Total Pages Processed', default=0, readonly=True)
    total_parsed_txns = fields.Integer(string='Total Transactions Extracted', default=0, readonly=True)
    last_status = fields.Char(string='Last Connection Status', readonly=True, default='Not Tested')
    has_api_key = fields.Boolean(string='Has API Key', compute='_compute_has_api_key')
    supported_models_json = fields.Text(string='Supported Models JSON Cache')
    supported_models_count = fields.Integer(
        string='Verified Models Count',
        compute='_compute_supported_models_count',
        help='Count of live supported models returned by the AI provider API.'
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._sync_model_fields(vals)
        return super().create(vals_list)

    def write(self, vals):
        self._sync_model_fields(vals)
        res = super().write(vals)
        if vals.get('is_active'):
            for rec in self:
                if rec.is_active:
                    self.search([('id', '!=', rec.id), ('is_active', '=', True)]).write({'is_active': False})
        return res

    def _sync_model_fields(self, vals):
        ptype = vals.get('provider_type') or (self and self[:1].provider_type) or 'gemini'
        if ptype == 'gemini':
            if 'model_name' in vals and ('argon' in (vals['model_name'] or '').lower() or vals['model_name'] == 'gemini-2.5-flash'):
                vals['model_name'] = 'gemini-3.8-flash'
                vals['gemini_model'] = 'gemini-3.8-flash'
            known = [k for k, _ in self.GEMINI_MODELS if k != 'custom']
            if 'model_name' in vals and 'gemini_model' not in vals:
                vals['gemini_model'] = vals['model_name'] if vals['model_name'] in known else 'custom'
            elif 'gemini_model' in vals and vals['gemini_model'] != 'custom' and 'model_name' not in vals:
                vals['model_name'] = vals['gemini_model']
        elif ptype == 'openai':
            known = [k for k, _ in self.OPENAI_MODELS if k != 'custom']
            if 'model_name' in vals and 'openai_model' not in vals:
                vals['openai_model'] = vals['model_name'] if vals['model_name'] in known else 'custom'
            elif 'openai_model' in vals and vals['openai_model'] != 'custom' and 'model_name' not in vals:
                vals['model_name'] = vals['openai_model']
        elif ptype == 'native':
            known = [k for k, _ in self.NATIVE_MODELS if k != 'custom']
            if 'model_name' in vals and 'native_model' not in vals:
                vals['native_model'] = vals['model_name'] if vals['model_name'] in known else 'custom'
            elif 'native_model' in vals and vals['native_model'] != 'custom' and 'model_name' not in vals:
                vals['model_name'] = vals['native_model']

    @api.onchange('provider_type')
    def _onchange_provider_type(self):
        if self.provider_type == 'native':
            self.model_name = self.native_model or 'native-adaptive-v1'
            if not self.name or self.name == 'Provider':
                self.name = 'Native Python Engine (100% Offline)'
        elif self.provider_type == 'gemini':
            self.model_name = self.gemini_model or 'gemini-3.8-flash'
            if not self.name or self.name == 'Provider':
                self.name = 'Google Gemini Multimodal'
        elif self.provider_type == 'openai':
            self.model_name = self.openai_model or 'gpt-4o'
            if not self.name or self.name == 'Provider':
                self.name = 'OpenAI GPT-4o Vision'

    @api.onchange('native_model', 'gemini_model', 'openai_model')
    def _onchange_sub_models(self):
        if self.provider_type == 'native' and self.native_model and self.native_model != 'custom':
            self.model_name = self.native_model
        elif self.provider_type == 'gemini' and self.gemini_model and self.gemini_model != 'custom':
            self.model_name = self.gemini_model
        elif self.provider_type == 'openai' and self.openai_model and self.openai_model != 'custom':
            self.model_name = self.openai_model

    @api.onchange('model_name')
    def _onchange_model_name(self):
        if not self.model_name:
            return
        m = self.model_name.strip()
        if self.provider_type == 'native':
            known = [k for k, _ in self.NATIVE_MODELS if k != 'custom']
            self.native_model = m if m in known else 'custom'
        elif self.provider_type == 'gemini':
            known = [k for k, _ in self.GEMINI_MODELS if k != 'custom']
            self.gemini_model = m if m in known else 'custom'
        elif self.provider_type == 'openai':
            known = [k for k, _ in self.OPENAI_MODELS if k != 'custom']
            self.openai_model = m if m in known else 'custom'

    def _compute_api_key(self):
        vault = self.env['gsus.bank.ai.vault']
        for record in self:
            if record.api_key_encrypted:
                decrypted = vault.decrypt_secret(record.api_key_encrypted)
                record.api_key = vault.mask_secret(decrypted)
            else:
                record.api_key = ''

    def _compute_has_api_key(self):
        for record in self:
            record.has_api_key = bool(record.api_key_encrypted)

    def _compute_supported_models_count(self):
        for record in self:
            count = 0
            if record.supported_models_json:
                try:
                    data = json.loads(record.supported_models_json)
                    count = len(data) if isinstance(data, list) else 0
                except Exception:
                    count = 0
            record.supported_models_count = count

    def _inverse_api_key(self):
        vault = self.env['gsus.bank.ai.vault']
        for record in self:
            val = (record.api_key or '').strip()
            if val and not val.endswith('••••••••'):
                record.api_key_encrypted = vault.encrypt_secret(val)

    def action_test_connection(self):
        self.ensure_one()
        vault = self.env['gsus.bank.ai.vault']
        raw_key = vault.decrypt_secret(self.api_key_encrypted) if self.api_key_encrypted else ''
        if not raw_key and self.provider_type not in ('native',):
            raise UserError("Please enter and save your API Secret Key first.")

        parser = self.env['gsus.bank.ai.vision.parser']
        try:
            res = parser.test_provider_ping_and_fetch_models(
                self.provider_type,
                raw_key,
                model_name=self.model_name,
                timeout=self.timeout_seconds or 15,
            )
            status_text = res.get('message', 'Connected')
            supported_models = res.get('supported_models', [])
            vals = {
                'last_status': f"✅ {status_text}",
            }
            if supported_models:
                vals['supported_models_json'] = json.dumps(supported_models)
            self.write(vals)

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'AI Engine Verified',
                    'message': f"Provider '{self.name}' pinged successfully: {status_text}",
                    'type': 'success',
                    'sticky': False,
                }
            }
        except Exception as e:
            self.last_status = f"❌ Error: {str(e)[:100]}"
            raise UserError(f"Connection test failed for {self.name}: {str(e)}")
