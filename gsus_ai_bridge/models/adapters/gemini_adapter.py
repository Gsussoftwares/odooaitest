# -*- coding: utf-8 -*-
# Part of GSUS AI. See LICENSE file for full copyright and licensing details.

import json
import time
import logging
import requests
from ..provider_base import BaseAIProvider, ProviderResponse

_logger = logging.getLogger(__name__)


class GeminiProviderAdapter(BaseAIProvider):
    """Google Gemini REST adapter. Supports gemini-2.0-flash, gemini-1.5-pro, gemini-1.5-flash."""

    DEFAULT_BASE_URL = 'https://generativelanguage.googleapis.com/v1beta'
    DEFAULT_MODEL = 'gemini-3.5-flash'

    def get_capabilities(self):
        return {'tools': True, 'streaming': False, 'vision': True, 'json_mode': True, 'max_tokens': 1048576}

    def validate_configuration(self):
        errors = []
        if not self.provider.get_decrypted_key():
            errors.append('Google Gemini API key is missing. Get one at https://aistudio.google.com/app/apikey')
        if not self.provider.model_name:
            errors.append('Model name is missing (e.g., gemini-3.5-flash, gemini-3.8-flash).')
        return errors

    def test_connection(self):
        errors = self.validate_configuration()
        if errors:
            return {'success': False, 'message': '; '.join(errors)}
        base_url = (self.provider.base_url or self.DEFAULT_BASE_URL).rstrip('/')
        api_key = self.provider.get_decrypted_key()
        model = self.provider.model_name or self.DEFAULT_MODEL
        url = '{}/models/{}:generateContent?key={}'.format(base_url, model, api_key)
        payload = {
            'contents': [{'role': 'user', 'parts': [{'text': 'Reply with: OK'}]}],
            'generationConfig': {'maxOutputTokens': 10},
        }
        start = time.time()
        try:
            resp = requests.post(url, headers={'Content-Type': 'application/json'}, json=payload, timeout=15)
            ms = round((time.time() - start) * 1000, 2)
            if resp.status_code == 200:
                return {'success': True, 'message': 'Gemini OK! Model: {}. Latency: {}ms.'.format(model, ms)}
            err_data = resp.json() if resp.text else {}
            err = err_data.get('error', {}).get('message', 'HTTP {}'.format(resp.status_code))
            return {'success': False, 'message': 'Gemini Error: {}'.format(err)}
        except Exception as exc:
            return {'success': False, 'message': 'Connection failed: {}'.format(exc)}

    def format_tools(self, tools):
        decls = []
        for t in tools:
            schema = t.get('json_schema') or {'type': 'object', 'properties': {}}
            decls.append({
                'name': t.get('code') or t.get('name'),
                'description': t.get('description', ''),
                'parameters': schema,
            })
        return [{'functionDeclarations': decls}]

    def parse_tool_calls(self, raw_response):
        tool_calls = []
        for c in (raw_response.get('candidates') or []):
            for p in (c.get('content', {}).get('parts') or []):
                fc = p.get('functionCall')
                if fc:
                    fc_name = fc.get('name', '')
                    tool_calls.append({
                        'id': fc.get('id') or 'gfc_{}_{}'.format(fc_name, int(time.time() * 1000)),
                        'name': fc_name,
                        'arguments': fc.get('args', {}),
                        'thought_signature': p.get('thoughtSignature') or p.get('thought_signature'),
                    })
        return tool_calls

    def _build_contents(self, messages):
        sys_parts = []
        contents = []
        for msg in messages:
            role = msg.get('role', 'user')
            content = msg.get('content', '')
            tcs = msg.get('tool_calls') or []
            if role == 'system':
                sys_parts.append({'text': content})
                continue
            if role == 'user':
                u_parts = [{'text': content or ' '}]
                img_info = msg.get('image_data')
                if img_info and isinstance(img_info, dict) and img_info.get('data'):
                    u_parts.append({
                        'inlineData': {
                            'mimeType': img_info.get('mime_type') or 'image/png',
                            'data': img_info.get('data'),
                        }
                    })
                contents.append({'role': 'user', 'parts': u_parts})
            elif role == 'assistant':
                parts = []
                if content:
                    parts.append({'text': content})
                for tc in tcs:
                    n = tc.get('name') or ''
                    if not n and isinstance(tc.get('function'), dict):
                        n = tc['function'].get('name', '')
                    a = tc.get('arguments') or {}
                    if not a and isinstance(tc.get('function'), dict):
                        a = tc['function'].get('arguments', {})
                    if isinstance(a, str):
                        try:
                            a = json.loads(a)
                        except Exception:
                            a = {}
                    call_part = {'functionCall': {'name': n, 'args': a}}
                    ts = tc.get('thought_signature') or tc.get('thoughtSignature')
                    if ts:
                        call_part['thoughtSignature'] = ts
                    parts.append(call_part)
                if parts:
                    contents.append({'role': 'model', 'parts': parts})
            elif role == 'tool':
                tname = msg.get('name')
                if not tname or tname == 'tool_result':
                    for prev_turn in reversed(contents):
                        if prev_turn.get('role') == 'model':
                            for prev_p in prev_turn.get('parts', []):
                                if 'functionCall' in prev_p:
                                    tname = prev_p['functionCall'].get('name')
                                    break
                            if tname:
                                break
                if not tname:
                    tname = 'tool_result'

                try:
                    tres = json.loads(content) if isinstance(content, str) else content
                except Exception:
                    tres = {'result': content}

                # Gemini REST API requires functionResponse to immediately follow a model functionCall turn.
                has_preceding_call = (
                    contents and contents[-1].get('role') == 'model' and 
                    any('functionCall' in p for p in contents[-1].get('parts', []))
                )
                if has_preceding_call:
                    contents.append({'role': 'user', 'parts': [{'functionResponse': {'name': tname, 'response': tres}}]})
                else:
                    contents.append({'role': 'user', 'parts': [{'text': f"System/Tool output: {content}"}]})
        # Merge consecutive same-role turns (Gemini requires alternating)
        cleaned = []
        for e in contents:
            if cleaned and cleaned[-1]['role'] == e['role']:
                cleaned[-1]['parts'].extend(e.get('parts', []))
            else:
                cleaned.append(e)
        if cleaned and cleaned[0]['role'] != 'user':
            cleaned.insert(0, {'role': 'user', 'parts': [{'text': 'Hello'}]})
        return sys_parts, cleaned

    def generate_response(self, messages, tools=None, options=None):
        options = options or {}
        base_url = (self.provider.base_url or self.DEFAULT_BASE_URL).rstrip('/')
        api_key = self.provider.get_decrypted_key()
        if not api_key:
            return ProviderResponse(error='Google Gemini API key is missing.')
        model = options.get('model') or self.provider.model_name or self.DEFAULT_MODEL
        url = '{}/models/{}:generateContent?key={}'.format(base_url, model, api_key)
        sys_parts, contents = self._build_contents(messages)
        max_out = options.get('max_tokens') or self.provider.max_tokens or 8192
        payload = {
            'contents': contents,
            'generationConfig': {
                'temperature': options.get('temperature', self.provider.temperature or 0.7),
                'maxOutputTokens': max_out,
            },
        }
        if sys_parts:
            payload['systemInstruction'] = {'parts': sys_parts}
        if tools:
            payload['tools'] = self.format_tools(tools)
            payload['toolConfig'] = {'functionCallingConfig': {'mode': 'AUTO'}}
        max_retries = self.provider.max_retries or 2
        start = time.time()
        for attempt in range(max_retries + 1):
            try:
                resp = requests.post(
                    url,
                    headers={'Content-Type': 'application/json'},
                    json=payload,
                    timeout=self.provider.timeout_seconds or 60,
                )
                ms = round((time.time() - start) * 1000, 2)
                if resp.status_code == 200:
                    data = resp.json()
                    tcs = self.parse_tool_calls(data)
                    text_parts = []
                    for c in (data.get('candidates') or []):
                        for p in (c.get('content', {}).get('parts') or []):
                            if 'text' in p:
                                text_parts.append(p['text'])
                    content_out = '\n'.join(text_parts)
                    if not content_out and not tcs:
                        fr = ((data.get('candidates') or [{}])[0]).get('finishReason', '')
                        content_out = 'Processed.' if fr in ('STOP', 'MAX_TOKENS') else '[Gemini empty. Reason: {}]'.format(fr or 'UNKNOWN')
                    um = data.get('usageMetadata', {})
                    pt = um.get('promptTokenCount', 0)
                    ct = um.get('candidatesTokenCount', 0)
                    return ProviderResponse(
                        content=content_out, tool_calls=tcs, raw_response=data,
                        prompt_tokens=pt, completion_tokens=ct, total_tokens=pt + ct,
                        model=model, duration_ms=ms,
                    )
                elif resp.status_code in (429, 503) and attempt < max_retries:
                    time.sleep((2 ** attempt) + 1.0)
                    continue
                else:
                    err_data = resp.json() if resp.text else {}
                    err = err_data.get('error', {}).get('message', 'HTTP {}'.format(resp.status_code))
                    return ProviderResponse(error='Gemini API Error: {}'.format(err), duration_ms=ms)
            except requests.exceptions.Timeout:
                if attempt < max_retries:
                    time.sleep(1)
                    continue
                return ProviderResponse(error='Gemini request timed out.', duration_ms=round((time.time() - start) * 1000, 2))
            except Exception as exc:
                return ProviderResponse(error='Gemini Error: {}'.format(exc), duration_ms=round((time.time() - start) * 1000, 2))
        return ProviderResponse(error='Failed after maximum retries.')
