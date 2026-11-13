# -*- coding: utf-8 -*-
# Part of GSUS Bank AI. See LICENSE file for full copyright and licensing details.

from odoo import models, fields, api


class GsusBankAiRule(models.Model):
    _name = 'gsus.bank.ai.rule'
    _description = 'GSUS Bank Statement AI Matching Rule'
    _order = 'sequence, id'

    name = fields.Char(string='Rule Name', required=True)
    company_id = fields.Many2one('res.company', string='Company', required=True, default=lambda self: self.env.company, index=True)
    sequence = fields.Integer(string='Sequence', default=10)
    priority = fields.Integer(string='Priority', default=10)
    is_active = fields.Boolean(string='Active', default=True)

    direction = fields.Selection([
        ('both', 'Both (Debit & Credit)'),
        ('debit', 'Debit Only (Outflow)'),
        ('credit', 'Credit Only (Inflow)'),
    ], string='Direction', default='both', required=True)

    match_type = fields.Selection([
        ('contains', 'Narration Contains Keyword'),
        ('exact', 'Exact Keyword Match'),
        ('regex', 'Regular Expression'),
    ], string='Match Type', default='contains', required=True)

    keyword = fields.Char(string='Keyword / Pattern', required=True, help='e.g. SWIGGY, ZOMATO, SALARY, PETROL')
    partner_id = fields.Many2one('res.partner', string='Assign Partner / Contact')
    account_id = fields.Many2one('account.account', string='Assign Ledger / Account', required=True)

    min_amount = fields.Float(string='Minimum Amount', default=0.0)
    max_amount = fields.Float(string='Maximum Amount', default=0.0, help='0.0 means no upper limit')

    learned_from_chat = fields.Boolean(string='Learned from AI Chat', default=False, readonly=True)
    total_matched_count = fields.Integer(string='Matches Applied', default=0, readonly=True)

    def apply_to_narration(self, narration: str, amount: float, direction: str = 'debit') -> bool:
        if not self.is_active or not narration:
            return False

        if self.direction != 'both' and self.direction != direction:
            return False

        narr_upper = narration.upper()
        key_upper = self.keyword.upper()

        if self.min_amount > 0 and amount < self.min_amount:
            return False
        if self.max_amount > 0 and amount > self.max_amount:
            return False

        if self.match_type == 'contains':
            return key_upper in narr_upper
        elif self.match_type == 'exact':
            return key_upper == narr_upper
        elif self.match_type == 'regex':
            import re
            return bool(re.search(self.keyword, narration, re.IGNORECASE))
        return False
