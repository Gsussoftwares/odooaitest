# -*- coding: utf-8 -*-
# Part of GSUS AI. See LICENSE file for full copyright and licensing details.

import time
import logging
import requests
from typing import Dict, Any, List, Optional
from ..provider_base import BaseAIProvider, ProviderResponse

_logger = logging.getLogger(__name__)


class AnthropicProviderAdapter(BaseAIProvider):
    """Adapter for official Anthropic Claude Messages API."""

    DEFAULT_BASE_URL = "https://api.anthropic.com/v1"
    DEFAULT_MODEL = "claude-3-7-sonnet-20250219"
    ANTHROPIC_VERSION = "2023-06-01"

    def get_capabilities(self) -> Dict[str, Any]:
        return {
            'tools': True,
            'streaming': True,
            'vision': True,
            'json_mode': False,
            'max_tokens': 200000,
        }

    def validate_configuration(self) -> List[str]:
        errors = []
        api_key = self.provider.get_decrypted_key()
        if not api_key:
            errors.append("Anthropic API key is missing. Please configure an API key (sk-ant-...).")
        if not self.provider.model_name:
            errors.append("Claude model identifier is missing (e.g., claude-3-7-sonnet-20250219).")
        return errors

    def test_connection(self) -> Dict[str, Any]:
        errors = self.validate_configuration()
        if errors:
            return {'success': False, 'message': "; ".join(errors)}

        base_url = (self.provider.base_url or self.DEFAULT_BASE_URL).rstrip('/')
        api_key = self.provider.get_decrypted_key()
        headers = {
            'x-api-key': api_key,
            'anthropic-version': self.ANTHROPIC_VERSION,
            'content-type': 'application/json',
        }
        test_payload = {
            'model': self.provider.model_name or self.DEFAULT_MODEL,
            'max_tokens': 5,
            'messages': [{'role': 'user', 'content': 'Test ping'}],
        }

        start_time = time.time()
        try:
            resp = requests.post(
                f"{base_url}/messages",
                headers=headers,
                json=test_payload,
                timeout=self.provider.timeout_seconds or 15,
            )
            duration_ms = round((time.time() - start_time) * 1000, 2)
            if resp.status_code == 200:
                return {
                    'success': True,
                    'message': f"Connection successful! Latency: {duration_ms}ms.",
                    'duration_ms': duration_ms,
                }
            error_data = resp.json().get('error', {}) if resp.text else {}
            error_msg = error_data.get('message', f"HTTP {resp.status_code}: {resp.text}")
            return {'success': False, 'message': f"Anthropic Error: {error_msg}"}
        except requests.exceptions.Timeout:
            return {'success': False, 'message': "Connection timed out. Check network or timeout limit."}
        except Exception as e:
            return {'success': False, 'message': f"Connection failed: {str(e)}"}

    def format_tools(self, tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Format standard tools into Anthropic tool schema format."""
        formatted = []
        for tool in tools:
            formatted.append({
                'name': tool.get('code') or tool.get('name'),
                'description': tool.get('description', ''),
                'input_schema': tool.get('json_schema') or {
                    'type': 'object',
                    'properties': {},
                },
            })
        return formatted

    def parse_tool_calls(self, raw_response: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extract tool calls from Claude content blocks."""
        tool_calls = []
        content_blocks = raw_response.get('content') or []
        for block in content_blocks:
            if block.get('type') == 'tool_use':
                tool_calls.append({
                    'id': block.get('id', ''),
                    'name': block.get('name', ''),
                    'arguments': block.get('input', {}),
                })
        return tool_calls

    def generate_response(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> ProviderResponse:
        options = options or {}
        base_url = (self.provider.base_url or self.DEFAULT_BASE_URL).rstrip('/')
        api_key = self.provider.get_decrypted_key()
        if not api_key:
            return ProviderResponse(error="Anthropic API key is missing. Please set your API key in Settings.")

        headers = {
            'x-api-key': api_key,
            'anthropic-version': self.ANTHROPIC_VERSION,
            'content-type': 'application/json',
        }

        # Separate system prompt from messages (Anthropic requirement)
        system_prompt = ""
        claude_messages = []
        for msg in messages:
            role = msg.get('role', 'user')
            content = msg.get('content', '')
            if role == 'system':
                system_prompt += (content + "\n\n")
            elif role == 'tool':
                # Tool result in Anthropic format
                claude_messages.append({
                    'role': 'user',
                    'content': [{
                        'type': 'tool_result',
                        'tool_use_id': msg.get('tool_call_id', ''),
                        'content': content,
                    }]
                })
            else:
                claude_messages.append({
                    'role': role,
                    'content': content,
                })

        payload = {
            'model': self.provider.model_name or self.DEFAULT_MODEL,
            'max_tokens': options.get('max_tokens') or self.provider.max_tokens or 4096,
            'messages': claude_messages or [{'role': 'user', 'content': 'Hello'}],
            'temperature': options.get('temperature', self.provider.temperature or 0.7),
        }
        if system_prompt.strip():
            payload['system'] = system_prompt.strip()

        if tools:
            payload['tools'] = self.format_tools(tools)

        max_retries = self.provider.max_retries or 2
        start_time = time.time()
        for attempt in range(max_retries + 1):
            try:
                resp = requests.post(
                    f"{base_url}/messages",
                    headers=headers,
                    json=payload,
                    timeout=self.provider.timeout_seconds or 30,
                )
                duration_ms = round((time.time() - start_time) * 1000, 2)
                if resp.status_code == 200:
                    data = resp.json()
                    content_blocks = data.get('content', [])
                    text_parts = [b.get('text', '') for b in content_blocks if b.get('type') == 'text']
                    content = "\n".join(text_parts)
                    tool_calls = self.parse_tool_calls(data)

                    usage = data.get('usage', {})
                    return ProviderResponse(
                        content=content,
                        tool_calls=tool_calls,
                        raw_response=data,
                        prompt_tokens=usage.get('input_tokens', 0),
                        completion_tokens=usage.get('output_tokens', 0),
                        total_tokens=usage.get('input_tokens', 0) + usage.get('output_tokens', 0),
                        model=data.get('model', payload['model']),
                        duration_ms=duration_ms,
                    )
                elif resp.status_code == 429 and attempt < max_retries:
                    time.sleep(2 ** attempt)
                    continue
                else:
                    err_json = resp.json().get('error', {}) if resp.text else {}
                    err_msg = err_json.get('message', f"HTTP {resp.status_code}: {resp.text}")
                    return ProviderResponse(error=f"Claude API Error: {err_msg}", duration_ms=duration_ms)
            except requests.exceptions.Timeout:
                if attempt < max_retries:
                    time.sleep(1)
                    continue
                return ProviderResponse(error="Request to Claude timed out.", duration_ms=round((time.time() - start_time) * 1000, 2))
            except Exception as e:
                return ProviderResponse(error=f"Claude Communication Error: {str(e)}", duration_ms=round((time.time() - start_time) * 1000, 2))

        return ProviderResponse(error="Failed after maximum retries.")
