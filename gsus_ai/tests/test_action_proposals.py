# -*- coding: utf-8 -*-
# Part of GSUS AI. See LICENSE file for full copyright and licensing details.

import json
from odoo.tests.common import TransactionCase


class TestActionProposals(TransactionCase):

    def setUp(self):
        super().setUp()
        self.partner = self.env['res.partner'].create({
            'name': 'Proposal Test Partner',
            'email': 'partner@gsus.test',
        })
        self.provider = self.env['gsus.ai.provider'].create({
            'name': 'Test Provider',
            'provider_type': 'openai',
            'model_name': 'gpt-4o',
        })
        self.conv = self.env['gsus.ai.conversation'].create({
            'name': 'Proposal Test Chat',
            'provider_id': self.provider.id,
            'model_name': 'gpt-4o',
        })
        self.tool_activity = self.env['gsus.ai.tool'].search([('code', '=', 'calendar_schedule_activity')], limit=1)

    def test_01_proposal_approval_flow(self):
        proposal = self.env['gsus.ai.action.proposal'].create({
            'conversation_id': self.conv.id,
            'tool_id': self.tool_activity.id,
            'summary': 'Schedule Client Followup Call',
            'arguments_json': json.dumps({
                'res_model': 'res.partner',
                'res_id': self.partner.id,
                'summary': 'Followup on Proposal',
                'note': 'Discuss licensing terms',
            }),
            'state': 'pending',
        })

        self.assertEqual(proposal.state, 'pending')

        # Confirm proposal
        res = proposal.action_confirm()
        self.assertEqual(proposal.state, 'confirmed')
        self.assertIn('activity_id', proposal.execution_result)

        # Verify activity was created on res.partner
        activity = self.env['mail.activity'].search([
            ('res_model', '=', 'res.partner'),
            ('res_id', '=', self.partner.id),
            ('summary', '=', 'Followup on Proposal'),
        ], limit=1)
        self.assertTrue(activity)

    def test_02_proposal_rejection_flow(self):
        proposal = self.env['gsus.ai.action.proposal'].create({
            'conversation_id': self.conv.id,
            'tool_id': self.tool_activity.id,
            'summary': 'Rejected Meeting Activity',
            'arguments_json': json.dumps({
                'res_model': 'res.partner',
                'res_id': self.partner.id,
                'summary': 'Rejected Meeting Activity',
            }),
            'state': 'pending',
        })

        proposal.action_reject()
        self.assertEqual(proposal.state, 'rejected')

        activity = self.env['mail.activity'].search([
            ('res_model', '=', 'res.partner'),
            ('res_id', '=', self.partner.id),
            ('summary', '=', 'Rejected Meeting Activity'),
        ], limit=1)
        self.assertFalse(activity)
