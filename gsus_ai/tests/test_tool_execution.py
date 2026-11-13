# -*- coding: utf-8 -*-
# Part of GSUS AI. See LICENSE file for full copyright and licensing details.

from odoo.tests.common import TransactionCase


class TestToolExecution(TransactionCase):

    def setUp(self):
        super().setUp()
        self.tool_stock = self.env['gsus.ai.tool'].search([('code', '=', 'stock_check_availability')], limit=1)
        self.partner = self.env['res.partner'].create({
            'name': 'GSUS Test Customer',
            'email': 'customer@gsus.test',
        })
        self.product = self.env['product.product'].create({
            'name': 'GSUS AI Software License',
            'list_price': 99.0,
            'sale_ok': True,
        })

    def test_01_stock_tool_execution(self):
        self.assertTrue(self.tool_stock)
        result = self.tool_stock.execute_tool({'product_name': 'GSUS AI Software'})
        self.assertIn('products', result)
        self.assertTrue(any(p['name'] == self.product.display_name for p in result['products']))

        # Verify audit log was created
        log = self.env['gsus.ai.audit.log'].search([('tool_code', '=', 'stock_check_availability')], limit=1)
        self.assertTrue(log)
        self.assertEqual(log.result_status, 'success')

    def test_02_use_in_ai_and_skill_toggle(self):
        # Create test skill and agent
        skill = self.env['gsus.ai.skill'].create({
            'name': 'Test Inventory Skill',
            'code': 'test_inventory_skill',
            'tool_ids': [(6, 0, [self.tool_stock.id])],
            'is_active': True,
        })
        agent = self.env['gsus.ai.agent'].create({
            'name': 'Test Agent',
            'code': 'test_agent',
            'role_description': 'Test',
            'system_prompt': 'Test',
            'skill_ids': [(6, 0, [skill.id])],
        })

        # When active and use_in_ai is True:
        self.tool_stock.use_in_ai = True
        effective_tools = agent.get_effective_tools()
        self.assertIn(self.tool_stock, effective_tools)

        # When tool use_in_ai is UNCHECKED:
        self.tool_stock.use_in_ai = False
        effective_tools = agent.get_effective_tools()
        self.assertNotIn(self.tool_stock, effective_tools)

        # Re-enable tool, but UNCHECK skill:
        self.tool_stock.use_in_ai = True
        skill.is_active = False
        effective_tools = agent.get_effective_tools()
        self.assertNotIn(self.tool_stock, effective_tools)

        # Re-enable skill:
        skill.is_active = True
        effective_tools = agent.get_effective_tools()
        self.assertIn(self.tool_stock, effective_tools)
