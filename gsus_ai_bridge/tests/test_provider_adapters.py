# -*- coding: utf-8 -*-
# Part of GSUS AI. See LICENSE file for full copyright and licensing details.

from unittest.mock import patch, MagicMock
from odoo.tests.common import TransactionCase
from odoo.addons.gsus_ai_bridge.models.adapters.openai_adapter import OpenAIProviderAdapter
from odoo.addons.gsus_ai_bridge.models.adapters.anthropic_adapter import AnthropicProviderAdapter


class TestProviderAdapters(TransactionCase):

    def setUp(self):
        super().setUp()
        self.vault = self.env['gsus.ai.secret.vault']
        self.provider_groq = self.env['gsus.ai.provider'].create({
            'name': 'Test Groq',
            'provider_type': 'groq',
            'model_name': 'qwen/qwen3.8-27b',
            'api_key': 'gsk-test-secret-1234567890',
        })
        self.provider_claude = self.env['gsus.ai.provider'].create({
            'name': 'Test Claude',
            'provider_type': 'anthropic',
            'model_name': 'claude-3-7-sonnet-20250219',
            'api_key': 'sk-ant-test-9876543210',
        })

    def test_01_secret_vault_encryption(self):
        raw = "my_top_secret_api_key_12345"
        encrypted = self.vault.encrypt_secret(raw)
        self.assertNotEqual(raw, encrypted)
        decrypted = self.vault.decrypt_secret(encrypted)
        self.assertEqual(raw, decrypted)

        # Test masking
        masked = self.vault.mask_secret(raw)
        self.assertTrue(masked.startswith("my_to"))
        self.assertTrue(masked.endswith("2345"))
        self.assertIn("••••", masked)

    def test_02_groq_adapter_mock_generation(self):
        adapter = self.provider_groq.get_adapter()
        self.assertIsInstance(adapter, OpenAIProviderAdapter)

        # Test tool formatting
        sample_tools = [{
            'code': 'search_partner',
            'description': 'Search partners by name',
            'json_schema': {
                'type': 'object',
                'properties': {'query': {'type': 'string'}},
                'required': ['query'],
            }
        }]
        formatted = adapter.format_tools(sample_tools)
        self.assertEqual(len(formatted), 1)
        self.assertEqual(formatted[0]['type'], 'function')
        self.assertEqual(formatted[0]['function']['name'], 'search_partner')

        # Test mocked response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'choices': [{
                'message': {
                    'role': 'assistant',
                    'content': 'Hello from mocked Groq!',
                    'tool_calls': None,
                }
            }],
            'usage': {'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15},
            'model': 'qwen/qwen3.8-27b',
        }

        with patch('requests.post', return_value=mock_response):
            resp = adapter.generate_response([{'role': 'user', 'content': 'Hello'}])
            self.assertTrue(resp.is_success)
            self.assertEqual(resp.content, 'Hello from mocked Groq!')
            self.assertEqual(resp.total_tokens, 15)

    def test_03_anthropic_adapter_mock_generation(self):
        adapter = self.provider_claude.get_adapter()
        self.assertIsInstance(adapter, AnthropicProviderAdapter)

        # Test mocked response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'content': [{'type': 'text', 'text': 'Hello from mocked Claude!'}],
            'usage': {'input_tokens': 12, 'output_tokens': 8},
            'model': 'claude-3-7-sonnet-20250219',
        }

        with patch('requests.post', return_value=mock_response):
            resp = adapter.generate_response([{'role': 'user', 'content': 'Hello'}])
            self.assertTrue(resp.is_success)
            self.assertEqual(resp.content, 'Hello from mocked Claude!')
            self.assertEqual(resp.total_tokens, 20)
