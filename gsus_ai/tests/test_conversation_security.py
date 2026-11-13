# -*- coding: utf-8 -*-
# Part of GSUS AI. See LICENSE file for full copyright and licensing details.

from odoo.tests.common import TransactionCase
from odoo.exceptions import AccessError


class TestConversationSecurity(TransactionCase):

    def setUp(self):
        super().setUp()
        self.user_a = self.env['res.users'].create({
            'name': 'User A',
            'login': 'user_a@gsus.test',
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id, self.env.ref('gsus_ai.group_gsus_ai_user').id])],
        })
        self.user_b = self.env['res.users'].create({
            'name': 'User B',
            'login': 'user_b@gsus.test',
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id, self.env.ref('gsus_ai.group_gsus_ai_user').id])],
        })
        self.provider = self.env['gsus.ai.provider'].create({
            'name': 'Test Provider',
            'provider_type': 'openai',
            'model_name': 'gpt-4o',
        })

    def test_01_conversation_privacy_isolation(self):
        # User A creates a conversation
        conv_a = self.env['gsus.ai.conversation'].with_user(self.user_a).create({
            'name': 'Private Secrets of User A',
            'provider_id': self.provider.id,
            'model_name': 'gpt-4o',
        })

        # User A can read it
        self.assertTrue(conv_a.with_user(self.user_a).read(['name']))

        # User B searches conversations: conv_a should not appear in search
        user_b_convs = self.env['gsus.ai.conversation'].with_user(self.user_b).search([('id', '=', conv_a.id)])
        self.assertEqual(len(user_b_convs), 0)

        # User B trying direct access should raise AccessError
        with self.assertRaises(AccessError):
            conv_a.with_user(self.user_b).read(['name'])
