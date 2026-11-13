# -*- coding: utf-8 -*-
# Part of GSUS Bank AI. See LICENSE file for full copyright and licensing details.

import logging
import re
from difflib import SequenceMatcher
from odoo import models, api

_logger = logging.getLogger(__name__)


class GsusBankAiMatcher(models.AbstractModel):
    _name = 'gsus.bank.ai.matcher'
    _description = 'GSUS Bank AI Semantic Partner & Account Matcher Engine'

    BANK_IFSC_PREFIXES = {
        'YESB', 'TMBL', 'UTIB', 'FDRL', 'SBIN', 'ICIC', 'HDFC', 'KKBK',
        'BARB', 'PUNB', 'CNRB', 'IOBA', 'IDIB', 'UBIN', 'CBIN', 'VIJB',
        'CORP', 'ALLA', 'ANDB', 'SYNB', 'MAHB', 'PSIB', 'BDBL', 'IDFB',
        'PAYTM', 'PYTM', 'AIRP', 'JIOP', 'IPOS', 'CITI', 'HSBC', 'SCBL'
    }

    DISCARD_TOKENS = {
        'UPI', 'UFI', 'DR', 'CR', 'P2A', 'P2P', 'REF', 'PAYMENT', 'TRANSFER',
        'INVOICE', 'BILL', 'MBANK', 'TEST', 'IMPS', 'NEFT', 'RTGS', 'ATM', 'CASH',
        'PHONEPE', 'PAYTM', 'GPAY', 'NAVI', 'CRED', 'BHIM', 'OTHER', 'PHONE', 'PHON',
        'APP', 'NETBANKING', 'MOB'
    }

    @api.model
    def extract_clean_counterparty(self, narration: str) -> str:
        """Extract clean counterparty name from Indian & International bank statement lines."""
        if not narration:
            return ""
        text = narration.strip()
        text_upper = text.upper()

        # 0. Skip bank charges / interest / cash / taxes (no external party)
        if any(k in text_upper for k in ('SMS CHARGE', 'SMS CHG', 'ANNFEE', 'ANNUAL FEE', 'IMPS CHARGE', 'ATM/CASH', 'BANK CHARGE')):
            return ""

        # 1. UPI / UFI: e.g. UPI/665675166831/Bhavani hotel s/YESB/UPI or UPI/DR/618332710546/ANNALAKS/UTIB/annalakshm/UPI
        if text_upper.startswith(('UPI', 'UFI')) or '/UPI' in text_upper or '/UFI' in text_upper:
            parts = [p.strip() for p in text.split('/') if p.strip()]
            candidates = []
            for p in parts:
                p_up = p.upper()
                if p_up in self.DISCARD_TOKENS or p_up in self.BANK_IFSC_PREFIXES:
                    continue
                if re.match(r'^\d+$', p):  # pure number / UTR / reference
                    continue
                if p_up.startswith(('PAYMENT FROM', 'SENDING', 'SENT USING', 'PAYMENT TO', 'TRANSFER TO')):
                    continue
                # Clean handle like ajothi.1234567@ -> ajothi
                cleaned = re.sub(r'[@\d_\.]+', ' ', p).strip()
                if len(cleaned) >= 3 and cleaned.upper() not in self.BANK_IFSC_PREFIXES and cleaned.upper() not in self.DISCARD_TOKENS:
                    candidates.append(cleaned)
            if candidates:
                for cand in candidates:
                    if len(cand) >= 3 and cand.upper() not in self.BANK_IFSC_PREFIXES and cand.upper() not in self.DISCARD_TOKENS:
                        return cand.title()

        # 2. Check for 'To <NAME>' or 'From <NAME>' (e.g. MBank/IMPSP2P To J SUBASH/628719882524/Test)
        to_from = re.search(r'\b(?:To|From)\s+([A-Za-z\s\.\-_]+?)(?:/|\d|$)', text, re.I)
        if to_from:
            cand = to_from.group(1).strip()
            if len(cand) >= 3 and cand.upper() not in self.DISCARD_TOKENS and cand.upper() not in self.BANK_IFSC_PREFIXES and not cand.upper().startswith(('PHONE', 'PHON', 'APP', 'PAYTM', 'GPAY', 'NAVI', 'CRED')):
                return cand.title()

        # 3. IMPS: IMPS/624814610598/fbl-XX328-GSUS STA/Aug2026 M
        imps_match = re.search(r'IMPS[/-]\d+[/-](?:[\w]+-)*(.*?)(?:/|$)', text, re.I)
        if imps_match:
            cand = imps_match.group(1).replace('-', ' ').strip()
            if len(cand) >= 3 and cand.upper() not in self.DISCARD_TOKENS and cand.upper() not in self.BANK_IFSC_PREFIXES:
                return cand.title()

        # 4. NEFT / RTGS: e.g. NEFT/N11019847261/METRO INFOTECH LTD/INVOICE 1042
        neft_match = re.search(r'(?:NEFT|RTGS)[/-][\w]+[/-]([A-Za-z0-9\s]+?)(?:/|$)', text, re.I)
        if neft_match:
            cand = neft_match.group(1).strip()
            if len(cand) >= 3 and cand.upper() not in self.DISCARD_TOKENS:
                return cand.title()

        # 5. NACH / Mandate
        if 'NACH' in text_upper:
            return "NACH Direct Debit"

        # 6. Slash separated generic fallback
        if '/' in text:
            parts = [p.strip() for p in text.split('/') if p.strip()]
            for p in parts:
                p_up = p.upper()
                if p_up in self.DISCARD_TOKENS or p_up in self.BANK_IFSC_PREFIXES:
                    continue
                if re.match(r'^\d+$', p):
                    continue
                cleaned = re.sub(r'[@\d_\.]+', ' ', p).strip()
                if len(cleaned) >= 3:
                    return cleaned.title()

        return ""

    @api.model
    def match_transaction(self, narration: str, debit: float, credit: float,
                          company_id=None, counterparty: str = None,
                          rules_cache=None, memory_cache=None,
                          partner_cache=None, account_cache=None, open_invoice_cache=None) -> dict:
        """5-Layer Semantic Partner & Account Matcher Engine."""
        narration_clean = (narration or '').strip()
        narration_upper = narration_clean.upper()
        amount = debit if debit > 0 else credit
        is_debit = debit > 0
        direction = 'debit' if is_debit else 'credit'
        target_company_id = company_id or self.env.company.id

        # ─── LAYER 1: Learned Business Rules (gsus.bank.ai.rule) ───────
        if rules_cache is None:
            rules_cache = self.env['gsus.bank.ai.rule'].sudo().search([
                ('is_active', '=', True),
                '|', ('company_id', '=', False), ('company_id', '=', target_company_id)
            ], order='priority desc, sequence asc')

        for rule in rules_cache:
            if rule.apply_to_narration(narration_clean, amount, direction=direction):
                return {
                    'partner_id': rule.partner_id.id if rule.partner_id else False,
                    'partner_name': rule.partner_id.name if rule.partner_id else "",
                    'account_id': rule.account_id.id if rule.account_id else False,
                    'confidence': 1.0,
                    'matched_invoice_id': False,
                    'matched_invoice_ref': "",
                    'status': 'suggested',
                    'suggestion_source': 'rule',
                    'ai_reason': f"Matched rule: '{rule.name}' ({rule.keyword})",
                }

        # ─── LAYER 2: Learned Historical Memory (gsus.bank.ai.memory) ──
        clean_cp = (counterparty or '').strip().upper()
        if not clean_cp:
            extracted_cp = self.extract_clean_counterparty(narration_clean)
            if extracted_cp:
                clean_cp = extracted_cp.upper()
            else:
                upi_match = re.search(r'(?:UPI|IMPS|NEFT)[/-](?:DR|CR|P2A|P2P)[/-][\w]+[/-]([^/]+)', narration_clean, re.I)
                if upi_match:
                    clean_cp = upi_match.group(1).strip().upper()
                else:
                    clean_cp = narration_upper[:40]

        if clean_cp:
            memory_rec = self.env['gsus.bank.ai.memory'].sudo().search([
                ('counterparty_key', '=', clean_cp),
                ('direction', '=', direction),
                ('company_id', '=', target_company_id),
            ], limit=1)
            if memory_rec:
                return {
                    'partner_id': memory_rec.partner_id.id if memory_rec.partner_id else False,
                    'partner_name': memory_rec.partner_id.name if memory_rec.partner_id else "",
                    'account_id': memory_rec.account_id.id if memory_rec.account_id else False,
                    'confidence': 0.95,
                    'matched_invoice_id': False,
                    'matched_invoice_ref': "",
                    'status': 'suggested',
                    'suggestion_source': 'memory',
                    'ai_reason': f"Confirmed {memory_rec.confirmations}x previously for '{clean_cp}'",
                }

        # ─── LAYER 3: Partner & Open Invoice Fuzzy Match ───────────────
        if partner_cache is None:
            partner_cache = self._get_partner_cache(target_company_id)
        if account_cache is None:
            account_cache = self._get_account_cache(target_company_id)
        if open_invoice_cache is None:
            open_invoice_cache = self._get_open_invoice_cache(target_company_id)

        best_partner_id = False
        best_partner_name = ""
        best_partner_score = 0.0

        lookup_text = clean_cp if clean_cp else narration_upper

        for p in partner_cache:
            p_name_upper = p['name_upper']
            if len(p_name_upper) >= 3 and (p_name_upper in lookup_text or lookup_text in p_name_upper):
                score = 0.92 + min(0.06, len(p_name_upper) / 100)
                if score > best_partner_score:
                    best_partner_score = score
                    best_partner_id = p['id']
                    best_partner_name = p['name']
            else:
                ratio = SequenceMatcher(None, p_name_upper, lookup_text).ratio()
                if ratio > 0.70 and ratio > best_partner_score:
                    best_partner_score = ratio
                    best_partner_id = p['id']
                    best_partner_name = p['name']

        # If not in cache, check case-insensitive direct search or suggest counterparty name
        if not best_partner_id and clean_cp and len(clean_cp) >= 3:
            found_partner = self.env['res.partner'].sudo().search([
                ('name', '=ilike', clean_cp),
                '|', ('company_id', '=', False), ('company_id', '=', target_company_id)
            ], limit=1)
            if found_partner:
                best_partner_id = found_partner.id
                best_partner_name = found_partner.name
                best_partner_score = 0.95

        # Check Open Invoices for matched partner
        matched_invoice_id = False
        matched_invoice_ref = ""
        if best_partner_id and open_invoice_cache:
            for inv in open_invoice_cache:
                if inv['partner_id'] == best_partner_id:
                    if abs(inv['residual'] - amount) < 0.05:
                        matched_invoice_id = inv['id']
                        matched_invoice_ref = inv['name']
                        best_partner_score = 1.0
                        break

        # ─── LAYER 4: Smart Chart of Accounts Keyword Categorization ───
        best_account_id = False
        best_account_score = 0.0

        keyword_accounts = {
            ('SALARY', 'PAYROLL', 'WAGES'): ['Salary', 'Wages', 'Payroll'],
            ('RENT', 'OFFICE RENT', 'LEASE'): ['Rent', 'Office Rent'],
            ('ELECTRICITY', 'POWER', 'TNEB', 'BESCOM'): ['Electricity', 'Utility', 'Power'],
            ('PETROL', 'FUEL', 'HPCL', 'BPCL', 'IOCL'): ['Vehicle', 'Fuel', 'Travel'],
            ('INTERNET', 'AIRTEL', 'JIO', 'BROADBAND'): ['Internet', 'Telephone', 'Communication'],
            ('GST', 'TAX', 'TDS', 'CHALLAN'): ['GST', 'Tax', 'TDS Payable'],
            ('SWIGGY', 'ZOMATO', 'FOOD', 'REFRESHMENT', 'HOTEL'): ['Refreshment', 'Meal', 'Employee Welfare', 'Food'],
            ('INTEREST', 'INT PAID', 'LOAN EMI'): ['Interest', 'Bank Charges', 'Loan'],
            ('CHARGES', 'CHG', 'SMS CHG', 'ANNUAL FEE'): ['Bank Charges', 'Fees'],
        }

        for keywords, name_targets in keyword_accounts.items():
            if any(k in narration_upper for k in keywords):
                for acc in account_cache:
                    if any(target.lower() in acc['name'].lower() for target in name_targets):
                        best_account_id = acc['id']
                        best_account_score = 0.90
                        break
                if best_account_id:
                    break

        if not best_account_id and best_partner_id:
            partner_rec = self.env['res.partner'].sudo().browse(best_partner_id)
            if is_debit and partner_rec.property_account_payable_id:
                best_account_id = partner_rec.property_account_payable_id.id
                best_account_score = max(best_partner_score, 0.85)
            elif not is_debit and partner_rec.property_account_receivable_id:
                best_account_id = partner_rec.property_account_receivable_id.id
                best_account_score = max(best_partner_score, 0.85)

        if not best_account_id:
            # Fallback smart expense/income account from cache
            if is_debit:
                for acc in account_cache:
                    acc_n = acc['name'].lower()
                    if 'expense' in acc_n or 'office' in acc_n or 'general' in acc_n or 'misc' in acc_n:
                        best_account_id = acc['id']
                        best_account_score = 0.75
                        break
            else:
                for acc in account_cache:
                    acc_n = acc['name'].lower()
                    if 'income' in acc_n or 'sales' in acc_n or 'revenue' in acc_n:
                        best_account_id = acc['id']
                        best_account_score = 0.75
                        break

        # ─── LAYER 5: Suspense Fallback ───────────────────────────────
        confidence = round(max(best_partner_score, best_account_score), 2)
        if confidence == 0.0:
            confidence = 0.40

        status = 'suggested' if confidence >= 0.70 else 'pending'
        source = 'fuzzy' if best_partner_id else ('ai' if best_account_id else 'manual')
        ai_reason = "Fuzzy partner match" if best_partner_id else ("Smart ledger assignment" if best_account_id else "Unassigned / Needs review")

        return {
            'partner_id': best_partner_id,
            'partner_name': best_partner_name or (clean_cp.title() if clean_cp else ""),
            'proposed_partner_name': clean_cp.title() if (clean_cp and not best_partner_id) else "",
            'counterparty': clean_cp.title() if clean_cp else "",
            'account_id': best_account_id,
            'confidence': confidence,
            'matched_invoice_id': matched_invoice_id,
            'matched_invoice_ref': matched_invoice_ref,
            'status': status,
            'suggestion_source': source,
            'ai_reason': ai_reason,
        }

    # -------------------------------------------------------------
    # CACHES
    # -------------------------------------------------------------
    @api.model
    def _get_partner_cache(self, company_id=None) -> list:
        domain = ['|', ('company_id', '=', False), ('company_id', '=', company_id)] if company_id else []
        partners = self.env['res.partner'].sudo().search_read(
            domain, ['id', 'name'], limit=2000
        )
        return [{'id': p['id'], 'name': p['name'], 'name_upper': p['name'].strip().upper()} for p in partners if p.get('name')]

    @api.model
    def _get_account_cache(self, company_id=None) -> list:
        domain = [('company_ids', 'in', [company_id])] if company_id else []
        accounts = self.env['account.account'].sudo().search_read(
            domain, ['id', 'name', 'code', 'account_type'], limit=1000
        )
        return [{'id': a['id'], 'name': a['name'], 'code': a.get('code', '')} for a in accounts]

    @api.model
    def _get_open_invoice_cache(self, company_id=None) -> list:
        domain = [
            ('state', '=', 'posted'),
            ('payment_state', 'in', ('not_paid', 'partial')),
            ('move_type', 'in', ('out_invoice', 'in_invoice'))
        ]
        if company_id:
            domain.append(('company_id', '=', company_id))
        invoices = self.env['account.move'].sudo().search_read(
            domain,
            ['id', 'name', 'partner_id', 'amount_residual', 'move_type'],
            limit=1000
        )
        return [{
            'id': inv['id'],
            'name': inv['name'],
            'partner_id': inv['partner_id'][0] if inv['partner_id'] else False,
            'residual': inv['amount_residual'],
            'type': inv['move_type'],
        } for inv in invoices]
