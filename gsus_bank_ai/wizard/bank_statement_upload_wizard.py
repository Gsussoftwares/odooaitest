# -*- coding: utf-8 -*-
# Part of GSUS Bank AI. See LICENSE file for full copyright and licensing details.

import logging
from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class GsusBankStatementUploadWizard(models.TransientModel):
    _name = 'gsus.bank.statement.upload.wizard'
    _description = 'Bank Statement PDF & Document Upload Wizard'

    file_data = fields.Binary(string='Bank Statement File (PDF / Image / CSV)', required=True)
    file_name = fields.Char(string='File Name')
    journal_id = fields.Many2one('account.journal', string='Bank Journal', domain=[('type', '=', 'bank')])
    bank_hint = fields.Char(string='Bank Name Hint (Optional)', help='e.g. Axis Bank, State Bank of India')
    pdf_password = fields.Char(string='PDF Password (If Encrypted)', help='Password for password-protected bank statement PDF')

    def action_upload_and_process(self):
        self.ensure_one()
        if not self.file_data:
            raise UserError("Please select a bank statement file to upload.")

        session = self.env['gsus.bank.statement.ai'].sudo().create({
            'name': self.file_name or 'Bank Statement',
            'file_data': self.file_data,
            'file_name': self.file_name,
            'pdf_password': self.pdf_password,
            'journal_id': self.journal_id.id if self.journal_id else False,
            'bank_name': self.bank_hint or '',
        })

        # Run AI parsing & auto-assign (let password UserError surface to user)
        try:
            session.action_parse_statement()
        except UserError:
            raise
        except Exception as e:
            session.last_error_message = str(e)
            _logger.exception("AI Statement parsing error during upload: %s", str(e))
            raise UserError(f"AI Statement Parsing Error: {str(e)}")
        finally:
            if session.pdf_password:
                session.pdf_password = False
            if self.pdf_password:
                self.pdf_password = False

        # Transition directly to the Full-Screen Advanced OWL 3 Workbench
        return {
            'type': 'ir.actions.client',
            'tag': 'gsus_bank_workbench_action',
            'name': f"Bank Statement AI Workbench: {session.name}",
            'res_id': session.id,
            'params': {'statement_id': session.id},
            'context': {
                'active_id': session.id,
                'statement_id': session.id,
            },
            'target': 'current',
        }
