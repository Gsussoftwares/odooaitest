# -*- coding: utf-8 -*-
# Part of GSUS AI. See LICENSE file for full copyright and licensing details.

import json
import logging
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class GsusAiMcpController(http.Controller):
    """Model Context Protocol (MCP) HTTP/JSON-RPC 2.0 Controller."""

    CORS_HEADERS = {
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Methods': 'POST, OPTIONS',
        'Access-Control-Allow-Headers': 'Authorization, Content-Type, Accept',
    }

    @http.route('/gsus_ai/mcp', type='http', auth='public', csrf=False, methods=['OPTIONS', 'POST'])
    def handle_mcp_endpoint(self, **kwargs):
        if request.httprequest.method == 'OPTIONS':
            return request.make_response('', headers=self.CORS_HEADERS)

        auth_header = request.httprequest.headers.get('Authorization', '')
        # Check authentication: session user or Bearer API key
        env = request.env
        if not env.user or env.user._is_public():
            token = ""
            if auth_header.startswith('Bearer '):
                token = auth_header.split('Bearer ', 1)[1].strip()

            if token:
                # Check api key in res.users.apikeys if available
                if 'res.users.apikeys' in env:
                    uid = env['res.users.apikeys']._check_credentials(scope='mcp', key=token)
                    if not uid:
                        uid = env['res.users.apikeys']._check_credentials(scope='rpc', key=token)
                    if uid:
                        env = env(user=uid)

            if not env.user or env.user._is_public():
                return request.make_json_response(
                    {
                        'jsonrpc': '2.0',
                        'id': None,
                        'error': {
                            'code': -32002,
                            'message': 'Unauthorized: Bearer token or valid session required.',
                        },
                    },
                    status=401,
                    headers=self.CORS_HEADERS,
                )

        # Parse JSON-RPC 2.0 payload
        try:
            payload = json.loads(request.httprequest.data.decode('utf-8'))
        except Exception:
            return request.make_json_response(
                {
                    'jsonrpc': '2.0',
                    'id': None,
                    'error': {'code': -32700, 'message': 'Parse error: Invalid JSON.'},
                },
                status=400,
                headers=self.CORS_HEADERS,
            )

        req_id = payload.get('id')
        try:
            result = env['gsus.ai.mcp.dispatcher'].dispatch_mcp_request(payload)
            response_data = {
                'jsonrpc': '2.0',
                'id': req_id,
                'result': result,
            }
            return request.make_json_response(response_data, headers=self.CORS_HEADERS)
        except Exception as e:
            _logger.exception("Error processing MCP request")
            error_data = {
                'jsonrpc': '2.0',
                'id': req_id,
                'error': {
                    'code': -32603,
                    'message': str(e),
                },
            }
            return request.make_json_response(error_data, status=500, headers=self.CORS_HEADERS)
