# -*- coding: utf-8 -*-
# Part of GSUS AI. See LICENSE file for full copyright and licensing details.

from odoo.tests.common import TransactionCase


class TestMcpProtocol(TransactionCase):

    def setUp(self):
        super().setUp()
        self.dispatcher = self.env['gsus.ai.mcp.dispatcher']

    def test_01_mcp_initialize(self):
        payload = {
            'jsonrpc': '2.0',
            'id': 1,
            'method': 'initialize',
            'params': {
                'protocolVersion': '2024-11-05',
                'clientInfo': {'name': 'Antigravity IDE', 'version': '1.0'},
            }
        }
        res = self.dispatcher.dispatch_mcp_request(payload)
        self.assertEqual(res['protocolVersion'], '2024-11-05')
        self.assertEqual(res['serverInfo']['name'], 'GSUS AI MCP Server')
        self.assertIn('tools', res['capabilities'])

    def test_02_mcp_tools_list_and_ping(self):
        list_payload = {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'}
        list_res = self.dispatcher.dispatch_mcp_request(list_payload)
        self.assertIn('tools', list_res)

        call_payload = {
            'jsonrpc': '2.0',
            'id': 3,
            'method': 'tools/call',
            'params': {'name': 'odoo_ping', 'arguments': {}}
        }
        call_res = self.dispatcher.dispatch_mcp_request(call_payload)
        self.assertFalse(call_res['isError'])
        self.assertTrue(len(call_res['content']) > 0)
        self.assertIn('status', call_res['content'][0]['text'])
