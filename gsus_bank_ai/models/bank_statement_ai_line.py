# -*- coding: utf-8 -*-
# Part of GSUS Bank AI. See LICENSE file for full copyright and licensing details.

import re
from odoo import models, fields, api, _

class GsusBankStatementAiLine(models.Model):
    _name = 'gsus.bank.statement.ai.line'
    _description = 'Bank Statement Staged Transaction Line'
    _order = 'date asc, sequence asc, id asc'

    statement_id = fields.Many2one('gsus.bank.statement.ai', string='Statement Batch', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='statement_id.company_id', string='Company', store=True, index=True)
    currency_id = fields.Many2one(related='statement_id.currency_id', string='Currency')
    sequence = fields.Integer(string='Sequence', default=10)

    date = fields.Date(string='Date', required=True, index=True)
    narration = fields.Text(string='Narration / Description', required=True)
    reference = fields.Char(string='Reference / UTR / Txn ID')

    payment_mode = fields.Selection([
        ('upi', 'UPI'),
        ('imps', 'IMPS'),
        ('neft', 'NEFT'),
        ('rtgs', 'RTGS'),
        ('nach', 'NACH / Mandate'),
        ('atm', 'ATM'),
        ('pos', 'POS / Card'),
        ('cheque', 'Cheque'),
        ('charge', 'Bank Charge'),
        ('transfer', 'Transfer'),
        ('other', 'Other'),
    ], string='Mode', compute='_compute_payment_mode', store=True)

    debit = fields.Float(string='Debit (Outflow)', digits='Product Price', default=0.0)
    credit = fields.Float(string='Credit (Inflow)', digits='Product Price', default=0.0)
    balance = fields.Float(string='Running Balance', digits='Product Price')
    amount = fields.Float(string='Amount', compute='_compute_amount', store=True)
    row_verified = fields.Boolean(string='Math Verified', default=False)

    # Counterparty & AI Clustering
    counterparty = fields.Char(string='Clean Counterparty', index=True)
    counterparty_handle = fields.Char(string='Handle / VPA / Account')
    fingerprint = fields.Char(string='Line Fingerprint', index=True)

    # ─── Intelligent Classification & Approval Fields ────────────────
    transaction_type = fields.Selection([
        ('customer_payment', 'Customer Payment'),
        ('vendor_payment', 'Vendor Payment'),
        ('bank_charges', 'Bank Charges'),
        ('bank_interest', 'Bank Interest'),
        ('internal_transfer', 'Internal Transfer'),
        ('loan_transaction', 'Loan Transaction'),
        ('refund', 'Refund'),
        ('other_expense', 'Other Expense'),
        ('other_income', 'Other Income'),
        ('unknown', 'Unknown / Needs Review'),
    ], string='Transaction Category', default='unknown', index=True)

    counterparty_type = fields.Selection([
        ('customer', 'Customer'),
        ('vendor', 'Vendor'),
        ('bank', 'Bank / Financial Institution'),
        ('internal', 'Internal Account'),
        ('none', 'No Counterparty'),
    ], string='Counterparty Role', default='none')

    contact_status = fields.Selection([
        ('existing', 'Existing Contact'),
        ('new_proposed', 'New Contact Proposed'),
        ('no_contact_needed', 'No Contact Required'),
        ('needs_review', 'Needs Review'),
        ('approved', 'Approved for Creation'),
        ('rejected', 'Rejected Contact'),
    ], string='Contact Resolution Status', default='needs_review', index=True)

    approval_target = fields.Selection([
        ('customer', 'Approve as Customer'),
        ('vendor', 'Approve as Vendor'),
        ('none', 'No Contact'),
    ], string='Approval Target Type', default='none')

    proposed_contact_name = fields.Char(string='Proposed Contact Name')
    proposed_upi_id = fields.Char(string='Proposed UPI / VPA ID')
    proposed_bank_account = fields.Char(string='Proposed Bank Account')
    classification_confidence = fields.Float(string='Classification Match %', default=0.0)
    classification_reason = fields.Char(string='Classification Reason')

    contact_approved_by = fields.Many2one('res.users', string='Approved By', readonly=True)
    contact_approved_date = fields.Datetime(string='Approved Date', readonly=True)

    # Accounting Mapping
    partner_id = fields.Many2one('res.partner', string='Assigned Contact / Partner')
    new_contact_name = fields.Char(string='Proposed Contact Name (Legacy)')
    account_id = fields.Many2one('account.account', string='Assigned Ledger / Account')
    matched_invoice_id = fields.Many2one('account.move', string='Matched Open Invoice')
    native_statement_line_id = fields.Many2one('account.bank.statement.line', string='Odoo Statement Line', ondelete='set null')

    # Intelligence Metadata
    confidence = fields.Float(string='Confidence', default=0.0, help='AI matching confidence from 0.0 to 1.0')
    confidence_percent = fields.Integer(string='Match %', compute='_compute_confidence_percent')
    suggestion_source = fields.Selection([
        ('rule', 'Learned Rule'),
        ('memory', 'Historical Confirmation'),
        ('fuzzy', 'Exact / Fuzzy Match'),
        ('ai', 'Gemini Multimodal Reasoning'),
        ('manual', 'Accountant Input'),
    ], string='Source', default='fuzzy')
    ai_reason = fields.Char(string='AI Reasoning Hint')

    status = fields.Selection([
        ('pending', 'Not Assigned'),
        ('suggested', 'AI Suggested'),
        ('reviewed', 'Reviewed'),
        ('pushed', 'Pushed to Odoo'),
    ], string='Status', default='pending', required=True, index=True)

    group_key = fields.Char(string='Group Key', compute='_compute_group_key', store=True, index=True)
    group_remark = fields.Char(string='Group Remark')
    user_remarks = fields.Char(string='Remarks')
    is_duplicate = fields.Boolean(string='Potential Duplicate', default=False)
    is_anomaly = fields.Boolean(string='Anomaly Flag', default=False)
    anomaly_reason = fields.Char(string='Anomaly Reason')

    @api.depends('debit', 'credit')
    def _compute_amount(self):
        for line in self:
            line.amount = line.debit if line.debit > 0 else line.credit

    @api.depends('confidence')
    def _compute_confidence_percent(self):
        for line in self:
            line.confidence_percent = int(round((line.confidence or 0.0) * 100))

    @api.depends('narration')
    def _compute_payment_mode(self):
        for line in self:
            text = (line.narration or '').upper()
            if 'UPI' in text:
                line.payment_mode = 'upi'
            elif 'IMPS' in text:
                line.payment_mode = 'imps'
            elif 'NEFT' in text:
                line.payment_mode = 'neft'
            elif 'RTGS' in text:
                line.payment_mode = 'rtgs'
            elif 'NACH' in text or 'ACH' in text or 'MANDATE' in text or 'ECS' in text or 'PFN' in text:
                line.payment_mode = 'nach'
            elif 'ATM' in text or 'NWD' in text or 'CASH WDL' in text or 'WDL' in text or 'CWDR' in text:
                line.payment_mode = 'atm'
            elif 'POS' in text or 'ECOM' in text or 'SWIPE' in text or 'DEBIT CARD' in text or 'CARD' in text:
                line.payment_mode = 'pos'
            elif 'CHQ' in text or 'CHEQUE' in text or 'CLG' in text:
                line.payment_mode = 'cheque'
            elif 'CHG' in text or 'CHARGE' in text or 'FEE' in text or 'TAX' in text:
                line.payment_mode = 'charge'
            elif 'TPFT' in text or 'TRANSFER' in text or 'INB' in text:
                line.payment_mode = 'transfer'
            else:
                line.payment_mode = 'other'

    @api.depends('narration', 'payment_mode', 'proposed_contact_name', 'counterparty')
    def _compute_group_key(self):
        BANK_IFSC = {
            'YESB', 'TMBL', 'UTIB', 'FDRL', 'SBIN', 'ICIC', 'HDFC', 'KKBK',
            'BARB', 'PUNB', 'CNRB', 'IOBA', 'IDIB', 'UBIN', 'CBIN', 'VIJB',
            'CORP', 'ALLA', 'ANDB', 'SYNB', 'MAHB', 'PSIB', 'BDBL', 'IDFB',
            'PAYTM', 'PYTM', 'AIRP', 'JIOP', 'IPOS', 'CITI', 'HSBC', 'SCBL'
        }
        for line in self:
            c_name = line.proposed_contact_name or line.counterparty
            if c_name and c_name.strip().upper() in BANK_IFSC:
                c_name = False
            if not c_name and line.narration:
                if 'gsus.bank.ai.matcher' in self.env:
                    c_name = self.env['gsus.bank.ai.matcher'].sudo().extract_clean_counterparty(line.narration)
            if c_name and len(c_name.strip()) >= 3 and c_name.strip().upper() not in BANK_IFSC:
                line.group_key = c_name.strip().upper()
                continue
            text = (line.narration or '').strip()
            cleaned = re.sub(r'[0-9]+', '', text)
            tokens = [t for t in re.split(r'[/_\-\s]+', cleaned) if len(t) >= 4 and t.upper() not in BANK_IFSC and t.upper() not in ('UPI', 'UFI', 'PAYMENT', 'TRANSFER')]
            line.group_key = " ".join(tokens[:3]).strip().upper() or 'GENERAL'

    # ─── Accountant Approval Action Methods ──────────────────────────
    def action_approve_as_customer(self):
        """Accountant explicitly approves the proposed contact as a Customer."""
        now = fields.Datetime.now()
        for line in self:
            name = line.proposed_contact_name or line.new_contact_name or line.counterparty
            line.write({
                'contact_status': 'approved',
                'approval_target': 'customer',
                'counterparty_type': 'customer',
                'transaction_type': 'customer_payment' if line.transaction_type in ('unknown', 'other_income') else line.transaction_type,
                'proposed_contact_name': name,
                'contact_approved_by': self.env.user.id,
                'contact_approved_date': now,
                'status': 'reviewed',
            })
        return True

    def action_approve_as_vendor(self):
        """Accountant explicitly approves the proposed contact as a Vendor."""
        now = fields.Datetime.now()
        for line in self:
            name = line.proposed_contact_name or line.new_contact_name or line.counterparty
            line.write({
                'contact_status': 'approved',
                'approval_target': 'vendor',
                'counterparty_type': 'vendor',
                'transaction_type': 'vendor_payment' if line.transaction_type in ('unknown', 'other_expense') else line.transaction_type,
                'proposed_contact_name': name,
                'contact_approved_by': self.env.user.id,
                'contact_approved_date': now,
                'status': 'reviewed',
            })
        return True

    def action_mark_no_contact(self):
        """Accountant explicitly marks line as No Contact Required (bank fee, transfer, etc.)."""
        for line in self:
            line.write({
                'contact_status': 'no_contact_needed',
                'approval_target': 'none',
                'partner_id': False,
                'status': 'reviewed',
            })
        return True

    def action_reject_contact(self):
        """Accountant explicitly rejects proposed contact."""
        for line in self:
            line.write({
                'contact_status': 'rejected',
                'approval_target': 'none',
                'partner_id': False,
            })
        return True

    def action_change_category(self, new_type):
        """Accountant changes transaction category."""
        valid_types = dict(self._fields['transaction_type'].selection)
        if new_type in valid_types:
            for line in self:
                vals = {'transaction_type': new_type}
                if new_type in ('bank_charges', 'bank_interest', 'internal_transfer'):
                    vals['contact_status'] = 'no_contact_needed'
                    vals['counterparty_type'] = 'none'
                elif new_type == 'customer_payment':
                    vals['counterparty_type'] = 'customer'
                elif new_type == 'vendor_payment':
                    vals['counterparty_type'] = 'vendor'
                line.write(vals)
        return True

    def action_mark_reviewed(self):
        for line in self:
            if line.account_id or line.partner_id or line.contact_status in ('approved', 'no_contact_needed'):
                line.status = 'reviewed'

    def action_quick_assign(self, partner_id=False, account_id=False):
        vals = {'status': 'reviewed', 'confidence': 1.0}
        if partner_id:
            vals['partner_id'] = partner_id
            vals['contact_status'] = 'existing'
        if account_id:
            vals['account_id'] = account_id
        self.write(vals)
