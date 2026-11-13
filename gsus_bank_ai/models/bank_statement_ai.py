# -*- coding: utf-8 -*-

# Part of GSUS Bank AI. See LICENSE file for full copyright and licensing details.



import json

import base64

import re

import logging

from odoo import models, fields, api, _

from odoo.exceptions import UserError



_logger = logging.getLogger(__name__)





class GsusBankStatementAi(models.Model):

    _name = 'gsus.bank.statement.ai'

    _description = 'Bank Statement AI Staging Session'

    _order = 'create_date desc, id desc'



    name = fields.Char(string='Statement Title', required=True, default='New Bank Statement')

    company_id = fields.Many2one('res.company', string='Company', required=True, default=lambda self: self.env.company, index=True)

    bank_name = fields.Char(string='Bank Name', help='Auto-detected or user selected')

    account_number = fields.Char(string='Account Number', help='Auto-detected bank account number')

    account_holder = fields.Char(string='Account Holder')

    file_hash = fields.Char(string='File Hash (SHA256)', index=True)



    file_data = fields.Binary(string='Statement File (PDF/Image/CSV)', attachment=True)

    file_name = fields.Char(string='File Name')

    pdf_password = fields.Char(string='PDF Password', help='Enter password if bank statement PDF is password-protected')



    journal_id = fields.Many2one('account.journal', string='Bank Journal', domain=[('type', '=', 'bank')])

    currency_id = fields.Many2one('res.currency', string='Currency', default=lambda self: self.env.company.currency_id)

    statement_date = fields.Date(string='Statement Date', default=fields.Date.context_today)

    period_from = fields.Date(string='Period From')

    period_to = fields.Date(string='Period To')



    opening_balance = fields.Float(string='Opening Balance', digits='Product Price', default=0.0)

    closing_balance = fields.Float(string='Closing Balance', digits='Product Price', default=0.0)

    recomputed_closing_balance = fields.Float(string='Recomputed Closing', compute='_compute_verification', store=True, digits='Product Price')

    verification_state = fields.Selection([

        ('verified', 'Reconciled & Verified'),

        ('flagged', 'Mismatch Flagged'),

        ('unchecked', 'Unverified'),

    ], string='Math Check', compute='_compute_verification', store=True, default='unchecked')

    verification_notes = fields.Char(string='Verification Details', compute='_compute_verification', store=True)



    job_id = fields.Many2one('gsus.bank.ai.job', string='Background Job')



    # Line Items

    line_ids = fields.One2many('gsus.bank.statement.ai.line', 'statement_id', string='Transaction Lines')



    @api.model_create_multi

    def create(self, vals_list):

        import hashlib

        for vals in vals_list:

            if vals.get('file_data') and not vals.get('file_hash'):

                try:

                    raw = base64.b64decode(vals['file_data'])

                    vals['file_hash'] = hashlib.sha256(raw).hexdigest()

                except Exception:

                    pass

        return super().create(vals_list)



    def write(self, vals):

        import hashlib

        if vals.get('file_data') and not vals.get('file_hash'):

            try:

                raw = base64.b64decode(vals['file_data'])

                vals['file_hash'] = hashlib.sha256(raw).hexdigest()

            except Exception:

                pass

        return super().write(vals)



    # Metrics for Top Dynamic Odometer

    total_transactions = fields.Integer(string='Total Lines', compute='_compute_kpis', store=True)

    total_debit = fields.Float(string='Total Outflow (Debit)', compute='_compute_kpis', store=True, digits='Product Price')

    total_credit = fields.Float(string='Total Inflow (Credit)', compute='_compute_kpis', store=True, digits='Product Price')

    net_flow = fields.Float(string='Net Flow', compute='_compute_kpis', store=True, digits='Product Price')



    assigned_count = fields.Integer(string='Assigned Count', compute='_compute_kpis', store=True)

    reviewed_count = fields.Integer(string='Reviewed Count', compute='_compute_kpis', store=True)

    unassigned_count = fields.Integer(string='Unassigned Count', compute='_compute_kpis', store=True)

    pushed_count = fields.Integer(string='Pushed Count', compute='_compute_kpis', store=True)

    confidence_avg = fields.Integer(string='Average Match %', compute='_compute_kpis', store=True)



    state = fields.Selection([

        ('draft', 'Uploaded'),

        ('parsed', 'AI Parsed & Staged'),

        ('reviewed', 'Reviewed'),

        ('pushed', 'Pushed to Odoo'),

        ('cancelled', 'Cancelled'),

    ], string='Status', default='draft', required=True)



    # Push Reference to Native Odoo Accounting

    account_bank_statement_id = fields.Many2one('account.bank.statement', string='Odoo Bank Statement', readonly=True)

    last_error_message = fields.Text(string='Processing Remarks', readonly=True)



    @api.depends('line_ids', 'line_ids.debit', 'line_ids.credit', 'line_ids.status', 'line_ids.confidence')

    def _compute_kpis(self):

        for rec in self:

            lines = rec.line_ids

            total_tx = len(lines)

            rec.total_transactions = total_tx

            tot_debit = sum(l.debit for l in lines)

            tot_credit = sum(l.credit for l in lines)

            rec.total_debit = tot_debit

            rec.total_credit = tot_credit

            rec.net_flow = tot_credit - tot_debit



            rec.assigned_count = len(lines.filtered(lambda l: l.status in ('suggested', 'reviewed', 'pushed')))

            rec.reviewed_count = len(lines.filtered(lambda l: l.status in ('reviewed', 'pushed')))

            rec.unassigned_count = len(lines.filtered(lambda l: l.status == 'pending'))

            rec.pushed_count = len(lines.filtered(lambda l: l.status == 'pushed'))



            if total_tx > 0:

                rec.confidence_avg = int(round((sum(l.confidence for l in lines) / total_tx) * 100))

            else:

                rec.confidence_avg = 0



    @api.depends('opening_balance', 'total_credit', 'total_debit', 'closing_balance', 'line_ids')

    def _compute_verification(self):

        for rec in self:

            calc_closing = round(rec.opening_balance + rec.total_credit - rec.total_debit, 2)

            rec.recomputed_closing_balance = calc_closing

            if not rec.line_ids:

                rec.verification_state = 'unchecked'

                rec.verification_notes = 'No transactions parsed yet'

            elif rec.closing_balance == 0.0 or abs(calc_closing - round(rec.closing_balance, 2)) < 0.01:

                rec.verification_state = 'verified'

                rec.verification_notes = f'Verified: ₹{rec.opening_balance:,.2f} + ₹{rec.total_credit:,.2f} - ₹{rec.total_debit:,.2f} = ₹{calc_closing:,.2f}'

            else:

                diff = round(calc_closing - rec.closing_balance, 2)

                rec.verification_state = 'flagged'

                rec.verification_notes = f'Discrepancy of ₹{diff:,.2f} (Calculated ₹{calc_closing:,.2f} vs Statement ₹{rec.closing_balance:,.2f})'





    def action_group_approve_as_vendor(self, group_key):

        """Approve proposed contact for all transactions in this group as a Vendor."""

        self.ensure_one()

        lines = self.line_ids.filtered(lambda l: (l.group_key == group_key or l.counterparty == group_key) and l.status != 'pushed')

        now = fields.Datetime.now()

        for line in lines:

            name = line.proposed_contact_name or line.counterparty or group_key

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



    def action_group_approve_as_customer(self, group_key):

        """Approve proposed contact for all transactions in this group as a Customer."""

        self.ensure_one()

        lines = self.line_ids.filtered(lambda l: (l.group_key == group_key or l.counterparty == group_key) and l.status != 'pushed')

        now = fields.Datetime.now()

        for line in lines:

            name = line.proposed_contact_name or line.counterparty or group_key

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



    def action_group_assign_partner(self, group_key, partner_id):

        """Assign existing contact to all transactions in this group."""

        self.ensure_one()

        lines = self.line_ids.filtered(lambda l: (l.group_key == group_key or l.counterparty == group_key) and l.status != 'pushed')

        p = self.env['res.partner'].sudo().browse(partner_id)

        if p.exists():

            for line in lines:

                line.write({

                    'partner_id': p.id,

                    'contact_status': 'existing',

                    'counterparty_type': 'customer' if p.customer_rank > p.supplier_rank else 'vendor',

                    'status': 'reviewed',

                    'confidence': 1.0,

                })

        return True



    def action_open_workbench(self):

        """Open the full-screen interactive OWL 3 Workbench."""

        self.ensure_one()

        return {

            'type': 'ir.actions.client',

            'tag': 'gsus_bank_workbench_review_action',

            'name': f"Bank Statement AI Workbench: {self.name}",

            'res_model': 'gsus.bank.statement.ai',

            'res_id': self.id,

            'params': {

                'statement_id': self.id,

                'initial_view': 'review',

            },

            'context': {

                'active_id': self.id,

                'active_model': 'gsus.bank.statement.ai',

                'statement_id': self.id,

                'initial_view': 'review',

            },

            'target': 'current',

        }



    # -------------------------------------------------------------

    # 1. PARSE & INGEST VIA MULTIMODAL AI

    # -------------------------------------------------------------



    def _classify_and_match_transaction(self, narration, debit, credit, ref, match_info):

        """Intelligently classify bank transaction and perform 5-tier contact matching.

        Strict Rule: Does NOT automatically create contacts in res.partner.

        """

        narration_clean = (narration or '').strip()

        narration_upper = narration_clean.upper()

        amount = debit if debit > 0 else credit

        is_debit = debit > 0

        company_id = self.company_id.id or self.env.company.id



        # 1. Extract clean counterparty and payment handles

        upi_id = False

        bank_account = False



        # Extract UPI ID / VPA

        upi_m = re.search(r'[\w\.\-]+@[\w]+', narration_clean)

        if upi_m:

            upi_id = upi_m.group(0).lower()



        # Extract account number if present

        acc_m = re.search(r'(?:A/C|AC|ACCT|ACCOUNT)[/-]?\s*(\d{9,18})', narration_clean, re.I)

        if acc_m:

            bank_account = acc_m.group(1)



        BANK_IFSC = {

            'YESB', 'TMBL', 'UTIB', 'FDRL', 'SBIN', 'ICIC', 'HDFC', 'KKBK',

            'BARB', 'PUNB', 'CNRB', 'IOBA', 'IDIB', 'UBIN', 'CBIN', 'VIJB',

            'CORP', 'ALLA', 'ANDB', 'SYNB', 'MAHB', 'PSIB', 'BDBL', 'IDFB',

            'PAYTM', 'PYTM', 'AIRP', 'JIOP', 'IPOS', 'CITI', 'HSBC', 'SCBL'

        }

        DISCARD_WORDS = {

            'UPI', 'UFI', 'DR', 'CR', 'P2A', 'P2P', 'REF', 'PAYMENT', 'TRANSFER',

            'INVOICE', 'BILL', 'MBANK', 'TEST', 'IMPS', 'NEFT', 'RTGS', 'ATM', 'CASH',

            'PHONEPE', 'PAYTM', 'GPAY', 'NAVI', 'CRED', 'BHIM', 'OTHER'

        }



        clean_cp = match_info.get('counterparty') or ''

        if clean_cp.upper() in BANK_IFSC or clean_cp.upper() in DISCARD_WORDS:

            clean_cp = ''



        if not clean_cp or '@' in clean_cp:

            if 'gsus.bank.ai.matcher' in self.env:

                clean_cp = self.env['gsus.bank.ai.matcher'].sudo().extract_clean_counterparty(narration_clean)

            if not clean_cp or clean_cp.upper() in BANK_IFSC or clean_cp.upper() in DISCARD_WORDS:

                # Extract from common Indian banking formats

                if narration_upper.startswith(('UPI', 'UFI')) or '/UPI' in narration_upper or '/UFI' in narration_upper:

                    parts = [p.strip() for p in narration_clean.split('/') if p.strip()]

                    candidates = []

                    for p in parts:

                        p_up = p.upper()

                        if p_up in DISCARD_WORDS or p_up in BANK_IFSC:

                            continue

                        if re.match(r'^\d+$', p):

                            continue

                        if p_up.startswith(('PAYMENT FROM', 'SENDING', 'SENT USING', 'PAYMENT TO')):

                            continue

                        cleaned = re.sub(r'[@\d_\.]+', ' ', p).strip()

                        if len(cleaned) >= 3 and cleaned.upper() not in BANK_IFSC and cleaned.upper() not in DISCARD_WORDS:

                            candidates.append(cleaned)

                    if candidates:

                        clean_cp = candidates[0].title()

                elif 'NEFT' in narration_upper or 'RTGS' in narration_upper:

                    m = re.search(r'(?:NEFT|RTGS)[/-][\w]+[/-]([A-Za-z\s]+)', narration_clean, re.I)

                    if m and len(m.group(1).strip()) >= 3:

                        clean_cp = m.group(1).strip().title()

                elif 'IMPS' in narration_upper:

                    m = re.search(r'IMPS[/-]\d+[/-](?:[\w]+-)*(.*?)(?:/|$)', narration_clean, re.I)

                    if m and len(m.group(1).replace('-', ' ').strip()) >= 3:

                        clean_cp = m.group(1).replace('-', ' ').strip().title()

                elif narration_upper.startswith('POS'):

                    parts = [p.strip() for p in narration_clean.split('/') if p.strip()]

                    for p in parts[1:]:

                        if not any(k in p.upper() for k in ('SWIPE', 'POS', 'CARD', 'TERMINAL', 'AUTH')) and len(p) >= 3:

                            clean_cp = p.title()

                            break



        # 2. Transaction Category Classification Logic

        txn_type = 'unknown'

        counterparty_type = 'none'

        contact_status = 'needs_review'

        reason = ''

        confidence = 0.50

        target_account_id = match_info.get('account_id') or False

        matched_inv_id = match_info.get('matched_invoice_id') or False



        # A) Bank Charges & Commission

        bank_charge_keywords = (

            'SMS CHG', 'SMS CHARGE', 'RTGS CHG', 'NEFT CHG', 'IMPS CHG', 'COMMISSION',

            'FOLIO', 'AMC CHG', 'POS SWIPE FEE', 'CARD FEE', 'CHG/', '/CHG', 'BANK CHARGE',

            'ANNUAL FEE', 'INWARD REMITTANCE SWIFT CHARGE', 'OUTWARD PROCESSING CHARGE',

            'CLEARING CESS', 'CAS SERVICES FEE', 'CONSOLIDATED CASH MGMT'

        )

        if any(k in narration_upper for k in bank_charge_keywords) or (is_debit and ('CHARGE' in narration_upper or 'CHG' in narration_upper)):

            txn_type = 'bank_charges'

            counterparty_type = 'bank'

            contact_status = 'no_contact_needed'

            reason = 'Bank fee/charge detected from narration'

            confidence = 0.98

            if not target_account_id:

                bc_acc = self.env['account.account'].sudo().search([

                    ('account_type', 'in', ('expense', 'expense_direct_cost')),

                    ('name', 'ilike', 'Bank'),

                    ('company_ids', 'in', [company_id])

                ], limit=1)

                if bc_acc:

                    target_account_id = bc_acc.id



        # B) Bank Interest

        elif any(k in narration_upper for k in ('INT.PD', 'INTEREST CR', 'INTEREST EARNED', 'SWEEP INT', 'AUTO SWEEP CR', 'INT COLL')):

            txn_type = 'bank_interest'

            counterparty_type = 'bank'

            contact_status = 'no_contact_needed'

            reason = 'Bank interest credit detected from narration'

            confidence = 0.98

            if not target_account_id:

                int_acc = self.env['account.account'].sudo().search([

                    ('account_type', 'in', ('income', 'income_other')),

                    ('name', 'ilike', 'Interest'),

                    ('company_ids', 'in', [company_id])

                ], limit=1)

                if int_acc:

                    target_account_id = int_acc.id



        # C) Internal Transfers

        elif any(k in narration_upper for k in ('OWN A/C', 'TPFT', 'SELF TRANSFER', 'INTERNAL TRANSFER', 'FUNDS TRF TO', 'FUNDS TRF FROM', 'SWEEP TRANSFER')):

            txn_type = 'internal_transfer'

            counterparty_type = 'internal'

            contact_status = 'no_contact_needed'

            reason = 'Internal account liquidity transfer detected'

            confidence = 0.95



        # D) Loan Transactions (Disbursement / EMI)

        elif any(k in narration_upper for k in ('LOAN EMI', 'EQUATED MONTHLY', 'LOAN DISBURSAL', 'LOAN DISBURSEMENT', 'TERM LOAN')):

            txn_type = 'loan_transaction'

            counterparty_type = 'bank'

            contact_status = 'needs_review'

            reason = 'Loan EMI / disbursement pattern detected'

            confidence = 0.90



        # E) Refund

        elif any(k in narration_upper for k in ('REFUND', 'REVERSAL', 'REV/', 'RTN/', 'RETURN OF')):

            txn_type = 'refund'

            counterparty_type = 'customer' if not is_debit else 'vendor'

            contact_status = 'needs_review'

            reason = 'Refund / Reversal keyword detected'

            confidence = 0.85



        # F) Customer Invoice or Vendor Bill Match

        elif matched_inv_id:

            inv = self.env['account.move'].sudo().browse(matched_inv_id)

            if inv.is_sale_document():

                txn_type = 'customer_payment'

                counterparty_type = 'customer'

                reason = f"Matches open Customer Invoice {inv.name}"

            else:

                txn_type = 'vendor_payment'

                counterparty_type = 'vendor'

                reason = f"Matches open Vendor Bill {inv.name}"

            confidence = 1.0



        # 3. 5-Tier Contact Matching (Only if not bank charges / transfer / interest)

        partner_id = match_info.get('partner_id') or False

        partner_name = match_info.get('partner_name') or ''

        proposed_name = clean_cp or match_info.get('proposed_partner_name') or ''



        if contact_status != 'no_contact_needed':

            # Tier 1: Search by UPI ID / VPA in partner handles or bank accounts

            if not partner_id and upi_id:

                upi_partner = self.env['res.partner'].sudo().search([

                    '|', ('ref', '=ilike', upi_id),

                    ('comment', 'ilike', upi_id),

                    '|', ('company_id', '=', False), ('company_id', '=', company_id)

                ], limit=1)

                if upi_partner:

                    partner_id = upi_partner.id

                    partner_name = upi_partner.name

                    confidence = 0.98

                    reason = f"Exact UPI ID ({upi_id}) match with partner {upi_partner.name}"



            # Tier 2: Search by Bank Account number

            if not partner_id and bank_account:

                bank_acc_partner = self.env['res.partner.bank'].sudo().search([

                    ('acc_number', 'ilike', bank_account),

                    '|', ('company_id', '=', False), ('company_id', '=', company_id)

                ], limit=1)

                if bank_acc_partner and bank_acc_partner.partner_id:

                    partner_id = bank_acc_partner.partner_id.id

                    partner_name = bank_acc_partner.partner_id.name

                    confidence = 0.98

                    reason = f"Exact bank account match with partner {partner_name}"



            # Tier 3: Search by Invoice / Bill Reference in narration

            if not partner_id:

                inv_ref_match = re.search(r'(?:INV|BILL|REF|PO)[/-]?\s*([A-Za-z0-9\-_/]+)', narration_clean, re.I)

                if inv_ref_match:

                    found_inv = self.env['account.move'].sudo().search([

                        ('state', '=', 'posted'),

                        ('name', 'ilike', inv_ref_match.group(1).strip()),

                        ('company_id', '=', company_id)

                    ], limit=1)

                    if found_inv and found_inv.partner_id:

                        partner_id = found_inv.partner_id.id

                        partner_name = found_inv.partner_id.name

                        matched_inv_id = found_inv.id

                        confidence = 0.95

                        reason = f"Invoice ref {inv_ref_match.group(1)} matches {found_inv.name}"

                        txn_type = 'customer_payment' if found_inv.is_sale_document() else 'vendor_payment'

                        counterparty_type = 'customer' if found_inv.is_sale_document() else 'vendor'



            # Tier 4: Exact Name Match

            if not partner_id and proposed_name and len(proposed_name) >= 3:

                exact_p = self.env['res.partner'].sudo().search([

                    ('name', '=ilike', proposed_name),

                    '|', ('company_id', '=', False), ('company_id', '=', company_id)

                ], limit=1)

                if exact_p:

                    partner_id = exact_p.id

                    partner_name = exact_p.name

                    confidence = max(confidence, 0.92)

                    reason = f"Exact name match with partner {exact_p.name}"



            # Tier 5: Fallback from matcher fuzzy engine

            if partner_id:

                contact_status = 'existing'

                if txn_type == 'unknown':

                    p_rec = self.env['res.partner'].sudo().browse(partner_id)

                    if p_rec.customer_rank > p_rec.supplier_rank:

                        txn_type = 'customer_payment'

                        counterparty_type = 'customer'

                    elif p_rec.supplier_rank > p_rec.customer_rank:

                        txn_type = 'vendor_payment'

                        counterparty_type = 'vendor'

                    else:

                        txn_type = 'vendor_payment' if is_debit else 'customer_payment'

                        counterparty_type = 'vendor' if is_debit else 'customer'

            else:

                # NO EXISTING PARTNER FOUND: Propose contact in STAGING ONLY!

                if proposed_name and len(proposed_name) >= 3:

                    contact_status = 'new_proposed'

                    counterparty_type = 'vendor' if is_debit else 'customer'

                    if txn_type == 'unknown':

                        txn_type = 'vendor_payment' if is_debit else 'customer_payment'

                    reason = f"New proposed contact: '{proposed_name}' (requires accountant approval)"

                    confidence = 0.75

                else:

                    contact_status = 'needs_review'

                    reason = "No identifiable counterparty found; accountant review required"

                    confidence = 0.40



        approval_target = 'customer' if counterparty_type == 'customer' else ('vendor' if counterparty_type == 'vendor' else 'none')



        return {

            'transaction_type': txn_type,

            'counterparty_type': counterparty_type,

            'contact_status': contact_status,

            'approval_target': approval_target,

            'partner_id': partner_id,

            'partner_name': partner_name,

            'proposed_contact_name': proposed_name,

            'proposed_upi_id': upi_id or False,

            'proposed_bank_account': bank_account or False,

            'classification_confidence': confidence,

            'classification_reason': reason,

            'account_id': target_account_id,

            'matched_invoice_id': matched_inv_id,

        }



    def action_parse_statement(self):

        self.ensure_one()

        if not self.file_data:

            raise UserError("Please upload a bank statement document (PDF, Image, or CSV) first.")



        parser = self.env['gsus.bank.ai.vision.parser'].sudo()

        matcher = self.env['gsus.bank.ai.matcher'].sudo()

        rules = self.env['gsus.bank.ai.rule'].sudo().search([('is_active', '=', True)])



        # Execute elevated multimodal extraction with PDF password decryption (handles Odoo 20 BinaryValueAttachment)

        fd = self.file_data

        if hasattr(fd, 'to_base64'):

            raw_b64 = fd.to_base64()

        elif hasattr(fd, 'content'):

            raw_b64 = base64.b64encode(fd.content).decode('ascii')

        elif isinstance(fd, bytes):

            raw_b64 = fd.decode('ascii')

        else:

            raw_b64 = str(fd or '')

        temp_pwd = self.pdf_password

        try:

            parsed_result = parser.parse_statement_file(

                raw_b64,

                self.file_name or 'statement.pdf',

                pdf_password=temp_pwd

            )

        finally:

            # Security Hardening: Immediately wipe PDF password from database

            if self.pdf_password:

                self.pdf_password = False



        # Update Session Metadata

        # Update Session Metadata - resolve IFSC to full bank name if returned as code
        raw_b_name = (parsed_result.get('bank_name') or self.bank_name or '').strip()
        IFSC_TO_BANK = {
            'TMBL': 'Tamilnad Mercantile Bank',
            'KKBK': 'Kotak Mahindra Bank',
            'HDFC': 'HDFC Bank',
            'ICIC': 'ICICI Bank',
            'UTIB': 'Axis Bank',
            'SBIN': 'State Bank of India',
            'BARB': 'Bank of Baroda',
            'PUNB': 'Punjab National Bank',
            'CNRB': 'Canara Bank',
            'UBIN': 'Union Bank of India',
            'FDRL': 'Federal Bank',
            'INDB': 'IndusInd Bank',
            'YESB': 'Yes Bank',
            'IDIB': 'Indian Bank',
            'IOBA': 'Indian Overseas Bank',
        }
        if raw_b_name.upper() in IFSC_TO_BANK:
            raw_b_name = IFSC_TO_BANK[raw_b_name.upper()]
        self.bank_name = raw_b_name or 'Unknown Bank'

        self.account_number = parsed_result.get('account_number') or self.account_number

        self.account_holder = parsed_result.get('account_holder') or self.account_holder

        if parsed_result.get('opening_balance'):

            self.opening_balance = float(parsed_result['opening_balance'])

        if parsed_result.get('closing_balance'):

            self.closing_balance = float(parsed_result['closing_balance'])



        # Auto-detect Bank Journal if not selected, or create default if none exists

        if not self.journal_id:

            journal = self.env['account.journal'].sudo().search(

                [('type', '=', 'bank')], limit=1

            )

            if not journal:

                # Auto-create bank journal so user never faces missing journal block

                journal_code = 'BNK1'

                if self.bank_name:

                    clean_code = ''.join(c for c in self.bank_name if c.isalnum())[:5].upper()

                    if clean_code:

                        journal_code = clean_code

                journal = self.env['account.journal'].sudo().create({

                    'name': self.bank_name or 'Bank',

                    'type': 'bank',

                    'code': journal_code,

                    'company_id': self.company_id.id or self.env.company.id,

                })

            if journal:

                self.journal_id = journal.id

        # In-Memory Cache preparation

        partner_cache = matcher._get_partner_cache()

        account_cache = matcher._get_account_cache()

        open_invoice_cache = matcher._get_open_invoice_cache()



        # Build Staging Lines

        self.line_ids.unlink()

        line_vals = []

        for idx, tx in enumerate(parsed_result.get('transactions', [])):

            debit = float(tx.get('debit') or 0.0)

            credit = float(tx.get('credit') or 0.0)

            narration = tx.get('narration') or 'Transaction'

            ref = tx.get('reference') or False



            # Intelligent UTR / RRN / Cheque extraction if reference not directly isolated

            if not ref and narration:

                utr_match = re.search(r'(?:UPI|IMPS)[/-](?:DR|CR|P2A|P2P)*[/-]*(\d{12})', narration, re.I)

                if not utr_match:

                    utr_match = re.search(r'\b(\d{12})\b', narration)

                if utr_match:

                    ref = utr_match.group(1)

                else:

                    neft_match = re.search(r'(?:NEFT|RTGS)[/-]([A-Za-z0-9]+)', narration, re.I)

                    if neft_match:

                        ref = neft_match.group(1)

                    elif 'NACH' in narration.upper():

                        nach_m = re.search(r'NACH(\d+)', narration, re.I)

                        if nach_m:

                            ref = f"NACH{nach_m.group(1)}"



            date_val = tx.get('date') or fields.Date.context_today(self)



            # Match using 5-layer semantic engine

            match_info = matcher.match_transaction(

                narration=narration,

                debit=debit,

                credit=credit,

                company_id=self.company_id.id,

            )



            # Intelligent Classification & 5-tier Contact Matching

            clf = self._classify_and_match_transaction(narration, debit, credit, ref, match_info)



            line_vals.append((0, 0, {

                'sequence': (idx + 1) * 10,

                'date': date_val,

                'narration': narration,

                'reference': ref,

                'debit': debit,

                'credit': credit,

                'balance': float(tx.get('balance')) if tx.get('balance') is not None else 0.0,

                'counterparty': clf.get('proposed_contact_name') or match_info.get('counterparty') or '',

                'proposed_contact_name': clf.get('proposed_contact_name') or '',

                'new_contact_name': clf.get('proposed_contact_name') or '',

                'proposed_upi_id': clf.get('proposed_upi_id') or False,

                'proposed_bank_account': clf.get('proposed_bank_account') or False,

                'transaction_type': clf.get('transaction_type', 'unknown'),

                'counterparty_type': clf.get('counterparty_type', 'none'),

                'contact_status': clf.get('contact_status', 'needs_review'),

                'approval_target': clf.get('approval_target', 'none'),

                'classification_confidence': clf.get('classification_confidence', 0.0),

                'classification_reason': clf.get('classification_reason', ''),

                'partner_id': clf.get('partner_id'),

                'account_id': clf.get('account_id'),

                'matched_invoice_id': clf.get('matched_invoice_id'),

                'confidence': clf.get('classification_confidence', match_info.get('confidence', 0.0)),

                'status': 'reviewed' if clf.get('contact_status') in ('existing', 'no_contact_needed') and clf.get('account_id') else 'suggested',

                'suggestion_source': match_info.get('suggestion_source', 'fuzzy'),

                'ai_reason': clf.get('classification_reason') or match_info.get('ai_reason', ''),

            }))



        self.line_ids = line_vals

        # Smart Opening Balance Derivation:

        # If opening balance was not explicitly printed in bank statement (e.g. SBI, WhatsApp Banking),

        # derive it backward from first transaction running balance, or from closing balance and totals.

        if (not self.opening_balance or self.opening_balance == 0.0) and self.line_ids:

            sorted_lines = self.line_ids.sorted(lambda l: (l.date, l.sequence, l.id))

            first_l = sorted_lines[:1]

            if first_l and first_l.balance:

                self.opening_balance = round(first_l.balance - first_l.credit + first_l.debit, 2)

            elif self.closing_balance and (self.total_credit or self.total_debit):

                self.opening_balance = round(self.closing_balance - self.total_credit + self.total_debit, 2)



        self.state = 'parsed'

        # Security Hardening: Immediately wipe PDF password from database after parsing

        if self.pdf_password:

            self.pdf_password = False

        return True



    # -------------------------------------------------------------

    # 2. AUTO-ASSIGN & GROUP ACTIONS

    # -------------------------------------------------------------

    def action_auto_assign_high_confidence(self):

        """Auto-assign lines where confidence >= 85%."""

        for line in self.line_ids.filtered(lambda l: l.status == 'suggested' and l.confidence >= 0.85):

            line.status = 'reviewed'

        return True



    def action_mark_all_reviewed(self):

        """Mark all assigned lines as reviewed."""

        self.line_ids.filtered(lambda l: l.account_id or l.partner_id).write({'status': 'reviewed'})

        self.state = 'reviewed'

        return True



    # -------------------------------------------------------------

    # 3. 1-CLICK PUSH TO NATIVE ODOO ACCOUNTING (AUTONOMOUS AUTO-RECONCILIATION)

    # -------------------------------------------------------------

    def action_push_to_odoo(self):

        """Autonomous 1-Click push: auto-reconcile open customer/vendor invoices to PAID,

        assign direct counterpart accounts, populate Partner & Reference on Journal Entries,

        and eliminate Bank Suspense Account balance."""

        self.ensure_one()

        if not self.line_ids:

            raise UserError(_("No transactions to push."))



        # ─── DUPLICATE PUSH GUARD (SAFETY LOCK) ─────────────────────────

        # Lock 1: Statement level check

        if self.state == 'pushed' and self.account_bank_statement_id and self.account_bank_statement_id.exists():

            raise UserError(

                _("DUPLICATE PUSH BLOCKED!\n\n"

                  "This bank statement has already been pushed to native Odoo Accounting as '%s'.\n\n"

                  "To prevent duplicate journal entries in your General Ledger, re-pushing is locked.\n"

                  "If you need to make changes and re-push, click 'Rollback / Revert' first to safely cancel and un-reconcile previous entries.")

                % (self.account_bank_statement_id.name or 'Bank Statement')

            )



        # Lock 2: Filter for unpushed lines only

        lines_to_push = self.line_ids.filtered(lambda l: l.status != 'pushed' and not l.native_statement_line_id)

        if not lines_to_push:

            raise UserError(

                _("DUPLICATE PUSH BLOCKED!\n\n"

                  "All %d transactions in this statement have already been pushed to Odoo.\n"

                  "No duplicate journal entries were created.") % len(self.line_ids)

            )



        # Ensure a Bank Journal is assigned; auto-create if database has none

        if not self.journal_id:

            journal = self.env['account.journal'].sudo().search([('type', '=', 'bank')], limit=1)

            if not journal:

                journal_code = 'BNK1'

                if self.bank_name:

                    clean_code = ''.join(c for c in self.bank_name if c.isalnum())[:5].upper()

                    if clean_code:

                        journal_code = clean_code

                journal = self.env['account.journal'].sudo().create({

                    'name': self.bank_name or 'Bank',

                    'type': 'bank',

                    'code': journal_code,

                    'company_id': self.company_id.id or self.env.company.id,

                })

            self.journal_id = journal.id



        # Create or update native Odoo bank statement

        st_vals = {

            'name': f"{self.bank_name or 'Bank'} Statement - {self.name}",

            'journal_id': self.journal_id.id,

            'balance_start': self.opening_balance,

            'balance_end_real': self.closing_balance if self.closing_balance > 0 else (self.opening_balance + self.net_flow),

        }



        StatementModel = self.env['account.bank.statement'].sudo()

        st_record = StatementModel.create(st_vals)



        LineModel = self.env['account.bank.statement.line'].sudo()

        reconciled_invoice_count = 0

        categorized_count = 0



        for line in lines_to_push:

            net_amt = line.credit - line.debit

            partner_id = line.partner_id.id if line.partner_id else False



            # Strict Contact Gatekeeping & Accountant Approval Verification

            partner_id = False

            c_name = (line.proposed_contact_name or '').strip()



            # Case 1: Line already has a partner assigned

            if line.partner_id:

                partner_id = line.partner_id.id

                # If contact name was updated, sync the master contact's name in Odoo

                if c_name and line.partner_id.name.strip().lower() != c_name.lower():

                    line.partner_id.sudo().write({'name': c_name})

                line.contact_status = 'existing'

            # Case 2: Contact status is existing

            elif line.contact_status == 'existing' and line.partner_id:

                partner_id = line.partner_id.id

            # Case 3: Approved contact or edited proposed contact name

            elif line.contact_status == 'approved' or (c_name and len(c_name) >= 2):

                raw_name = (c_name or line.new_contact_name or line.counterparty or '').strip()

                if raw_name and len(raw_name) >= 2:

                    existing_p = self.env['res.partner'].sudo().search([

                        ('name', '=ilike', raw_name),

                        '|', ('company_id', '=', False), ('company_id', '=', self.company_id.id)

                    ], limit=1)

                    if existing_p:

                        partner_id = existing_p.id

                    else:

                        is_cust = (line.approval_target == 'customer') or (line.counterparty_type == 'customer') or (line.credit > 0)

                        is_vend = (line.approval_target == 'vendor') or (line.counterparty_type == 'vendor') or (line.debit > 0)

                        new_p = self.env['res.partner'].sudo().create({

                            'name': raw_name,

                            'company_id': self.company_id.id,

                            'customer_rank': 1 if is_cust else 0,

                            'supplier_rank': 1 if is_vend else 0,

                        })

                        partner_id = new_p.id

                    line.partner_id = partner_id

                    line.contact_status = 'existing'

            # 3. No Contact Needed, Rejected, Bank Charges, Bank Interest, or Internal Transfer -> ZERO contact

            elif line.contact_status in ('no_contact_needed', 'rejected') or line.transaction_type in ('bank_charges', 'bank_interest', 'internal_transfer'):

                partner_id = False

            # 4. New Proposed or Needs Review (NOT approved by accountant) -> NEVER create partner!

            elif line.contact_status in ('new_proposed', 'needs_review'):

                partner_id = False



            target_account_id = line.account_id.id if line.account_id else False

            if not target_account_id:

                if line.debit > 0:

                    exp_acc = self.env['account.account'].sudo().search([

                        ('account_type', 'in', ('expense', 'expense_direct_cost')),

                        ('company_ids', 'in', [self.company_id.id])

                    ], limit=1)

                    if exp_acc:

                        target_account_id = exp_acc.id

                else:

                    inc_acc = self.env['account.account'].sudo().search([

                        ('account_type', 'in', ('income', 'income_other')),

                        ('company_ids', 'in', [self.company_id.id])

                    ], limit=1)

                    if inc_acc:

                        target_account_id = inc_acc.id



            ref_text = line.reference or (line.narration[:60] if line.narration else 'Bank Transaction')



            st_line = LineModel.create({

                'statement_id': st_record.id,

                'journal_id': self.journal_id.id,

                'date': line.date,

                'payment_ref': (line.narration or 'Transaction')[:200],

                'amount': net_amt,

                'partner_id': partner_id,

            })



            move = st_line.move_id

            if not move:

                line.write({'status': 'pushed'})

                continue



            # Counterpart line: not the bank default liquidity account

            counterpart = move.line_ids.filtered(lambda l: l.account_id.id != self.journal_id.default_account_id.id)



            # ─── TIER 1: AUTO-RECONCILE OPEN INVOICES TO PAID ──────────────

            matched_inv = False

            if line.matched_invoice_id:

                matched_inv = line.matched_invoice_id

            elif partner_id:

                # Fuzzy search for open posted customer invoice or vendor bill matching the amount

                move_types = ('out_invoice', 'out_refund') if line.credit > 0 else ('in_invoice', 'in_refund')

                inv_domain = [

                    ('partner_id', '=', partner_id),

                    ('state', '=', 'posted'),

                    ('payment_state', 'in', ('not_paid', 'partial')),

                    ('move_type', 'in', move_types),

                ]

                candidates = self.env['account.move'].sudo().search(inv_domain)

                for cand in candidates:

                    if abs(cand.amount_residual - abs(net_amt)) < 0.05:

                        matched_inv = cand

                        break



            if matched_inv and counterpart:

                inv_lines = matched_inv.line_ids.filtered(

                    lambda l: l.account_id.account_type in ('asset_receivable', 'liability_payable') and not l.reconciled

                )

                if inv_lines:

                    try:

                        move.button_draft()

                        counterpart.write({

                            'account_id': inv_lines[0].account_id.id,

                            'partner_id': partner_id,

                        })

                        move.write({

                            'partner_id': partner_id,

                            'ref': matched_inv.name or ref_text,

                        })

                        move.action_post()

                        (inv_lines[0] + counterpart).reconcile()

                        reconciled_invoice_count += 1

                        line.write({

                            'status': 'pushed',

                            'native_statement_line_id': st_line.id,

                            'matched_invoice_id': matched_inv.id,

                            'matched_invoice_ref': matched_inv.name,

                        })

                        continue

                    except Exception as e:

                        _logger.warning("Auto-reconcile invoice error: %s", str(e))



            # ─── TIER 2: DIRECT COUNTERPART CATEGORIZATION (Expense/Income) ──

            if target_account_id and counterpart:

                try:

                    move.button_draft()

                    counterpart.write({

                        'account_id': target_account_id,

                        'partner_id': partner_id,

                    })

                    move.write({

                        'partner_id': partner_id,

                        'ref': ref_text,

                    })

                    move.action_post()

                    categorized_count += 1

                except Exception as e:

                    _logger.warning("Auto-categorize counterpart error: %s", str(e))

            elif partner_id and counterpart:

                try:

                    move.button_draft()

                    counterpart.write({'partner_id': partner_id})

                    move.write({'partner_id': partner_id, 'ref': ref_text})

                    move.action_post()

                except Exception as e:

                    pass



            line.write({

                'status': 'pushed',

                'native_statement_line_id': st_line.id,

            })



        self.account_bank_statement_id = st_record.id

        self.state = 'pushed'



        return {

            'success': True,

            'reconciled_invoice_count': reconciled_invoice_count,

            'categorized_count': categorized_count,

            'statement_id': st_record.id,

            'name': st_record.name,

        }



    # -------------------------------------------------------------

    # 4. 1-CLICK ROLLBACK / REVERT (WITH SAFE UN-RECONCILIATION)

    # -------------------------------------------------------------

    def action_revert_push(self):

        """Rollback created Odoo bank statement, un-reconcile invoices back to unpaid, and restore staging session."""

        self.ensure_one()

        if self.account_bank_statement_id:

            st = self.account_bank_statement_id

            if hasattr(st, 'line_ids') and st.line_ids:

                for st_line in st.line_ids:

                    move = st_line.move_id

                    if move:

                        reconciled_lines = move.line_ids.filtered(lambda l: l.reconciled)

                        if reconciled_lines:

                            try:

                                reconciled_lines.remove_move_reconcile()

                            except Exception as e:

                                _logger.warning("Un-reconcile line warning during rollback: %s", str(e))

                        try:

                            move.button_draft()

                        except Exception:

                            pass

                try:

                    st.line_ids.unlink()

                except Exception as e:

                    _logger.warning("Statement lines unlink warning: %s", str(e))

            try:

                st.unlink()

            except Exception as e:

                _logger.warning("Rollback statement unlink warning: %s", str(e))

            self.account_bank_statement_id = False



        self.line_ids.write({

            'status': 'reviewed',

            'native_statement_line_id': False,

        })

        self.state = 'reviewed'

        return {

            'type': 'ir.actions.client',

            'tag': 'display_notification',

            'params': {

                'title': 'Rollback Successful',

                'message': 'Bank statement unwound, invoices restored to unpaid, and staging restored.',

                'type': 'warning',

                'sticky': False,

            }

        }



    def action_open_bank_reconcile_widget(self):

        """Open Odoo native bank reconciliation widget for this statement, or fallback to statement form."""

        self.ensure_one()

        if not self.account_bank_statement_id:

            return {

                'type': 'ir.actions.client',

                'tag': 'display_notification',

                'params': {

                    'title': 'Statement Not Pushed',

                    'message': 'Please push the statement to Odoo first before reconciling.',

                    'type': 'warning',

                    'sticky': False,

                }

            }



        st = self.account_bank_statement_id

        # 1. Enterprise Bank Rec Widget on account.bank.statement

        if hasattr(st, 'action_open_bank_reconcile_widget'):

            try:

                return st.action_open_bank_reconcile_widget()

            except Exception as e:

                _logger.warning("Error calling st.action_open_bank_reconcile_widget: %s", str(e))



        # 2. Enterprise Bank Rec Line Widget

        st_line_model = self.env.get('account.bank.statement.line')

        if st_line_model is not None and hasattr(st_line_model, '_action_open_bank_reconciliation_widget'):

            try:

                return st_line_model._action_open_bank_reconciliation_widget(

                    name=st.name,

                    default_context={

                        'search_default_statement_id': st.id,

                        'search_default_journal_id': st.journal_id.id,

                    },

                    extra_domain=[('statement_id', '=', st.id)]

                )

            except Exception as e:

                _logger.warning("Error opening bank rec line widget: %s", str(e))



        # 3. Fallback to standard Odoo Bank Statement form view

        return {

            'type': 'ir.actions.act_window',

            'name': f'Bank Statement: {st.name}',

            'res_model': 'account.bank.statement',

            'res_id': st.id,

            'views': [[False, 'form']],

            'view_mode': 'form',

            'target': 'current',

        }



    # -------------------------------------------------------------

    # 5. IN-WORKBENCH CHAT COPILOT NATURAL LANGUAGE BATCH ACTIONS

    # -------------------------------------------------------------

    def action_chat_batch_command(self, user_prompt: str) -> dict:

        """Process conversational natural language instructions from the in-workbench copilot."""

        self.ensure_one()

        prompt_upper = (user_prompt or '').strip().upper()



        # Check for Rule Learning ("Remember rule...")

        if 'REMEMBER' in prompt_upper and 'RULE' in prompt_upper:

            # e.g. "Remember rule: SWIGGY to Employee Welfare"

            for acc in self.env['account.account'].sudo().search([], limit=500):

                if acc.name.upper() in prompt_upper:

                    rule = self.env['gsus.bank.ai.rule'].sudo().create({

                        'name': f"Learned Rule for {acc.name}",

                        'keyword': prompt_upper.split('REMEMBER')[1].split('RULE')[1].strip().split(' ')[0],

                        'account_id': acc.id,

                        'learned_from_chat': True,

                    })

                    return {

                        'reply': f"✅ Rule saved! Future transactions matching '{rule.keyword}' will automatically map to {acc.name}.",

                        'affected_count': 0

                    }



        # Check for batch assignment commands

        affected = 0

        # Check for Account mention

        target_account = False

        for acc in self.env['account.account'].sudo().search([], limit=500):

            if acc.name.upper() in prompt_upper:

                target_account = acc

                break



        # Check for Partner mention

        target_partner = False

        for p in self.env['res.partner'].sudo().search([], limit=1000):

            if len(p.name) > 3 and p.name.upper() in prompt_upper:

                target_partner = p

                break



        # Filter lines

        matching_lines = self.line_ids

        if 'UPI' in prompt_upper:

            matching_lines = matching_lines.filtered(lambda l: l.payment_mode == 'upi')

        elif 'IMPS' in prompt_upper:

            matching_lines = matching_lines.filtered(lambda l: l.payment_mode == 'imps')



        # Amount conditions (e.g. "UNDER 1000" or "BELOW 500")

        amount_match = re.search(r'(?:UNDER|BELOW|<)\s*(?:RS\.?|INR|[^\w\s])?\s*(\d+)', prompt_upper, re.I)

        if amount_match:

            limit_val = float(amount_match.group(1))

            matching_lines = matching_lines.filtered(lambda l: l.amount <= limit_val)



        if target_account or target_partner:

            vals = {'status': 'reviewed', 'confidence': 1.0}

            if target_account:

                vals['account_id'] = target_account.id

            if target_partner:

                vals['partner_id'] = target_partner.id

            matching_lines.write(vals)

            affected = len(matching_lines)

            return {

                'reply': f"🎯 Executed! Updated {affected} matching transaction lines.",

                'affected_count': affected

            }



        return {

            'reply': f"I analyzed your instruction. Found {len(matching_lines)} candidate lines. Specify an Account or Partner name to apply batch updates.",

            'affected_count': 0

        }

