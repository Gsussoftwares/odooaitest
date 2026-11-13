# -*- coding: utf-8 -*-
# Part of GSUS AI. See LICENSE file for full copyright and licensing details.

import json
import logging
from odoo import models, api
from odoo.exceptions import AccessError, UserError

_logger = logging.getLogger(__name__)


class GsusAiMcpDispatcher(models.AbstractModel):
    _name = 'gsus.ai.mcp.dispatcher'
    _description = 'MCP JSON-RPC Protocol Dispatcher'

    @api.model
    def dispatch_mcp_request(self, payload: dict) -> dict:
        """Route incoming JSON-RPC 2.0 MCP request to appropriate handler."""
        method = payload.get('method')
        params = payload.get('params') or {}

        if method == 'initialize':
            return self._handle_initialize(params)
        elif method == 'notifications/initialized':
            return {}
        elif method == 'tools/list':
            return self._handle_tools_list(params)
        elif method == 'tools/call':
            return self._handle_tools_call(params)
        elif method == 'resources/list':
            return self._handle_resources_list(params)
        elif method == 'resources/read':
            return self._handle_resources_read(params)
        elif method == 'ping':
            return {}
        else:
            raise UserError(f"Unsupported MCP method: {method}")

    @api.model
    def _handle_initialize(self, params: dict) -> dict:
        return {
            'protocolVersion': '2024-11-05',
            'capabilities': {
                'tools': {'listChanged': False},
                'resources': {'subscribe': False, 'listChanged': False},
                'logging': {},
            },
            'serverInfo': {
                'name': 'GSUS AI MCP Server',
                'version': '20.0.1.0',
            },
            'instructions': (
                "GSUS AI Model Context Protocol Server for Odoo 20. "
                "Execute authorized Odoo business tools and retrieve permitted business records."
            ),
        }

    @api.model
    def _handle_tools_list(self, params: dict) -> dict:
        tools = []
        if 'gsus.ai.tool' in self.env:
            available_tools = self.env['gsus.ai.tool'].search([('is_active', '=', True)])
            for t in available_tools:
                tools.append({
                    'name': t.code or t.name,
                    'description': t.description or '',
                    'inputSchema': t.json_schema or {'type': 'object', 'properties': {}},
                })
        else:
            # Fallback baseline tools in bridge before main addon is loaded
            tools.append({
                'name': 'odoo_ping',
                'description': 'Check connection to Odoo server and retrieve user info.',
                'inputSchema': {'type': 'object', 'properties': {}},
            })
        return {'tools': tools}

    @api.model
    def _handle_tools_call(self, params: dict) -> dict:
        tool_name = params.get('name')
        arguments = params.get('arguments') or {}

        if tool_name == 'odoo_ping':
            user = self.env.user
            return {
                'content': [{
                    'type': 'text',
                    'text': json.dumps({
                        'status': 'ok',
                        'user': user.name,
                        'login': user.login,
                        'company': user.company_id.name,
                    }),
                }],
                'isError': False,
            }

        if 'gsus.ai.tool' in self.env:
            tool = self.env['gsus.ai.tool'].search([('code', '=', tool_name), ('is_active', '=', True)], limit=1)
            if not tool:
                return {
                    'content': [{'type': 'text', 'text': f"Tool '{tool_name}' not found or inactive."}],
                    'isError': True,
                }
            try:
                result = tool.execute_tool(arguments)
                return {
                    'content': [{'type': 'text', 'text': json.dumps(result, default=str)}],
                    'isError': False,
                }
            except Exception as e:
                _logger.exception("Error executing tool %s", tool_name)
                return {
                    'content': [{'type': 'text', 'text': f"Execution error: {str(e)}"}],
                    'isError': True,
                }

        return {
            'content': [{'type': 'text', 'text': f"Tool {tool_name} is not recognized."}],
            'isError': True,
        }

    @api.model
    def _handle_resources_list(self, params: dict) -> dict:
        resources = [
            {
                'uri': 'odoo://models/installed',
                'name': 'Installed Odoo Models',
                'description': 'List of accessible Odoo business models for the current user.',
                'mimeType': 'application/json',
            }
        ]
        return {'resources': resources}

    @api.model
    def _handle_resources_read(self, params: dict) -> dict:
        uri = params.get('uri', '')
        if uri == 'odoo://models/installed':
            # List permitted models
            models_data = self.env['ir.model'].search_read(
                [('transient', '=', False)],
                ['model', 'name'],
                limit=100,
            )
            return {
                'contents': [{
                    'uri': uri,
                    'mimeType': 'application/json',
                    'text': json.dumps(models_data),
                }]
            }
        raise UserError(f"Resource URI not found: {uri}")
