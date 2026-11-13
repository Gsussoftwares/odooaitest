# -*- coding: utf-8 -*-
# Part of GSUS Bank AI. See LICENSE file for full copyright and licensing details.

from odoo import models, fields, api


class GsusBankAiMemory(models.Model):
    _name = 'gsus.bank.ai.memory'
    _description = 'Counterparty Semantic AI Memory'
    _order = 'confirmations desc, write_date desc'

    company_id = fields.Many2one('res.company', string='Company', required=True, default=lambda self: self.env.company, index=True)
    counterparty_key = fields.Char(string='Normalized Counterparty Key', required=True, index=True)
    direction = fields.Selection([('debit', 'Debit / Outflow'), ('credit', 'Credit / Inflow')], string='Direction', required=True, index=True)

    partner_id = fields.Many2one('res.partner', string='Mapped Contact')
    account_id = fields.Many2one('account.account', string='Mapped Ledger Account', required=True)
    confirmations = fields.Integer(string='Confirmation Count', default=1)
    last_used = fields.Datetime(string='Last Used', default=fields.Datetime.now)

    _sql_constraints = [
        ('key_dir_company_uniq', 'unique(counterparty_key, direction, company_id)',
         'A learned mapping for this counterparty and direction already exists for this company.')
    ]

    @api.model
    def record_confirmation(self, counterparty_key, direction, partner_id, account_id, company_id=None):
        """Learn or increment counterparty mapping from accountant review."""
        if not counterparty_key or not account_id:
            return False
        comp_id = company_id or self.env.company.id
        norm_key = counterparty_key.strip().upper()
        existing = self.search([
            ('counterparty_key', '=', norm_key),
            ('direction', '=', direction),
            ('company_id', '=', comp_id),
        ], limit=1)

        if existing:
            vals = {
                'confirmations': existing.confirmations + 1,
                'last_used': fields.Datetime.now(),
            }
            if account_id and existing.account_id.id != account_id:
                vals['account_id'] = account_id
            if partner_id:
                vals['partner_id'] = partner_id
            existing.write(vals)
            return existing
        else:
            return self.create({
                'counterparty_key': norm_key,
                'direction': direction,
                'partner_id': partner_id or False,
                'account_id': account_id,
                'company_id': comp_id,
                'confirmations': 1,
                'last_used': fields.Datetime.now(),
            })

