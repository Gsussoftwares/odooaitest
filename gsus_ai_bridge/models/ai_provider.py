# -*- coding: utf-8 -*-
# Part of GSUS AI. See LICENSE file for full copyright and licensing details.

import logging
from odoo import models, fields, api
from odoo.exceptions import UserError
from .adapters.openai_adapter import OpenAIProviderAdapter
from .adapters.anthropic_adapter import AnthropicProviderAdapter
from .adapters.gemini_adapter import GeminiProviderAdapter

_logger = logging.getLogger(__name__)


class GsusAiProvider(models.Model):
    _name = 'gsus.ai.provider'
    _description = 'GSUS AI Provider Configuration'
    _order = 'sequence, id'

    name = fields.Char(string='Provider Name', required=True)
    sequence = fields.Integer(string='Sequence', default=10)
    provider_type = fields.Selection([
        ('groq', 'Groq (Ultra-Fast Free AI)'),
        ('gemini', 'Google Gemini'),
        ('anthropic', 'Anthropic Claude'),
    ], string='Provider Type', required=True, default='groq')

    base_url = fields.Char(string='Endpoint URL', help='Optional custom API base URL')
    api_key_encrypted = fields.Char(string='Encrypted API Key', readonly=True)
    api_key = fields.Char(
        string='API Key / Token',
        compute='_compute_api_key',
        inverse='_inverse_api_key',
        help='Enter your provider secret API key. Stored encrypted with AES/hash vault.',
    )

    GEMINI_MODELS = [
        ('gemini-3.5-flash-lite', 'Gemini 3.5 Flash-Lite (Fast, Active Quota)'),
        ('gemini-3.5-flash', 'Gemini 3.5 Flash (Recommended)'),
        ('gemini-3.1-flash-lite', 'Gemini 3.1 Flash-Lite'),
        ('gemini-3.1-pro-preview', 'Gemini 3.1 Pro Preview'),
        ('gemini-2.5-flash', 'Gemini 2.5 Flash'),
        ('gemini-2.5-pro', 'Gemini 2.5 Pro'),
        ('gemini-flash-latest', 'Gemini Flash Latest'),
        ('custom', 'Custom Model...'),
    ]

    ANTHROPIC_MODELS = [
        ('claude-3-7-sonnet-20250219', 'Claude 3.7 Sonnet (Hybrid Reasoning)'),
        ('claude-3-5-sonnet-20241022', 'Claude 3.5 Sonnet v2 (Recommended)'),
        ('claude-3-5-haiku-20241022', 'Claude 3.5 Haiku (Fast & Lightweight)'),
        ('claude-3-opus-20240229', 'Claude 3 Opus'),
        ('custom', 'Custom Model...'),
    ]

    GROQ_MODELS = [
        ('qwen/qwen3.8-27b', 'Qwen 3.8 27B (Ultra-Fast & Smart)'),
        ('openai/gpt-oss-120b', 'GPT-OSS 120B (High Intelligence)'),
        ('openai/gpt-oss-20b', 'GPT-OSS 20B (Fast & Lightweight)'),
        ('allam-2-7b', 'Allam 2 7B'),
        ('custom', 'Custom Model...'),
    ]

    model_name = fields.Char(string='Model Name', default='qwen/qwen3.8-27b', required=True, help='Model identifier (e.g. qwen/qwen3.8-27b, gemini-3.5-flash-lite)')

    groq_model = fields.Selection(
        GROQ_MODELS, string='Model Name',
        compute='_compute_models', inverse='_inverse_groq_model', store=True
    )
    gemini_model = fields.Selection(
        GEMINI_MODELS, string='Model Name',
        compute='_compute_models', inverse='_inverse_gemini_model', store=True
    )
    anthropic_model = fields.Selection(
        ANTHROPIC_MODELS, string='Model Name',
        compute='_compute_models', inverse='_inverse_anthropic_model', store=True
    )

    # Backward compatibility dummy fields for cached browser views
    openai_model = fields.Char(string='OpenAI Model (Deprecated)', compute='_compute_deprecated_models', store=False)
    antigravity_model = fields.Char(string='Antigravity Model (Deprecated)', compute='_compute_deprecated_models', store=False)

    def _compute_deprecated_models(self):
        for record in self:
            record.openai_model = False
            record.antigravity_model = False

    temperature = fields.Float(string='Temperature', default=0.7)
    max_tokens = fields.Integer(string='Max Tokens', default=4096)
    timeout_seconds = fields.Integer(string='Timeout (Seconds)', default=30)
    max_retries = fields.Integer(string='Max Retries', default=2)

    is_active = fields.Boolean(string='Active', default=True)
    state = fields.Selection([
        ('draft', 'Not Verified'),
        ('connected', 'Connected & Healthy'),
        ('error', 'Connection Error'),
    ], string='Status', default='draft', readonly=True)

    last_health_check = fields.Datetime(string='Last Health Check', readonly=True)
    last_error_message = fields.Text(string='Diagnostic Message', readonly=True)

    total_calls_count = fields.Integer(string='Total Requests', default=0, readonly=True)
    total_tokens_used = fields.Integer(string='Total Tokens Used', default=0, readonly=True)

    @api.depends('model_name', 'provider_type')
    def _compute_models(self):
        groq_keys = {m[0] for m in self.GROQ_MODELS}
        gemini_keys = {m[0] for m in self.GEMINI_MODELS}
        anthropic_keys = {m[0] for m in self.ANTHROPIC_MODELS}

        for record in self:
            mn = record.model_name or ''
            pt = record.provider_type

            if pt == 'groq':
                record.groq_model = mn if mn in groq_keys else 'custom'
                record.gemini_model = False
                record.anthropic_model = False
            elif pt == 'gemini':
                record.gemini_model = mn if mn in gemini_keys else 'custom'
                record.groq_model = False
                record.anthropic_model = False
            elif pt == 'anthropic':
                record.anthropic_model = mn if mn in anthropic_keys else 'custom'
                record.groq_model = False
                record.gemini_model = False
            else:
                record.groq_model = 'custom'
                record.gemini_model = False
                record.anthropic_model = False

    def _inverse_groq_model(self):
        for record in self:
            if record.provider_type == 'groq' and record.groq_model and record.groq_model != 'custom':
                record.model_name = record.groq_model

    def _inverse_gemini_model(self):
        for record in self:
            if record.provider_type == 'gemini' and record.gemini_model and record.gemini_model != 'custom':
                record.model_name = record.gemini_model

    def _inverse_anthropic_model(self):
        for record in self:
            if record.provider_type == 'anthropic' and record.anthropic_model and record.anthropic_model != 'custom':
                record.model_name = record.anthropic_model

    @api.onchange('provider_type')
    def _onchange_provider_type(self):
        if self.provider_type == 'groq':
            self.model_name = 'qwen/qwen3.8-27b'
            self.groq_model = 'qwen/qwen3.8-27b'
            self.base_url = 'https://api.groq.com/openai/v1'
        elif self.provider_type == 'anthropic':
            self.model_name = 'claude-3-7-sonnet-20250219'
            self.anthropic_model = 'claude-3-7-sonnet-20250219'
            self.base_url = 'https://api.anthropic.com/v1'
        elif self.provider_type == 'gemini':
            self.model_name = 'gemini-3.5-flash-lite'
            self.gemini_model = 'gemini-3.5-flash-lite'
            self.base_url = 'https://generativelanguage.googleapis.com/v1beta'

    def _compute_api_key(self):
        vault = self.env['gsus.ai.secret.vault']
        for record in self:
            if record.api_key_encrypted:
                decrypted = vault.decrypt_secret(record.api_key_encrypted)
                record.api_key = vault.mask_secret(decrypted)
            else:
                record.api_key = ""

    def _inverse_api_key(self):
        vault = self.env['gsus.ai.secret.vault']
        for record in self:
            if record.api_key and "••••" not in record.api_key:
                record.api_key_encrypted = vault.encrypt_secret(record.api_key.strip())

    def get_decrypted_key(self) -> str:
        """Retrieve raw plaintext API key on server only for authorized outgoing requests."""
        self.ensure_one()
        if not self.api_key_encrypted:
            return ""
        return self.env['gsus.ai.secret.vault'].decrypt_secret(self.api_key_encrypted)

    def get_adapter(self):
        """Instantiate the concrete adapter for this provider."""
        self.ensure_one()
        if self.provider_type in ('openai', 'groq'):
            return OpenAIProviderAdapter(self)
        elif self.provider_type == 'anthropic':
            return AnthropicProviderAdapter(self)
        elif self.provider_type == 'gemini':
            return GeminiProviderAdapter(self)
        raise UserError(f"Unsupported provider type: {self.provider_type}")

    def action_test_connection(self):
        """Test connectivity and update state."""
        self.ensure_one()
        adapter = self.get_adapter()
        result = adapter.test_connection()
        self.last_health_check = fields.Datetime.now()
        if result.get('success'):
            self.state = 'connected'
            self.last_error_message = result.get('message', 'Connection successful')
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Connection Success',
                    'message': self.last_error_message,
                    'type': 'success',
                    'sticky': False,
                }
            }
        else:
            self.state = 'error'
            self.last_error_message = result.get('message', 'Unknown error')
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Connection Failed',
                    'message': self.last_error_message,
                    'type': 'danger',
                    'sticky': True,
                }
            }

    def track_usage(self, total_tokens: int):
        """Increment usage metrics."""
        for record in self:
            record.sudo().write({
                'total_calls_count': record.total_calls_count + 1,
                'total_tokens_used': record.total_tokens_used + max(0, total_tokens),
            })
