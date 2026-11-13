# -*- coding: utf-8 -*-
# Part of GSUS AI. See LICENSE file for full copyright and licensing details.

import json
import time
import logging
import requests
from typing import Dict, Any, List, Optional
from ..provider_base import BaseAIProvider, ProviderResponse

_logger = logging.getLogger(__name__)


class OpenAIProviderAdapter(BaseAIProvider):
    """Adapter for official OpenAI / ChatGPT API."""

    DEFAULT_BASE_URL = "https://api.openai.com/v1"
    DEFAULT_MODEL = "gpt-4o"

    def get_capabilities(self) -> Dict[str, Any]:
        return {
            'tools': True,
            'streaming': True,
            'vision': True,
            'json_mode': True,
            'max_tokens': 128000,
        }

    def validate_configuration(self) -> List[str]:
        errors = []
        api_key = self.provider.get_decrypted_key()
        if not api_key:
            errors.append("OpenAI API key is missing. Please configure a valid API key.")
        if not self.provider.model_name:
            errors.append("Model name is missing (e.g., gpt-4o, gpt-4o-mini).")
        return errors

    def test_connection(self) -> Dict[str, Any]:
        errors = self.validate_configuration()
        if errors:
            return {'success': False, 'message': "; ".join(errors)}

        base_url = (self.provider.base_url or self.DEFAULT_BASE_URL).rstrip('/')
        api_key = self.provider.get_decrypted_key()
        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
            'User-Agent': 'Mozilla/5.0',
        }
        test_payload = {
            'model': self.provider.model_name or self.DEFAULT_MODEL,
            'messages': [{'role': 'user', 'content': 'Test connection ping'}],
            'max_tokens': 5,
        }

        start_time = time.time()
        try:
            resp = requests.post(
                f"{base_url}/chat/completions",
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
            return {'success': False, 'message': f"OpenAI Error: {error_msg}"}
        except requests.exceptions.Timeout:
            return {'success': False, 'message': "Connection timed out. Check network or timeout limit."}
        except Exception as e:
            return {'success': False, 'message': f"Connection failed: {str(e)}"}

    def format_tools(self, tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Format standard tools into OpenAI function calling format."""
        formatted = []
        for tool in tools:
            formatted.append({
                'type': 'function',
                'function': {
                    'name': tool.get('code') or tool.get('name'),
                    'description': tool.get('description', ''),
                    'parameters': tool.get('json_schema') or {
                        'type': 'object',
                        'properties': {},
                    },
                }
            })
        return formatted

    def parse_tool_calls(self, raw_choice: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extract tool calls from OpenAI response choice."""
        tool_calls = []
        message = raw_choice.get('message', {})
        raw_calls = message.get('tool_calls') or []
        for call in raw_calls:
            func = call.get('function', {})
            arguments = func.get('arguments', '{}')
            try:
                parsed_args = json.loads(arguments) if isinstance(arguments, str) else arguments
            except Exception:
                parsed_args = {'raw_arguments': arguments}
            tool_calls.append({
                'id': call.get('id', ''),
                'type': 'function',
                'name': func.get('name', ''),
                'arguments': parsed_args,
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
            return ProviderResponse(error="OpenAI API key is missing. Please set your API key in Settings.")

        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
            'User-Agent': 'Mozilla/5.0',
        }

        # Build a lookup: tool_call_id -> tool_name from assistant messages
        tool_id_to_name = {}
        for msg in messages:
            for tc in (msg.get('tool_calls') or []):
                cid = tc.get('id') or ''
                cname = tc.get('name') or (tc.get('function', {}).get('name') if isinstance(tc.get('function'), dict) else '')
                if cid and cname:
                    tool_id_to_name[cid] = cname

        # Normalize messages
        formatted_messages = []
        for msg in messages:
            role = msg.get('role', 'user')
            content = msg.get('content', '')
            entry = {'role': role, 'content': content}
            if role == 'tool':
                tcid = msg.get('tool_call_id', '')
                entry['tool_call_id'] = tcid
                # Groq + strict OpenAI require a 'name' field on tool messages
                entry['name'] = msg.get('name') or tool_id_to_name.get(tcid) or 'tool_result'
            if msg.get('tool_calls'):
                valid_calls = []
                for tc in msg.get('tool_calls'):
                    cid = tc.get('id') or ''
                    cname = tc.get('name') or (tc.get('function', {}).get('name') if isinstance(tc.get('function'), dict) else '')
                    cargs = tc.get('arguments') or (tc.get('function', {}).get('arguments') if isinstance(tc.get('function'), dict) else {})
                    args_str = json.dumps(cargs) if isinstance(cargs, (dict, list)) else str(cargs)
                    valid_calls.append({
                        'id': cid,
                        'type': 'function',
                        'function': {
                            'name': cname,
                            'arguments': args_str,
                        }
                    })
                if valid_calls:
                    entry['tool_calls'] = valid_calls
            formatted_messages.append(entry)

        chosen_model = options.get('model') or self.provider.model_name or self.DEFAULT_MODEL
        payload = {
            'model': chosen_model,
            'messages': formatted_messages,
            'temperature': options.get('temperature', self.provider.temperature or 0.7),
        }
        if options.get('max_tokens') or self.provider.max_tokens:
            payload['max_tokens'] = options.get('max_tokens') or self.provider.max_tokens

        if tools:
            payload['tools'] = self.format_tools(tools)
            payload['tool_choice'] = 'auto'

        max_retries = self.provider.max_retries or 2
        start_time = time.time()
        for attempt in range(max_retries + 1):
            try:
                resp = requests.post(
                    f"{base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=self.provider.timeout_seconds or 30,
                )
                duration_ms = round((time.time() - start_time) * 1000, 2)
                if resp.status_code == 200:
                    data = resp.json()
                    choices = data.get('choices', [])
                    first_choice = choices[0] if choices else {}
                    message_obj = first_choice.get('message', {})
                    content = message_obj.get('content') or ""
                    tool_calls = self.parse_tool_calls(first_choice)

                    usage = data.get('usage', {})
                    return ProviderResponse(
                        content=content,
                        tool_calls=tool_calls,
                        raw_response=data,
                        prompt_tokens=usage.get('prompt_tokens', 0),
                        completion_tokens=usage.get('completion_tokens', 0),
                        total_tokens=usage.get('total_tokens', 0),
                        model=data.get('model', payload['model']),
                        duration_ms=duration_ms,
                    )
                elif resp.status_code == 429 and attempt < max_retries:
                    wait_seconds = 2 ** attempt
                    try:
                        import re
                        match = re.search(r'try again in (\d+\.?\d*)s', resp.text)
                        if match:
                            wait_seconds = min(float(match.group(1)) + 0.5, 15.0)
                        elif 'retry-after' in resp.headers:
                            wait_seconds = min(float(resp.headers['retry-after']), 15.0)
                    except Exception:
                        pass
                    _logger.warning("Rate limit hit on %s (attempt %s). Retrying in %.1fs...", chosen_model, attempt + 1, wait_seconds)
                    time.sleep(wait_seconds)
                    continue
                else:
                    err_json = resp.json().get('error', {}) if resp.text else {}
                    err_msg = err_json.get('message', f"HTTP {resp.status_code}: {resp.text}")
                    return ProviderResponse(error=f"API Notice ({chosen_model}): {err_msg}", duration_ms=duration_ms)
            except requests.exceptions.Timeout:
                if attempt < max_retries:
                    time.sleep(1)
                    continue
                return ProviderResponse(error="Request to OpenAI timed out.", duration_ms=round((time.time() - start_time) * 1000, 2))
            except Exception as e:
                return ProviderResponse(error=f"OpenAI Communication Error: {str(e)}", duration_ms=round((time.time() - start_time) * 1000, 2))

        return ProviderResponse(error="Failed after maximum retries.")
