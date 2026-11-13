# -*- coding: utf-8 -*-
# Part of GSUS Bank AI. See LICENSE file for full copyright and licensing details.
import logging
from odoo import http, fields
from odoo.http import request
_logger = logging.getLogger(__name__)
class GsusBankAiController(http.Controller):
    @http.route('/gsus_bank_ai/get_ai_engine_status', type='json', auth='user')
    def get_ai_engine_status(self):
        Provider = request.env['gsus.bank.ai.provider'].sudo()
        active_provider = Provider.search([('is_active', '=', True)], limit=1)
        backup_provider = Provider.search([('id', '!=', active_provider.id if active_provider else False)], limit=1)
        if backup_provider:
            backup_engine_name = f"{backup_provider.name} ({backup_provider.model_name})" if backup_provider.model_name else backup_provider.name
        elif active_provider and active_provider.provider_type == 'gemini':
            backup_engine_name = "OpenAI (GPT-4o Vision)"
        else:
            backup_engine_name = "Google Gemini Multimodal"
        if active_provider:
            model_disp = active_provider.model_name or "Active"
            return {
                'badge_text': f"{model_disp} • Active",
                'badge_color': "success",
                'has_key': bool(active_provider.api_key),
                'model_name': model_disp,
                'engine_name': active_provider.name,
                'provider_type': active_provider.provider_type,
                'backup_engine_name': backup_engine_name,
            }
        return {
            'badge_text': "AI Engine (Not set)",
            'badge_color': "warning",
            'has_key': False,
            'model_name': "None",
            'engine_name': "Not configured",
            'backup_engine_name': backup_engine_name,
        }
    @http.route('/gsus_bank_ai/get_dashboard_metrics', type='json', auth='user')
    def get_dashboard_metrics(self):
        Statement = request.env['gsus.bank.statement.ai'].sudo()
        company = request.env.company
        user = request.env.user
        domain = ['|', ('company_id', '=', False), ('company_id', '=', company.id)]
        statements = Statement.search(domain, order='create_date desc, id desc')
        total_jobs = len(statements)
        avg_confidence = 100
        if statements:
            conf_list = [s.confidence_avg for s in statements if s.confidence_avg > 0]
            if conf_list:
                avg_confidence = int(round(sum(conf_list) / len(conf_list)))
        # Live Invoice Queue Queries
        inv_domain = [
            ('state', '=', 'posted'),
            ('payment_state', 'in', ('not_paid', 'partial')),
            ('move_type', 'in', ('out_invoice', 'in_invoice')),
            '|', ('company_id', '=', False), ('company_id', '=', company.id)
        ]
        open_invoices = request.env['account.move'].sudo().search(inv_domain)
        cust_invoices = open_invoices.filtered(lambda m: m.move_type == 'out_invoice')
        vendor_bills = open_invoices.filtered(lambda m: m.move_type == 'in_invoice')
        cust_count = len(cust_invoices)
        cust_amount = sum(cust_invoices.mapped('amount_residual'))
        bill_count = len(vendor_bills)
        bill_amount = sum(vendor_bills.mapped('amount_residual'))
        # Real Statement & AI Processing Metrics
        total_txns = sum(statements.mapped('total_transactions'))
        recent_list = []
        for s in statements[:10]:
            recent_list.append({
                'id': s.id,
                'name': s.name,
                'bank_name': s.bank_name or 'Bank',
                'statement_date': str(s.statement_date or (s.create_date and s.create_date.date()) or fields.Date.context_today(s)),
                'total_transactions': s.total_transactions,
                'total_debit': s.total_debit,
                'total_credit': s.total_credit,
                'confidence_avg': s.confidence_avg,
                'state': s.state,
                'state_label': dict(s._fields['state'].selection).get(s.state, s.state),
            })
        # Real-Time Active AI Engine Inspection
        Provider = request.env['gsus.bank.ai.provider'].sudo()
        active_prov = Provider.search([('is_active', '=', True)], limit=1, order='sequence asc, id asc')
        if not active_prov:
            active_prov = Provider.search([], limit=1, order='sequence asc, id asc')
        has_key = bool(active_prov and active_prov.api_key_encrypted)
        if not active_prov:
            ai_engine_info = {
                'has_key': False,
                'status': 'unconfigured',
                'badge_text': 'No Engine Configured',
                'badge_color': 'danger',
                'engine_name': 'None',
                'model_name': 'None',
                'provider_type': 'gemini',
            }
        elif not has_key:
            ai_engine_info = {
                'has_key': False,
                'status': 'missing_key',
                'badge_text': f'{active_prov.model_name or active_prov.name} · Key Missing',
                'badge_color': 'warning',
                'engine_name': active_prov.name,
                'model_name': active_prov.model_name or 'Not set',
                'provider_type': active_prov.provider_type,
            }
        else:
            model_disp = active_prov.model_name or active_prov.name
            ai_engine_info = {
                'has_key': True,
                'status': 'connected',
                'badge_text': f'{model_disp} · Active',
                'badge_color': 'success',
                'engine_name': active_prov.name,
                'model_name': model_disp,
                'provider_type': active_prov.provider_type,
            }
        return {
            'ai_engine': ai_engine_info,
                        'total_jobs': total_jobs,
            'total_transactions': total_txns,
            'accuracy_rate': avg_confidence,
            'active_tasks': len(statements.filtered(lambda s: s.state in ('draft', 'parsed', 'reviewed'))),
            'recent_statements': recent_list,
            'invoice_queue': {
                'customer_invoices_count': cust_count,
                'customer_invoices_amount': cust_amount,
                'vendor_bills_count': bill_count,
                'vendor_bills_amount': bill_amount,
                'total_pending_count': cust_count + bill_count,
                'total_pending_amount': cust_amount + bill_amount,
            },
            'active_workspace': {
                'user_name': user.name,
                'company_name': company.name,
                'role': 'Manager' if user.has_group('base.group_erp_manager') else 'Accountant',
                'status': 'Active',
            }
        }
    @http.route('/gsus_bank_ai/get_invoice_queues', type='json', auth='user')
    def get_invoice_queues(self):
        """Dedicated endpoint to fetch live real open customer invoices & vendor bills."""
        company = request.env.company
        inv_domain = [
            ('state', '=', 'posted'),
            ('payment_state', 'in', ('not_paid', 'partial')),
            ('move_type', 'in', ('out_invoice', 'in_invoice')),
            '|', ('company_id', '=', False), ('company_id', '=', company.id)
        ]
        open_invoices = request.env['account.move'].sudo().search(inv_domain)
        cust_invoices = open_invoices.filtered(lambda m: m.move_type == 'out_invoice')
        vendor_bills = open_invoices.filtered(lambda m: m.move_type == 'in_invoice')
        cust_count = len(cust_invoices)
        cust_amount = sum(cust_invoices.mapped('amount_residual'))
        bill_count = len(vendor_bills)
        bill_amount = sum(vendor_bills.mapped('amount_residual'))
        return {
            'success': True,
            'customer_invoices_count': cust_count,
            'customer_invoices_amount': cust_amount,
            'vendor_bills_count': bill_count,
            'vendor_bills_amount': bill_amount,
            'total_pending_count': cust_count + bill_count,
            'total_pending_amount': cust_amount + bill_amount,
            'currency': company.currency_id.symbol or '₹',
        }
    @http.route('/gsus_bank_ai/get_statement_data', type='json', auth='user')
    def get_statement_data(self, statement_id=None, filter_tab='all', page=1, limit=250):
        Statement = request.env['gsus.bank.statement.ai'].sudo()
        if statement_id:
            statement = Statement.browse(int(statement_id))
        else:
            statement = Statement.search([], limit=1, order='create_date desc, id desc')
        if not statement or not statement.exists():
            return {
                'kpis': {
                    'statement_id': 0,
                    'statement_name': 'No Statement Loaded',
                    'total_transactions': 0,
                    'total_debit': 0.0,
                    'total_credit': 0.0,
                    'net_flow': 0.0,
                    'assigned_count': 0,
                    'reviewed_count': 0,
                    'unassigned_count': 0,
                    'pushed_count': 0,
                    'confidence_avg': 0,
                    'state': 'draft',
                    'bank_name': 'No Bank Selected',
                    'opening_balance': 0.0,
                    'closing_balance': 0.0,
                    'recomputed_closing_balance': 0.0,
                    'verification_state': 'unchecked',
                    'verification_notes': 'No Statement Loaded',
                    'account_bank_statement_id': False,
                    'last_error_message': '',
                },
                'lines': [],
                'total': 0,
                'page': 1,
                'pages': 1,
            }
        # Auto-heal opening balance if missing or 0.0 but transactions exist
        if (not statement.opening_balance or statement.opening_balance == 0.0) and statement.line_ids:
            first_l = statement.line_ids.sorted(lambda l: (l.date, l.sequence, l.id))[:1]
            if first_l and first_l.balance:
                derived_opening = round(first_l.balance - first_l.credit + first_l.debit, 2)
                statement.write({'opening_balance': derived_opening})
            elif statement.closing_balance and (statement.total_credit or statement.total_debit):
                derived_opening = round(statement.closing_balance - statement.total_credit + statement.total_debit, 2)
                statement.write({'opening_balance': derived_opening})
        # Anomaly and Duplicate Analysis (Calibrated for High Precision)
        all_lines = statement.line_ids
        seen_refs = {}
        seen_exact = {}
        for l in all_lines:
            ref_clean = (l.reference or '').strip().upper()
            if ref_clean and len(ref_clean) >= 6:
                seen_refs[ref_clean] = seen_refs.get(ref_clean, 0) + 1
            # Exact combination: same date + same amount + same direction + same narration prefix
            exact_key = (l.date, round(l.amount, 2), l.debit > 0, (l.narration or '').strip().upper()[:30])
            seen_exact[exact_key] = seen_exact.get(exact_key, 0) + 1
        anomaly_line_ids = []
        for l in all_lines:
            ref_clean = (l.reference or '').strip().upper()
            is_dup_ref = bool(ref_clean and len(ref_clean) >= 6 and seen_refs.get(ref_clean, 0) > 1)
            exact_key = (l.date, round(l.amount, 2), l.debit > 0, (l.narration or '').strip().upper()[:30])
            is_dup_exact = bool(seen_exact.get(exact_key, 0) > 1)
            is_high = bool(l.amount > 500000.0 and len(all_lines) > 5)
            if is_dup_ref or is_dup_exact or is_high:
                anomaly_line_ids.append(l.id)
        anomalies_count = len(anomaly_line_ids)
        domain = [('statement_id', '=', statement.id)]
        if filter_tab == 'suggested':
            domain.append(('status', '=', 'suggested'))
        elif filter_tab == 'reviewed':
            domain.append(('status', '=', 'reviewed'))
        elif filter_tab == 'not_assigned':
            domain.append(('status', '=', 'pending'))
        elif filter_tab == 'pushed':
            domain.append(('status', '=', 'pushed'))
        elif filter_tab == 'anomalies':
            domain.append(('id', 'in', anomaly_line_ids or [-1]))
        total_matching = request.env['gsus.bank.statement.ai.line'].sudo().search_count(domain)
        offset = (page - 1) * limit
        lines = request.env['gsus.bank.statement.ai.line'].sudo().search(
            domain, offset=offset, limit=limit, order='date asc, sequence asc, id asc'
        )
        line_list = []
        for l in lines:
            ref_clean = (l.reference or '').strip().upper()
            is_dup_ref = bool(ref_clean and len(ref_clean) >= 6 and seen_refs.get(ref_clean, 0) > 1)
            exact_key = (l.date, round(l.amount, 2), l.debit > 0, (l.narration or '').strip().upper()[:30])
            is_dup_exact = bool(seen_exact.get(exact_key, 0) > 1)
            is_dup = is_dup_ref or is_dup_exact
            # Outlier Spike: only flag if amount exceeds ₹5,00,000 to prevent false flags on normal payments
            is_high = bool(l.amount > 500000.0 and len(all_lines) > 5)
            is_anom = is_dup or is_high
            anom_reason = 'Duplicate UTR Reference' if is_dup_ref else ('Duplicate Transaction (Same Date, Amount & Narration)' if is_dup_exact else ('High Value Spike (> ₹5,00,000)' if is_high else ''))
            ttype = l.transaction_type or 'unknown'
            ttype_sel = dict(l._fields['transaction_type'].selection) if 'transaction_type' in l._fields else {}
            cstatus = l.contact_status or 'needs_review'
            cstatus_sel = dict(l._fields['contact_status'].selection) if 'contact_status' in l._fields else {}
            line_list.append({
                'id': l.id,
                'date': str(l.date),
                'narration': l.narration,
                'reference': l.reference or '',
                'payment_mode': l.payment_mode or 'other',
                'debit': l.debit,
                'credit': l.credit,
                'amount': l.amount,
                'balance': l.balance,
                'counterparty': l.counterparty or l.group_key or '',
                'partner_id': l.partner_id.id if l.partner_id else False,
                'partner_name': l.partner_id.name if l.partner_id else 'Not assigned',
                'account_id': l.account_id.id if l.account_id else False,
                'account_name': l.account_id.display_name if l.account_id else 'Not assigned',
                'confidence': l.confidence_percent,
                'status': l.status,
                'group_key': l.group_key or '',
                'group_remark': l.group_remark or l.user_remarks or '',
                'user_remarks': l.user_remarks or '',
                'is_duplicate': is_dup,
                'is_anomaly': is_anom,
                'anomaly_reason': anom_reason,
                'suggestion_source': l.suggestion_source or 'fuzzy',
                'ai_reason': l.ai_reason or '',
                'transaction_type': ttype,
                'transaction_type_label': ttype_sel.get(ttype, ttype.replace('_', ' ').title()),
                'counterparty_type': l.counterparty_type or 'none',
                'contact_status': cstatus,
                'contact_status_label': cstatus_sel.get(cstatus, cstatus.replace('_', ' ').title()),
                'approval_target': l.approval_target or 'none',
                'proposed_contact_name': l.proposed_contact_name or l.new_contact_name or l.counterparty or '',
                'proposed_upi_id': l.proposed_upi_id or '',
                'proposed_bank_account': l.proposed_bank_account or '',
                'classification_confidence': int(round((l.classification_confidence or 0.0) * 100)),
                'classification_reason': l.classification_reason or '',
                'contact_approved_by': l.contact_approved_by.name if l.contact_approved_by else '',
                'contact_approved_date': str(l.contact_approved_date) if l.contact_approved_date else '',
            })
        # Summary KPIs
        kpis = {
            'statement_id': statement.id,
            'statement_name': statement.name,
            'total_transactions': statement.total_transactions,
            'total_debit': statement.total_debit,
            'total_credit': statement.total_credit,
            'net_flow': statement.net_flow,
            'assigned_count': statement.assigned_count,
            'reviewed_count': statement.reviewed_count,
            'unassigned_count': statement.unassigned_count,
            'pushed_count': statement.pushed_count,
            'anomalies_count': anomalies_count,
            'confidence_avg': statement.confidence_avg,
            'state': statement.state,
            'bank_name': statement.bank_name or 'Bank Statement',
            'opening_balance': statement.opening_balance,
            'closing_balance': statement.closing_balance,
            'recomputed_closing_balance': statement.recomputed_closing_balance,
            'verification_state': statement.verification_state or 'unchecked',
            'verification_notes': statement.verification_notes or '',
            'account_bank_statement_id': statement.account_bank_statement_id.id if statement.account_bank_statement_id else False,
            'last_error_message': statement.last_error_message or '',
        }
        return {
            'kpis': kpis,
            'lines': line_list,
            'total': total_matching,
            'page': page,
            'pages': (total_matching + limit - 1) // limit if limit else 1,
        }
    @http.route('/gsus_bank_ai/update_line', type='json', auth='user')
    def update_line(self, line_id, partner_id=None, account_id=None, status=None, **kw):
        line = request.env['gsus.bank.statement.ai.line'].sudo().browse(line_id)
        if not line.exists():
            return {'error': 'Line not found'}
        vals = {}
        if partner_id is not None:
            vals['partner_id'] = partner_id
            if partner_id:
                vals['contact_status'] = 'existing'
        if account_id is not None:
            vals['account_id'] = account_id
        if status:
            vals['status'] = status
            vals['confidence'] = 1.0
        partner_name = kw.get('partner_name') or kw.get('proposed_contact_name')
        if partner_name and not partner_id:
            c_name = partner_name.strip()
            # If line already has a partner, update that partner's name!
            if line.partner_id:
                line.partner_id.sudo().write({'name': c_name})
                vals['partner_id'] = line.partner_id.id
                vals['proposed_contact_name'] = c_name
                vals['contact_status'] = 'existing'
            else:
                existing_p = request.env['res.partner'].sudo().search([
                    ('name', '=ilike', c_name),
                    '|', ('company_id', '=', False), ('company_id', '=', line.company_id.id)
                ], limit=1)
                if existing_p:
                    vals['partner_id'] = existing_p.id
                    vals['contact_status'] = 'existing'
                    vals['proposed_contact_name'] = existing_p.name
                else:
                    target = 'vendor' if line.debit > 0 else 'customer'
                    new_p = request.env['res.partner'].sudo().create({
                        'name': c_name,
                        'company_id': line.company_id.id or request.env.company.id,
                        'customer_rank': 1 if target == 'customer' else 0,
                        'supplier_rank': 1 if target == 'vendor' else 0,
                    })
                    vals['partner_id'] = new_p.id
                    vals['proposed_contact_name'] = new_p.name
                    vals['contact_status'] = 'existing'
                    vals['approval_target'] = target
                    vals['counterparty_type'] = target
        for f in ('contact_status', 'approval_target', 'transaction_type', 'proposed_contact_name'):
            if f in kw and kw[f] is not None and f not in vals:
                vals[f] = kw[f]
        if kw.get('contact_status') == 'approved':
            vals['contact_approved_by'] = request.env.user.id
            vals['contact_approved_date'] = fields.Datetime.now()
            vals['status'] = 'reviewed'
        line.write(vals)
        # Learn to memory if both partner and account are confirmed
        if (partner_id or account_id) and line.counterparty:
            Memory = request.env['gsus.bank.ai.memory'].sudo()
            direction = 'debit' if line.debit > 0 else 'credit'
            company_id = line.company_id.id or request.env.company.id
            Memory.record_confirmation(
                counterparty_key=line.counterparty,
                direction=direction,
                company_id=company_id,
                partner_id=line.partner_id.id if line.partner_id else False,
                account_id=line.account_id.id if line.account_id else False
            )
        return {'success': True, 'id': line.id, 'status': line.status}
    @http.route('/gsus_bank_ai/delete_line', type='json', auth='user')
    def delete_line(self, line_id):
        line = request.env['gsus.bank.statement.ai.line'].sudo().browse(int(line_id))
        if line.exists():
            st = line.statement_id
            line.unlink()
            st._compute_kpis()
            st._compute_verification()
            return {'success': True}
        return {'error': 'Line not found'}
    @http.route('/gsus_bank_ai/add_line', type='json', auth='user')
    def add_line(self, statement_id, date=None, narration='Manual Entry', debit=0.0, credit=0.0, balance=0.0):
        statement = request.env['gsus.bank.statement.ai'].sudo().browse(int(statement_id))
        if not statement.exists():
            return {'error': 'Statement not found'}
        Line = request.env['gsus.bank.statement.ai.line'].sudo()
        new_line = Line.create({
            'statement_id': statement.id,
            'date': date or fields.Date.context_today(statement),
            'narration': narration or 'Manual Transaction',
            'debit': float(debit or 0.0),
            'credit': float(credit or 0.0),
            'balance': float(balance or 0.0),
            'status': 'pending',
            'suggestion_source': 'manual',
        })
        statement._compute_kpis()
        statement._compute_verification()
        return {'success': True, 'line_id': new_line.id}
    @http.route('/gsus_bank_ai/get_groups', type='json', auth='user')
    def get_groups(self, statement_id):
        statement = request.env['gsus.bank.statement.ai'].sudo().browse(int(statement_id))
        if not statement.exists():
            return {'groups': []}
        # Include all unpushed lines, or all lines if all are pushed
        lines = statement.line_ids.filtered(lambda l: l.status != 'pushed')
        if not lines:
            lines = statement.line_ids
        # Auto-heal any lines where contact was edited or matched to an existing partner
        for l in lines:
            if not l.partner_id and l.proposed_contact_name:
                p = request.env['res.partner'].sudo().search([
                    '|', ('name', '=ilike', l.proposed_contact_name.strip()),
                    '|', ('name', '=ilike', (l.counterparty or '').strip()),
                         ('name', '=ilike', (l.group_key or '').strip()),
                    '|', ('company_id', '=', False), ('company_id', '=', statement.company_id.id)
                ], limit=1)
                if p:
                    if l.proposed_contact_name.strip() and p.name != l.proposed_contact_name.strip():
                        p.sudo().write({'name': l.proposed_contact_name.strip()})
                    l.sudo().write({'partner_id': p.id, 'contact_status': 'existing'})
        BANK_IFSC = {
            'YESB', 'TMBL', 'UTIB', 'FDRL', 'SBIN', 'ICIC', 'HDFC', 'KKBK',
            'BARB', 'PUNB', 'CNRB', 'IOBA', 'IDIB', 'UBIN', 'CBIN', 'VIJB',
            'CORP', 'ALLA', 'ANDB', 'SYNB', 'MAHB', 'PSIB', 'BDBL', 'IDFB',
            'PAYTM', 'PYTM', 'AIRP', 'JIOP', 'IPOS', 'CITI', 'HSBC', 'SCBL'
        }
        groups_dict = {}
        for l in lines:
            gk = l.group_key
            if not gk or gk.strip().upper() in BANK_IFSC or gk == 'GENERAL':
                if l.counterparty and l.counterparty.strip().upper() not in BANK_IFSC:
                    gk = l.counterparty.strip().upper()
                elif l.proposed_contact_name and l.proposed_contact_name.strip().upper() not in BANK_IFSC:
                    gk = l.proposed_contact_name.strip().upper()
                else:
                    gk = l.group_key or 'GENERAL'
            sug_partner = l.partner_id.name if l.partner_id else (l.proposed_contact_name or l.counterparty or '')
            if sug_partner and sug_partner.strip().upper() in BANK_IFSC:
                sug_partner = ''
            if gk not in groups_dict:
                groups_dict[gk] = {
                    'group_key': gk,
                    'count': 0,
                    'total_amount': 0.0,
                    'total_debit': 0.0,
                    'total_credit': 0.0,
                    'sample_narration': l.narration,
                    'payment_mode': (l.payment_mode or 'other').upper(),
                    'suggested_partner': sug_partner,
                    'suggested_account': l.account_id.display_name if l.account_id else '',
                    'partner_id': l.partner_id.id if l.partner_id else False,
                    'account_id': l.account_id.id if l.account_id else False,
                    'group_remark': l.group_remark or l.user_remarks or '',
                    'line_ids': [],
                }
            groups_dict[gk]['count'] += 1
            groups_dict[gk]['total_amount'] += l.amount
            groups_dict[gk]['total_debit'] += (l.debit or 0.0)
            groups_dict[gk]['total_credit'] += (l.credit or 0.0)
            groups_dict[gk]['line_ids'].append(l.id)
            if not groups_dict[gk]['suggested_partner'] and sug_partner:
                groups_dict[gk]['suggested_partner'] = sug_partner
            groups_dict[gk]['primary_type'] = 'vendor' if groups_dict[gk]['total_debit'] >= groups_dict[gk]['total_credit'] else 'customer' 
        for g in groups_dict.values():
            grp_lines = statement.line_ids.filtered(lambda l: l.id in g['line_ids'])
            if all(l.contact_status == 'approved' for l in grp_lines):
                g['contact_status'] = 'approved'
                g['approval_target'] = grp_lines[0].approval_target if grp_lines else g['primary_type']
            elif any(l.partner_id or l.contact_status == 'existing' for l in grp_lines):
                g['contact_status'] = 'existing'
            else:
                g['contact_status'] = grp_lines[0].contact_status if grp_lines else 'new_proposed'
        sorted_groups = sorted(groups_dict.values(), key=lambda g: g['count'], reverse=True)
        return {'groups': sorted_groups[:50]}
    @http.route('/gsus_bank_ai/update_group_contact_name', type='json', auth='user')
    def update_group_contact_name(self, statement_id, group_key, new_contact_name):
        statement = request.env['gsus.bank.statement.ai'].sudo().browse(int(statement_id))
        if not statement.exists():
            return {'error': 'Statement not found'}
        lines = statement.line_ids.filtered(lambda l: (l.counterparty == group_key or l.group_key == group_key))
        cleaned_name = (new_contact_name or '').strip()
        if not cleaned_name:
            return {'error': 'Contact name cannot be empty'}
        # 1. Did these lines or this group already have an existing partner linked?
        existing_linked_partners = lines.mapped('partner_id')
        if not existing_linked_partners and group_key:
            # Check if group_key or previous counterparty matched an existing partner
            partner_by_group = request.env['res.partner'].sudo().search([
                ('name', '=ilike', group_key.strip()),
                '|', ('company_id', '=', False), ('company_id', '=', statement.company_id.id)
            ], limit=1)
            if partner_by_group:
                existing_linked_partners = partner_by_group
        # If an existing partner was already connected, RENAME that existing partner in Odoo!
        if existing_linked_partners:
            target_p = existing_linked_partners[0]
            old_name = target_p.name
            target_p.sudo().write({'name': cleaned_name})
            lines.write({
                'partner_id': target_p.id,
                'proposed_contact_name': cleaned_name,
                'counterparty': cleaned_name,
                'contact_status': 'existing',
                'status': 'reviewed',
            })
            return {
                'success': True,
                'updated_existing': True,
                'matched_existing': True,
                'partner_id': target_p.id,
                'partner_name': cleaned_name,
                'contact_status': 'existing',
                'message': f"Updated contact to '{cleaned_name}' in Odoo.",
            }
        # 2. Check if the entered name matches an existing partner in Odoo
        existing_partner = request.env['res.partner'].sudo().search([
            ('name', '=ilike', cleaned_name),
            '|', ('company_id', '=', False), ('company_id', '=', statement.company_id.id)
        ], limit=1)
        if existing_partner:
            lines.write({
                'partner_id': existing_partner.id,
                'proposed_contact_name': existing_partner.name,
                'counterparty': existing_partner.name,
                'contact_status': 'existing',
                'status': 'reviewed',
            })
            return {
                'success': True,
                'matched_existing': True,
                'partner_id': existing_partner.id,
                'partner_name': existing_partner.name,
                'contact_status': 'existing',
                'message': f"Assigned to existing contact '{existing_partner.name}'.",
            }
        else:
            # 3. Not in existing: Create new contact in Odoo immediately with the entered name!
            target_type = 'vendor' if any(l.debit > 0 for l in lines) else 'customer'
            new_partner = request.env['res.partner'].sudo().create({
                'name': cleaned_name,
                'company_id': statement.company_id.id,
                'customer_rank': 1 if target_type == 'customer' else 0,
                'supplier_rank': 1 if target_type == 'vendor' else 0,
            })
            lines.write({
                'partner_id': new_partner.id,
                'proposed_contact_name': new_partner.name,
                'counterparty': new_partner.name,
                'contact_status': 'existing',
                'approval_target': target_type,
                'counterparty_type': target_type,
                'status': 'reviewed',
            })
            return {
                'success': True,
                'created_new': True,
                'matched_existing': True,
                'partner_id': new_partner.id,
                'partner_name': new_partner.name,
                'contact_status': 'existing',
                'approval_target': target_type,
                'message': f"Created new contact '{new_partner.name}' in Odoo.",
            }
    @http.route('/gsus_bank_ai/resolve_group', type='json', auth='user')
    def resolve_group(self, statement_id, group_key, partner_id=None, account_id=None, group_remark=None, approve_as=None, proposed_name=None):
        statement = request.env['gsus.bank.statement.ai'].sudo().browse(int(statement_id))
        if not statement.exists():
            return {'error': 'Statement not found'}
        lines = statement.line_ids.filtered(lambda l: (l.counterparty == group_key or l.group_key == group_key) and l.status != 'pushed')
        if not lines:
            lines = statement.line_ids.filtered(lambda l: l.counterparty == group_key or l.group_key == group_key)
        vals = {'status': 'reviewed', 'confidence': 1.0}
        if partner_id:
            vals['partner_id'] = int(partner_id)
            vals['contact_status'] = 'existing'
        if account_id:
            vals['account_id'] = int(account_id)
        if group_remark is not None:
            vals['group_remark'] = group_remark
            vals['user_remarks'] = group_remark
        if approve_as in ('vendor', 'customer'):
            vals['contact_status'] = 'approved'
            vals['approval_target'] = approve_as
            vals['counterparty_type'] = approve_as
            vals['contact_approved_by'] = request.env.user.id
            vals['contact_approved_date'] = fields.Datetime.now()
            if proposed_name:
                vals['proposed_contact_name'] = proposed_name
        lines.write(vals)
        statement._compute_kpis()
        # AI Memory Learning
        if (partner_id or account_id) and lines:
            Memory = request.env['gsus.bank.ai.memory'].sudo()
            direction = 'debit' if any(l.debit > 0 for l in lines) else 'credit'
            company_id = statement.company_id.id or request.env.company.id
            Memory.record_confirmation(
                counterparty_key=group_key,
                direction=direction,
                company_id=company_id,
                partner_id=partner_id,
                account_id=account_id
            )
        return {'success': True, 'resolved_count': len(lines)}
    @http.route('/gsus_bank_ai/inspect_file', type='json', auth='user')
    def inspect_file(self, file_data, file_name='statement.pdf', pdf_password=''):
        """Instant in-memory pre-inspection to detect encryption, page count, and bank signature in < 100ms."""
        import base64
        import io
        result = {
            'success': True,
            'file_name': file_name or 'statement.pdf',
            'file_size_kb': 0,
            'page_count': 0,
            'detected_bank': '',
            'is_encrypted': False,
            'is_decrypted': True,
        }
        try:
            raw_bytes = base64.b64decode(file_data)
            result['file_size_kb'] = round(len(raw_bytes) / 1024, 2)
            import hashlib
            file_hash = hashlib.sha256(raw_bytes).hexdigest()
            company_id = request.env.company.id
            existing = request.env['gsus.bank.statement.ai'].sudo().search([
                ('file_hash', '=', file_hash),
                ('company_id', '=', company_id),
            ], limit=1, order='id desc')
            if existing:
                result['is_duplicate'] = True
                result['existing_statement_id'] = existing.id
                result['existing_statement_name'] = existing.name
                result['existing_statement_state'] = existing.state
                result['duplicate_warning'] = f"Duplicate Detected: This statement was already uploaded as '{existing.name}' (ID #{existing.id}, Status: {existing.state.upper()})."
            bank_specs = [
                ('HDFC Bank', ['HDFC BANK', 'HDFC0', 'HDFCBANK'], ['HDFC']),
                ('State Bank of India', ['STATE BANK OF INDIA', 'SBIN0', 'STATE BANK'], ['SBI']),
                ('Axis Bank', ['AXIS BANK', 'UTIB0', 'AXISBANK'], ['AXIS']),
                ('ICICI Bank', ['ICICI BANK', 'ICIC0', 'ICICIBANK'], ['ICICI']),
                ('Kotak Mahindra Bank', ['KOTAK MAHINDRA BANK', 'KOTAK MAHINDRA', 'KKBK0'], ['KOTAK']),
                ('Canara Bank', ['CANARA BANK', 'CNRB0'], ['CANARA']),
                ('Bank of Baroda', ['BANK OF BARODA', 'BARB0'], ['BARODA', 'BOB']),
                ('Punjab National Bank', ['PUNJAB NATIONAL BANK', 'PUNB0', 'PUNJAB NATIONAL'], ['PNB']),
                ('Union Bank of India', ['UNION BANK OF INDIA', 'UBIN0'], ['UNION BANK']),
                ('Federal Bank', ['FEDERAL BANK', 'FDRL0'], ['FEDERAL']),
                ('IndusInd Bank', ['INDUSIND BANK', 'INDB0'], ['INDUSIND']),
                ('Yes Bank', ['YES BANK', 'YESB0'], ['YESBANK']),
                ('IDFC FIRST Bank', ['IDFC FIRST BANK', 'IDFB0', 'IDFC FIRST'], ['IDFC']),
                ('Indian Overseas Bank', ['INDIAN OVERSEAS BANK', 'IOBA0'], ['IOB']),
                ('Indian Bank', ['INDIAN BANK', 'IDIB0'], []),
                ('AU Small Finance Bank', ['AU SMALL FINANCE', 'AUBL0', 'AU SMALL'], []),
            ]
            # --- UNIVERSAL MULTI-TIER PDF INSPECTION & DECRYPTION ENGINE ---
            # Tier 0: Pure binary signature check (works on all OS/containers with 0 dependencies)
            if b'/Encrypt' in raw_bytes:
                result['is_encrypted'] = True
                result['is_decrypted'] = False

            pdf_reader = None
            pdf_engine = None

            # Tier 1: Modern pypdf (Default standard in Odoo 17/18/20 and Odoo.sh)
            try:
                import pypdf
                pdf_reader = pypdf.PdfReader(io.BytesIO(raw_bytes))
                pdf_engine = 'pypdf'
            except Exception:
                pass

            # Tier 2: Legacy PyPDF2 fallback
            if not pdf_reader:
                try:
                    import PyPDF2
                    pdf_reader = PyPDF2.PdfReader(io.BytesIO(raw_bytes))
                    pdf_engine = 'PyPDF2'
                except Exception:
                    pass

            # Tier 3: PyMuPDF / fitz fallback
            if not pdf_reader:
                try:
                    import pymupdf
                    pdf_reader = pymupdf.open(stream=raw_bytes, filetype="pdf")
                    pdf_engine = 'pymupdf'
                except Exception:
                    try:
                        import fitz
                        pdf_reader = fitz.open(stream=raw_bytes, filetype="pdf")
                        pdf_engine = 'fitz'
                    except Exception:
                        pass

            if pdf_engine in ('pypdf', 'PyPDF2'):
                try:
                    is_enc = bool(getattr(pdf_reader, 'is_encrypted', getattr(pdf_reader, 'isEncrypted', False)))
                    if is_enc:
                        result['is_encrypted'] = True
                        result['is_decrypted'] = False
                        if pdf_password:
                            pwd = str(pdf_password).strip()
                            dec = 0
                            try:
                                dec = pdf_reader.decrypt(pwd)
                            except Exception:
                                pass
                            if dec == 0:
                                try:
                                    dec = pdf_reader.decrypt(pwd.upper()) or pdf_reader.decrypt(pwd.lower())
                                except Exception:
                                    pass
                            if dec != 0:
                                result['is_decrypted'] = True
                    if result['is_decrypted']:
                        result['page_count'] = len(pdf_reader.pages)
                        first_page_text = (pdf_reader.pages[0].extract_text() or "") if len(pdf_reader.pages) > 0 else ""
                        all_pages_text = ""
                        for p_idx in range(min(3, len(pdf_reader.pages))):
                            all_pages_text += " " + (pdf_reader.pages[p_idx].extract_text() or "")
                        header_corpus = first_page_text[:600].upper()
                        import re
                        cleaned_corpus = re.sub(r'@[A-Z0-9\._-]+', '', all_pages_text.upper())
                        cleaned_header = re.sub(r'@[A-Z0-9\._-]+', '', header_corpus)
                        scores = {}
                        for bname, strong_kws, weak_kws in bank_specs:
                            score = 0
                            for kw in strong_kws:
                                if kw in cleaned_header:
                                    score += 25
                                elif kw in cleaned_corpus:
                                    score += 10
                            for kw in weak_kws:
                                if re.search(r'\b' + re.escape(kw) + r'\b', cleaned_header):
                                    score += 15
                                elif re.search(r'\b' + re.escape(kw) + r'\b', cleaned_corpus):
                                    score += 4
                            if score > 0:
                                scores[bname] = score
                        if scores:
                            best_bank = max(scores, key=scores.get)
                            result['detected_bank'] = best_bank
                except Exception as e:
                    _logger.warning("PDF reader processing warning: %s", str(e))
            elif pdf_engine in ('pymupdf', 'fitz'):
                try:
                    if getattr(pdf_reader, 'is_encrypted', False):
                        result['is_encrypted'] = True
                        result['is_decrypted'] = False
                        if pdf_password:
                            pwd = str(pdf_password).strip()
                            auth = pdf_reader.authenticate(pwd)
                            if not auth:
                                auth = pdf_reader.authenticate(pwd.upper()) or pdf_reader.authenticate(pwd.lower())
                            if auth:
                                result['is_decrypted'] = True
                    if result['is_decrypted']:
                        result['page_count'] = len(pdf_reader)
                        first_page_text = pdf_reader[0].get_text() if len(pdf_reader) > 0 else ""
                        all_pages_text = ""
                        for p_idx in range(min(3, len(pdf_reader))):
                            all_pages_text += " " + pdf_reader[p_idx].get_text()
                        header_corpus = first_page_text[:600].upper()
                        import re
                        cleaned_corpus = re.sub(r'@[A-Z0-9\._-]+', '', all_pages_text.upper())
                        cleaned_header = re.sub(r'@[A-Z0-9\._-]+', '', header_corpus)
                        scores = {}
                        for bname, strong_kws, weak_kws in bank_specs:
                            score = 0
                            for kw in strong_kws:
                                if kw in cleaned_header:
                                    score += 25
                                elif kw in cleaned_corpus:
                                    score += 10
                            for kw in weak_kws:
                                if re.search(r'\b' + re.escape(kw) + r'\b', cleaned_header):
                                    score += 15
                                elif re.search(r'\b' + re.escape(kw) + r'\b', cleaned_corpus):
                                    score += 4
                            if score > 0:
                                scores[bname] = score
                        if scores:
                            best_bank = max(scores, key=scores.get)
                            result['detected_bank'] = best_bank
                except Exception as e:
                    _logger.warning("PyMuPDF reader processing warning: %s", str(e))

            if not result['detected_bank']:
                fn_upper = (file_name or '').upper()
                for bname, strong_kws, weak_kws in bank_specs:
                    for kw in strong_kws + weak_kws:
                        if kw in fn_upper:
                            result['detected_bank'] = bname
                            break
                    if result['detected_bank']:
                        break
            return result
        except Exception as e:
            return {'success': False, 'error': str(e), 'page_count': 0, 'detected_bank': '', 'is_encrypted': False, 'is_decrypted': True}
    @http.route('/gsus_bank_ai/upload_and_parse', type='json', auth='user')
    def upload_and_parse(self, file_data, file_name='statement.pdf', pdf_password='', bank_name='', force_duplicate=False):
        """Direct in-workbench upload & parse endpoint without default Odoo dialog."""
        import base64
        import hashlib
        raw_bytes = base64.b64decode(file_data)
        file_hash = hashlib.sha256(raw_bytes).hexdigest()
        Statement = request.env['gsus.bank.statement.ai'].sudo()
        company_id = request.env.company.id or request.env.user.company_id.id
        # ─── DUPLICATE STATEMENT DETECTION ───
        existing = Statement.search([
            ('file_hash', '=', file_hash),
            ('company_id', '=', company_id),
        ], limit=1, order='id desc')
        if existing and not force_duplicate:
            if existing.state == 'pushed':
                return {
                    'success': False,
                    'error': f"Duplicate Statement Blocked! This statement '{existing.name}' has already been processed and pushed to Odoo Accounting (ID #{existing.id}).",
                    'is_duplicate': True,
                    'statement_id': existing.id,
                }
            else:
                return {
                    'success': True,
                    'statement_id': existing.id,
                    'total_transactions': existing.total_transactions,
                    'bank_name': existing.bank_name or bank_name or 'Bank',
                    'is_duplicate': True,
                    'message': f"Opening existing staging session for this statement (ID #{existing.id}).",
                }
        clean_bank = bank_name if bank_name and 'AUTO-DETECT' not in bank_name.upper() else ''
        vals = {
            'name': file_name or 'Bank Statement',
            'company_id': company_id,
            'file_data': file_data,
            'file_name': file_name,
            'pdf_password': pdf_password,
            'file_hash': file_hash,
        }
        if clean_bank:
            vals['bank_name'] = clean_bank
        session = Statement.create(vals)
        try:
            session.action_parse_statement()
        except Exception as e:
            session.last_error_message = str(e)
            return {'success': False, 'error': str(e), 'statement_id': session.id}
        finally:
            if session.pdf_password:
                session.pdf_password = False
        return {
            'success': True,
            'statement_id': session.id,
            'total_transactions': session.total_transactions,
            'bank_name': session.bank_name or clean_bank or 'Bank',
        }
    @http.route('/gsus_bank_ai/delete_statement', type='json', auth='user')

    def delete_statement(self, statement_id):

        statement = request.env['gsus.bank.statement.ai'].sudo().browse(int(statement_id))

        if statement.exists():

            statement.unlink()

            return {'success': True}

        return {'error': 'Statement not found'}
    @http.route('/gsus_bank_ai/search_partners', type='json', auth='user')
    def search_partners(self, query='', limit=15):
        company_id = request.env.company.id
        domain = ['|', ('company_id', '=', False), ('company_id', '=', company_id)]
        if query:
            domain.append(('name', 'ilike', query))
        partners = request.env['res.partner'].sudo().search_read(domain, ['id', 'name'], limit=limit)
        return partners
    @http.route('/gsus_bank_ai/search_accounts', type='json', auth='user')
    def search_accounts(self, query='', limit=15):
        company_id = request.env.company.id
        domain = [('company_ids', 'in', [company_id])]
        if query:
            domain.append('|')
            domain.append(('name', 'ilike', query))
            domain.append(('code', 'ilike', query))
        accounts = request.env['account.account'].sudo().search_read(domain, ['id', 'name', 'code'], limit=limit)
        return accounts
    @http.route('/gsus_bank_ai/chat_command', type='json', auth='user')
    def chat_command(self, statement_id, prompt):
        statement = request.env['gsus.bank.statement.ai'].sudo().browse(int(statement_id))
        if not statement.exists():
            return {'reply': 'Statement session not found.'}
        res = statement.action_chat_batch_command(prompt)
        return res
    @http.route('/gsus_bank_ai/export_csv', type='http', auth='user')
    def export_csv(self, statement_id):
        import csv
        import io
        statement = request.env['gsus.bank.statement.ai'].sudo().browse(int(statement_id))
        if not statement.exists():
            return request.not_found()
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Date', 'Mode', 'Narration', 'Reference', 'Debit', 'Credit', 'Balance', 'Assigned Contact', 'Assigned Ledger', 'Confidence %', 'Status'])
        for l in statement.line_ids:
            writer.writerow([
                l.date,
                (l.payment_mode or '').upper(),
                l.narration,
                l.reference or '',
                l.debit,
                l.credit,
                l.balance,
                l.partner_id.name if l.partner_id else '',
                l.account_id.display_name if l.account_id else '',
                l.confidence_percent,
                l.status,
            ])
        csv_data = output.getvalue().encode('utf-8-sig')
        filename = f"{statement.bank_name or 'Bank'}_Statement_{statement.id}.csv"
        return request.make_response(
            csv_data,
            headers=[
                ('Content-Type', 'text/csv; charset=utf-8'),
                ('Content-Disposition', f'attachment; filename="{filename}"'),
            ]
        )
    @http.route('/gsus_bank_ai/export_excel', type='http', auth='user')
    def export_excel(self, statement_id):
        import io
        import xlsxwriter
        statement = request.env['gsus.bank.statement.ai'].sudo().browse(int(statement_id))
        if not statement.exists():
            return request.not_found()
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        worksheet = workbook.add_worksheet('Bank Transactions')
        # Odoo 20 Native Purple Branding Palette
        title_fmt = workbook.add_format({'bold': True, 'font_size': 14, 'font_color': '#714B67'})
        subtitle_fmt = workbook.add_format({'font_size': 9, 'font_color': '#6c757d'})
        header_fmt = workbook.add_format({
            'bold': True,
            'font_color': '#ffffff',
            'bg_color': '#714B67',
            'border': 1,
            'align': 'center',
            'valign': 'vcenter'
        })
        date_fmt = workbook.add_format({'num_format': 'yyyy-mm-dd', 'border': 1, 'align': 'center'})
        text_fmt = workbook.add_format({'border': 1, 'align': 'left'})
        num_fmt = workbook.add_format({'num_format': '#,##0.00', 'border': 1, 'align': 'right'})
        bold_num_fmt = workbook.add_format({'bold': True, 'num_format': '#,##0.00', 'border': 1, 'bg_color': '#f8f9fa', 'align': 'right'})
        bold_lbl_fmt = workbook.add_format({'bold': True, 'border': 1, 'bg_color': '#f8f9fa', 'align': 'right'})
        # Title Block
        worksheet.write(0, 0, f"{statement.bank_name or 'Bank'} Statement — {statement.name}", title_fmt)
        worksheet.write(1, 0, f"Company: {statement.company_id.name} | Date: {statement.statement_date or ''} | Total Debits: ₹{statement.total_debit:,.2f} | Total Credits: ₹{statement.total_credit:,.2f}", subtitle_fmt)
        headers = ['#', 'Date', 'Mode', 'Narration / Description', 'Reference / UTR', 'Debit (Outflow)', 'Credit (Inflow)', 'Balance', 'Assigned Contact', 'Assigned Ledger', 'Confidence', 'Status']
        row = 3
        for col, h in enumerate(headers):
            worksheet.write(row, col, h, header_fmt)
        worksheet.set_row(row, 24)
        row += 1
        start_row = row
        for idx, l in enumerate(statement.line_ids):
            worksheet.write(row, 0, idx + 1, text_fmt)
            worksheet.write(row, 1, str(l.date), date_fmt)
            worksheet.write(row, 2, (l.payment_mode or '').upper(), text_fmt)
            worksheet.write(row, 3, l.narration or '', text_fmt)
            worksheet.write(row, 4, l.reference or '', text_fmt)
            worksheet.write(row, 5, l.debit or 0.0, num_fmt)
            worksheet.write(row, 6, l.credit or 0.0, num_fmt)
            worksheet.write(row, 7, l.balance or 0.0, num_fmt)
            worksheet.write(row, 8, l.partner_id.name if l.partner_id else '', text_fmt)
            worksheet.write(row, 9, l.account_id.display_name if l.account_id else '', text_fmt)
            worksheet.write(row, 10, f"{l.confidence_percent}%", text_fmt)
            worksheet.write(row, 11, (l.status or '').upper(), text_fmt)
            row += 1
        end_row = row - 1
        if end_row >= start_row:
            worksheet.write(row, 4, 'TOTALS:', bold_lbl_fmt)
            worksheet.write_formula(row, 5, f"=SUM(F{start_row+1}:F{end_row+1})", bold_num_fmt)
            worksheet.write_formula(row, 6, f"=SUM(G{start_row+1}:G{end_row+1})", bold_num_fmt)
            worksheet.write(row, 7, statement.closing_balance or 0.0, bold_num_fmt)
        worksheet.set_column(0, 0, 5)
        worksheet.set_column(1, 1, 12)
        worksheet.set_column(2, 2, 10)
        worksheet.set_column(3, 3, 38)
        worksheet.set_column(4, 4, 24)
        worksheet.set_column(5, 7, 14)
        worksheet.set_column(8, 9, 24)
        worksheet.set_column(10, 11, 12)
        workbook.close()
        output.seek(0)
        xlsx_data = output.read()
        filename = f"{statement.bank_name or 'Bank'}_Statement_{statement.id}.xlsx"
        return request.make_response(
            xlsx_data,
            headers=[
                ('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
                ('Content-Disposition', f'attachment; filename="{filename}"'),
            ]
        )
    @http.route('/gsus_bank_ai/export_pdf', type='http', auth='user')
    def export_pdf(self, statement_id):
        """Direct HTTP download of styled statement audit report in PDF."""
        statement = request.env['gsus.bank.statement.ai'].sudo().browse(int(statement_id))
        if not statement.exists():
            return request.not_found()
        report_action = request.env.ref('gsus_bank_ai.action_report_bank_statement_ai', raise_if_not_found=False)
        if not report_action:
            return request.make_response("PDF Report Action not configured", status=500)
        pdf_content, _ = report_action.sudo()._render_qweb_pdf(report_action.id, [statement.id])
        filename = f"{statement.bank_name or 'Bank'}_Statement_{statement.id}.pdf"
        return request.make_response(
            pdf_content,
            headers=[
                ('Content-Type', 'application/pdf'),
                ('Content-Disposition', f'attachment; filename="{filename}"'),
            ]
        )
    @http.route('/gsus_bank_ai/view_pdf/<int:statement_id>', type='http', auth='public')
    def view_pdf(self, statement_id, **kwargs):
        """Stream original uploaded statement PDF or image inline for split-screen preview."""
        try:
            statement = request.env['gsus.bank.statement.ai'].sudo().browse(statement_id)
            if not statement.exists():
                return request.not_found()
            file_bytes = b''
            att = request.env['ir.attachment'].sudo().search([
                ('res_model', '=', 'gsus.bank.statement.ai'),
                ('res_id', '=', statement.id),
                ('res_field', '=', 'file_data'),
            ], limit=1)
            try:
                if att and att.raw:
                    raw_val = att.raw
                    if hasattr(raw_val, 'read'):
                        file_bytes = raw_val.read()
                    else:
                        file_bytes = bytes(raw_val)
                elif statement.file_data:
                    fdata = statement.file_data
                    if hasattr(fdata, 'read'):
                        file_bytes = fdata.read()
                    else:
                        file_bytes = bytes(fdata)
                # Check if base64 encoded
                if file_bytes and file_bytes.startswith(b'JVBERi0'):
                    pass
                elif file_bytes and (file_bytes.startswith(b'JVBER') or b'base64' in file_bytes[:100]):
                    import base64
                    try:
                        file_bytes = base64.b64decode(file_bytes)
                    except Exception:
                        pass
            except Exception as e:
                _logger.error("Error reading statement binary stream for #%s: %s", statement_id, str(e))
            if not file_bytes:
                placeholder_html = """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8"/>
    <style>
        body { font-family: system-ui, -apple-system, sans-serif; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; background: #f8fafc; color: #475569; }
        .card { text-align: center; padding: 32px; background: white; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.06); max-width: 420px; border: 1px solid #e2e8f0; }
        .icon { font-size: 3rem; margin-bottom: 12px; }
        h3 { margin: 0 0 8px; color: #1e293b; font-size: 1.2rem; }
        p { margin: 0 0 20px; font-size: 0.9rem; color: #64748b; line-height: 1.5; }
        .btn { display: inline-block; padding: 10px 20px; background: #6366f1; color: white; border-radius: 8px; text-decoration: none; font-weight: 600; font-size: 0.9rem; }
        .btn:hover { background: #4f46e5; }
    </style>
</head>
<body>
    <div class="card">
        <div class="icon">📄</div>
        <h3>Statement Document Preview</h3>
        <p>No document file is attached to this statement record yet.</p>
        <a class="btn" href="javascript:location.reload()">Refresh</a>
    </div>
</body>
</html>"""
                return request.make_response(placeholder_html, [('Content-Type', 'text/html; charset=utf-8')])
            mimetype = 'application/pdf'
            fname = (statement.file_name or 'statement.pdf').lower()
            if fname.endswith(('.jpg', '.jpeg')):
                mimetype = 'image/jpeg'
            elif fname.endswith('.png'):
                mimetype = 'image/png'
            elif fname.endswith('.csv'):
                mimetype = 'text/plain'
            import re
            import urllib.parse
            clean_fname = re.sub(r'[^a-zA-Z0-9_\.-]', '_', statement.file_name or 'statement.pdf')
            encoded_fname = urllib.parse.quote(statement.file_name or 'statement.pdf')
            headers = [
                ('Content-Type', mimetype),
                ('Content-Disposition', f'inline; filename="{clean_fname}"; filename*=UTF-8\'\'{encoded_fname}'),
                ('Content-Length', str(len(file_bytes))),
                ('Cache-Control', 'no-cache, max-age=0'),
                ('X-Content-Type-Options', 'nosniff'),
            ]
            return request.make_response(file_bytes, headers)
        except Exception as exc:
            _logger.exception("Unexpected error in view_pdf for statement #%s: %s", statement_id, str(exc))
            err_html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8"/>
    <style>
        body {{ font-family: system-ui, -apple-system, sans-serif; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; background: #f8fafc; color: #475569; }}
        .card {{ text-align: center; padding: 32px; background: white; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.06); max-width: 420px; border: 1px solid #e2e8f0; }}
        h3 {{ margin: 0 0 8px; color: #1e293b; font-size: 1.2rem; }}
        p {{ margin: 0 0 20px; font-size: 0.9rem; color: #64748b; }}
        .btn {{ display: inline-block; padding: 10px 20px; background: #6366f1; color: white; border-radius: 8px; text-decoration: none; font-weight: 600; font-size: 0.9rem; }}
    </style>
</head>
<body>
    <div class="card">
        <h3>Preview Loading</h3>
        <p>The document is ready. Click below to reload the preview.</p>
        <a class="btn" href="javascript:location.reload()">Reload Preview</a>
    </div>
</body>
</html>"""
            return request.make_response(err_html, [('Content-Type', 'text/html; charset=utf-8')])
    @http.route('/gsus_bank_ai/bulk_assign', type='json', auth='user')
    def bulk_assign(self, line_ids, partner_id=None, account_id=None, status='reviewed'):
        Line = request.env['gsus.bank.statement.ai.line'].sudo()
        lines = Line.browse([int(lid) for lid in line_ids if lid])
        if not lines:
            return {'error': 'No lines selected'}
        vals = {'confidence': 1.0}
        if status:
            vals['status'] = status
        if partner_id:
            vals['partner_id'] = int(partner_id)
        if account_id:
            vals['account_id'] = int(account_id)
        lines.write(vals)
        if lines:
            st = lines[0].statement_id
            st._compute_kpis()
        return {'success': True, 'count': len(lines)}
    @http.route('/gsus_bank_ai/bulk_delete', type='json', auth='user')
    def bulk_delete(self, line_ids):
        Line = request.env['gsus.bank.statement.ai.line'].sudo()
        lines = Line.browse([int(lid) for lid in line_ids if lid])
        if not lines:
            return {'error': 'No lines selected'}
        st = lines[0].statement_id
        count = len(lines)
        lines.unlink()
        st._compute_kpis()
        st._compute_verification()
        return {'success': True, 'count': count}
    @http.route('/gsus_bank_ai/bulk_status', type='json', auth='user')
    def bulk_status(self, line_ids, status='reviewed'):
        Line = request.env['gsus.bank.statement.ai.line'].sudo()
        lines = Line.browse([int(lid) for lid in line_ids if lid])
        if not lines:
            return {'error': 'No lines selected'}
        lines.write({'status': status})
        if lines:
            lines[0].statement_id._compute_kpis()
        return {'success': True, 'count': len(lines)}
    @http.route('/gsus_bank_ai/test_provider_ping', type='json', auth='user')
    def test_provider_ping(self, provider_type='gemini', api_key='', model_name='', ollama_host='http://localhost:11434'):
        key_val = (api_key or '').strip()
        if '•' in key_val or not key_val:
            Provider = request.env['gsus.bank.ai.provider'].sudo()
            rec = Provider.search([('provider_type', '=', provider_type)], limit=1)
            if rec:
                if rec.api_key_encrypted:
                    vault = request.env['gsus.bank.ai.vault']
                    key_val = vault.decrypt_secret(rec.api_key_encrypted)
                if getattr(rec, 'ollama_host', None):
                    ollama_host = rec.ollama_host
        if not key_val and provider_type not in ('native',):
            return {'success': False, 'error': 'No API Key entered. Please type or configure your API Secret Key.'}
        try:
            parser = request.env['gsus.bank.ai.vision.parser']
            res = parser.test_provider_ping_and_fetch_models(
                provider_type,
                key_val,
                model_name=model_name,
                timeout=15,
                ollama_host=ollama_host or 'http://localhost:11434',
            )
            return res
        except Exception as e:
            err_msg = str(e)
            if '400' in err_msg or '403' in err_msg or '401' in err_msg:
                err_msg = 'Authentication failed: API key invalid or unauthorized.'
            return {'success': False, 'error': err_msg, 'latency_ms': 0}
    @http.route('/gsus_bank_ai/get_providers', type='json', auth='user')
    def get_providers(self):
        import json
        import re
        def _sort_models_latest_first(model_list):
            EXCLUDED_KEYWORDS = ('argon', 'temp', 'aqa', 'robotics', 'imagen', 'embedding', 'learnlm', 'tts', 'audio')
            filtered = [
                m for m in model_list 
                if not any(x in (m.get('code', '') if isinstance(m, dict) else str(m)).lower() for x in EXCLUDED_KEYWORDS)
            ]
            def sort_key(item):
                code = (item.get('code', '') if isinstance(item, dict) else str(item)).lower()
                prod_prio = 0
                if code == 'gemini-3.8-flash':
                    prod_prio = 100
                elif code == 'gemini-3.5-flash':
                    prod_prio = 90
                elif code == 'gemini-3.5-flash-lite':
                    prod_prio = 85
                elif code == 'gemini-2.0-flash':
                    prod_prio = 80
                elif code == 'gemini-1.5-flash':
                    prod_prio = 70
                v_match = re.search(r'(\d+(?:\.\d+)*)', code)
                if v_match:
                    try:
                        v_parts = [int(p) for p in v_match.group(1).split('.')]
                    except Exception:
                        v_parts = [0]
                else:
                    v_parts = [0]
                while len(v_parts) < 3:
                    v_parts.append(0)
                is_flash = 1 if 'flash' in code else 0
                is_stable = 0 if ('exp' in code or 'preview' in code) else 1
                return (-prod_prio, [-v for v in v_parts], -is_flash, -is_stable, code)
            return sorted(filtered, key=sort_key)
        Provider = request.env['gsus.bank.ai.provider'].sudo()
        providers = Provider.search([], order='is_active desc, sequence asc')
        res = []
        for p in providers:
            if p.provider_type == 'gemini' and (not p.model_name or 'argon' in p.model_name.lower() or p.model_name == 'gemini-2.5-flash'):
                try:
                    p.sudo().write({'model_name': 'gemini-3.8-flash', 'gemini_model': 'gemini-3.8-flash'})
                except Exception:
                    pass
            sup_models = []
            if p.supported_models_json:
                try:
                    sup_models = json.loads(p.supported_models_json)
                    sup_models = _sort_models_latest_first(sup_models)
                except Exception:
                    pass
            res.append({
                'id': p.id,
                'name': p.name,
                'provider_type': p.provider_type,
                'model_name': p.model_name,
                'is_active': p.is_active,
                'has_key': bool(p.api_key_encrypted),
                'last_status': p.last_status,
                'ollama_host': getattr(p, 'ollama_host', 'http://localhost:11434') or 'http://localhost:11434',
                'supported_models': sup_models,
            })
        return {'providers': res}
    @http.route('/gsus_bank_ai/save_provider', type='json', auth='user')
    def save_provider(self, provider_type, api_key='', model_name='', is_active=True, supported_models=None, ollama_host='http://localhost:11434'):
        import json
        Provider = request.env['gsus.bank.ai.provider'].sudo()
        rec = Provider.search([('provider_type', '=', provider_type)], limit=1)
        vals = {
            'provider_type': provider_type,
            'is_active': is_active,
            'last_status': 'Connected & Verified',
        }
        if model_name:
            vals['model_name'] = model_name
        if supported_models:
            vals['supported_models_json'] = json.dumps(supported_models)
        # Safe selection fallback: dynamically validate against static selection choices
        # If model is a newly discovered live model (e.g. gemini-3.8-flash), store 'custom' in selection field
        # while keeping the full live identifier in model_name
        if provider_type == 'native':
            vals['name'] = 'Native Python Engine (100% Offline)'
            known_native = [k for k, _ in getattr(Provider, 'NATIVE_MODELS', [('native-adaptive-v1', '')])]
            vals['native_model'] = model_name if model_name in known_native else 'custom'
        elif provider_type == 'gemini':
            vals['name'] = 'Google Gemini Multimodal'
            known_gemini = [k for k, _ in Provider.GEMINI_MODELS]
            vals['gemini_model'] = model_name if model_name in known_gemini else 'custom'
        elif provider_type == 'openai':
            vals['name'] = 'OpenAI GPT-4o Vision'
            known_openai = [k for k, _ in Provider.OPENAI_MODELS]
            vals['openai_model'] = model_name if model_name in known_openai else 'custom'
        if is_active:
            # Ensure this provider is the single active engine
            other_providers = Provider.search([('provider_type', '!=', provider_type)])
            if other_providers:
                other_providers.write({'is_active': False})
        if rec:
            if api_key and not api_key.startswith('•'):
                vals['api_key'] = api_key
            rec.write(vals)
            provider_id = rec.id
        else:
            if api_key:
                vals['api_key'] = api_key
            new_rec = Provider.create(vals)
            provider_id = new_rec.id
        active_rec = Provider.browse(provider_id)
        is_native = (active_rec.provider_type == 'native')
        has_key = bool(active_rec.api_key_encrypted) or is_native
        model_disp = active_rec.model_name or active_rec.name
        if is_native:
            badge_text = f'{model_disp} · 100% Offline (Instant)'
            badge_color = 'success'
            status = 'connected'
        elif has_key:
            badge_text = f'{model_disp} · Active'
            badge_color = 'success'
            status = 'connected'
        else:
            badge_text = f'{model_disp} · Key Missing'
            badge_color = 'warning'
            status = 'missing_key'
        return {
            'success': True,
            'provider_id': provider_id,
            'ai_engine': {
                'has_key': has_key,
                'status': status,
                'badge_text': badge_text,
                'badge_color': badge_color,
                'engine_name': active_rec.name,
                'model_name': model_disp,
                'provider_type': active_rec.provider_type,
            }
        }
