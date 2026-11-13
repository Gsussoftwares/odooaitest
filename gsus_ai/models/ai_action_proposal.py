# -*- coding: utf-8 -*-
# Part of GSUS AI. See LICENSE file for full copyright and licensing details.

import json
import logging
from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class GsusAiActionProposal(models.Model):
    _name = 'gsus.ai.action.proposal'
    _description = 'GSUS AI Action Proposal & Confirmation Gate'
    _order = 'id desc'

    conversation_id = fields.Many2one('gsus.ai.conversation', string='Conversation', ondelete='cascade', required=True)
    message_id = fields.Many2one('gsus.ai.message', string='Assistant Message', ondelete='cascade')
    tool_id = fields.Many2one('gsus.ai.tool', string='Target Tool', required=True)
    tool_call_id = fields.Char(string='Tool Call ID')

    summary = fields.Char(string='Action Summary', required=True)
    arguments_json = fields.Text(string='Proposed Parameters (JSON)', required=True)

    state = fields.Selection([
        ('pending', 'Pending Approval'),
        ('confirmed', 'Approved & Executed'),
        ('failed', 'Execution Failed'),
        ('rejected', 'Rejected by User'),
    ], string='Status', default='pending', required=True, index=True)

    execution_result = fields.Text(string='Execution Result', readonly=True)
    executed_by = fields.Many2one('res.users', string='Approved By', readonly=True)
    executed_at = fields.Datetime(string='Executed At', readonly=True)

    def action_confirm(self):
        """Confirm proposed mutating action and execute the tool."""
        self.ensure_one()
        if self.state not in ('pending', 'failed'):
            raise UserError("Only pending or failed proposals can be confirmed.")

        try:
            args = json.loads(self.arguments_json) if self.arguments_json else {}
        except Exception:
            args = {}

        try:
            result = self.tool_id.execute_tool(args, conversation_id=self.conversation_id.id)
            if isinstance(result, dict) and result.get('error'):
                err_text = result['error']
                result_str = json.dumps(result, indent=2, default=str)
                self.write({
                    'state': 'failed',
                    'execution_result': result_str,
                    'executed_by': self.env.user.id,
                    'executed_at': fields.Datetime.now(),
                })
                error_msg = f"❌ **Action Failed:** Could not complete {self.summary}.\n\n**Reason:** {err_text}"
                self.env['gsus.ai.message'].create({
                    'conversation_id': self.conversation_id.id,
                    'role': 'assistant',
                    'content': error_msg,
                    'is_error': True,
                    'error_text': err_text,
                })
                return {'status': 'error', 'error': err_text}

            result_str = json.dumps(result, indent=2, default=str)
            self.write({
                'state': 'confirmed',
                'execution_result': result_str,
                'executed_by': self.env.user.id,
                'executed_at': fields.Datetime.now(),
            })

            # Append user-friendly confirmation message with direct Odoo record link
            formatted_msg = self._format_execution_message(result if isinstance(result, dict) else {})
            self.env['gsus.ai.message'].create({
                'conversation_id': self.conversation_id.id,
                'role': 'assistant',
                'content': formatted_msg,
            })
            return {'status': 'success', 'result': result}
        except Exception as e:
            _logger.exception("Failed to execute proposal %s", self.id)
            err_msg = str(e)
            self.write({
                'state': 'failed',
                'execution_result': json.dumps({'error': err_msg}),
                'executed_by': self.env.user.id,
                'executed_at': fields.Datetime.now(),
            })
            self.env['gsus.ai.message'].create({
                'conversation_id': self.conversation_id.id,
                'role': 'assistant',
                'content': f"❌ **Action Failed:** Execution error: {err_msg}",
                'is_error': True,
                'error_text': err_msg,
            })
            return {'status': 'error', 'error': err_msg}

    def _format_execution_message(self, result: dict) -> str:
        """Format tool execution result into clean, professional, human-understandable markdown."""
        if not isinstance(result, dict):
            return f"✅ **Action Executed:** {self.summary}"

        model = result.get('model')
        rec_id = result.get('id')
        display_name = result.get('display_name') or result.get('name') or (f"Record #{rec_id}" if rec_id else "")
        msg = result.get('message', '')

        # 0. System Configuration Settings (res.config.settings)
        if model == 'res.config.settings' or result.get('is_settings'):
            updated_fields = result.get('updated_fields') or {}
            lines = [
                f"### ✅ Configuration Settings Updated",
                "",
                "The requested configuration changes have been applied successfully to your system.",
                "",
                "| Setting | Value |",
                "| :--- | :--- |",
            ]
            if updated_fields:
                for k, v in updated_fields.items():
                    field_obj = self.env['res.config.settings']._fields.get(k)
                    label = field_obj.string if field_obj else k.replace('group_', '').replace('_', ' ').title()
                    val_str = "Enabled" if v is True else ("Disabled" if v is False else str(v))
                    lines.append(f"| **{label}** | {val_str} |")
            else:
                lines.append(f"| **Status** | Applied successfully |")
            lines.append("")
            lines.append("👉 **[Click here to open Settings in Odoo](odoo-action://base.action_general_configuration)**")
            return "\n".join(lines)

        # 0.5. Record Deleted (Suppress dead link, show pre-actions if any)
        if result.get('is_deleted') or (self.summary and 'delete' in self.summary.lower() and not result.get('error')):
            model_desc = result.get('model_description')
            if not model_desc and model:
                try:
                    model_desc = self.env[model]._description if model in self.env else model
                except Exception:
                    model_desc = model
            model_desc = model_desc or "Record"

            lines = [
                f"### 🗑️ {model_desc} {display_name} Deleted Successfully",
                "",
                f"| Detail | Value |",
                f"| :--- | :--- |",
                f"| **Record** | **{display_name}** |",
                f"| **Type** | {model_desc} (`{model}`) |",
                f"| **ID** | #{rec_id} |",
                f"| **Status** | **Permanently Deleted** |",
            ]
            if result.get('partner'):
                lines.append(f"| **Partner** | {result.get('partner')} |")
            if result.get('amount_total') is not None:
                lines.append(f"| **Total Amount** | {result.get('amount_total')} |")

            pre_actions = result.get('pre_actions') or []
            if pre_actions:
                lines.append("")
                lines.append("#### ⚙️ Automated Pre-deletion Actions:")
                for act in pre_actions:
                    lines.append(f"- ✅ {act}")

            lines.append("")
            lines.append(f"ℹ️ *This {model_desc.lower()} has been completely removed from the system.*")

            SAFE_LIST_ACTIONS = {
                'purchase.order': ('purchase.purchase_rfq', 'View All Purchase Orders / RFQs'),
                'sale.order': ('sale.action_orders', 'View All Sales Orders'),
                'account.move': ('account.action_move_out_invoice_type', 'View All Invoices'),
                'stock.picking': ('stock.action_picking_tree_all', 'View All Stock Transfers'),
                'crm.lead': ('crm.crm_lead_action_pipeline', 'View CRM Pipeline'),
            }
            if model in SAFE_LIST_ACTIONS:
                xml_id, nav_label = SAFE_LIST_ACTIONS[model]
                lines.append(f"👉 **[{nav_label}](odoo-action://{xml_id})**")

            return "\n".join(lines)

        # 1. Record Created / Updated
        if model and rec_id:
            try:
                model_desc = self.env[model]._description if model in self.env else model
            except Exception:
                model_desc = model

            summary_title = self.summary or 'Action Completed'
            if summary_title.startswith('Proposed action: '):
                summary_title = summary_title.replace('Proposed action: ', '')

            lines = [
                f"### ✅ {summary_title}",
                "",
                f"| Detail | Value |",
                f"| :--- | :--- |",
                f"| **Record** | **[{display_name}](odoo://{model}/{rec_id})** |",
                f"| **Type** | {model_desc} (`{model}`) |",
                f"| **ID** | #{rec_id} |",
            ]
            if result.get('partner'):
                lines.append(f"| **Partner** | {result.get('partner')} |")
            if result.get('amount_total') is not None:
                lines.append(f"| **Total Amount** | {result.get('amount_total')} |")

            # Changes Applied diff table
            diff = result.get('updated_fields_diff')
            if diff and isinstance(diff, dict):
                lines.append("")
                lines.append("#### 📋 Changes Applied:")
                lines.append("| Field | Previous Value | New Value |")
                lines.append("| :--- | :--- | :--- |")
                for fname, fvals in diff.items():
                    old_v = fvals.get('old', '') or '—'
                    new_v = fvals.get('new', '') or '—'
                    lines.append(f"| **{fname}** | {old_v} | **{new_v}** |")

            lines.append("")
            lines.append(f"👉 **[Click here to open {display_name} in Odoo](odoo://{model}/{rec_id})**")
            return "\n".join(lines)

        # 2. App Lifecycle (Installed / Upgraded / Uninstalled)
        if 'module_name' in result:
            mod_name = result.get('module_name')
            shortdesc = result.get('shortdesc') or mod_name
            action = result.get('action') or ''
            if not action:
                act_name = (self.action_name or '').lower()
                summary_str = (self.summary or '').lower()
                if 'uninstall' in act_name or 'uninstall' in summary_str:
                    action = 'uninstall'
                elif 'upgrade' in act_name or 'upgrade' in summary_str:
                    action = 'upgrade'
                else:
                    action = 'install'

            if action == 'uninstall':
                return (
                    f"### 🗑️ Module Uninstalled Successfully\n\n"
                    f"The app **{shortdesc}** (`{mod_name}`) has been uninstalled from your system.\n\n"
                    f"Its menus, views, and specific database records have been removed."
                )
            elif action == 'upgrade':
                return (
                    f"### 🔄 Module Upgraded Successfully\n\n"
                    f"The app **{shortdesc}** (`{mod_name}`) has been updated to the latest version."
                )
            else:
                return (
                    f"### ✅ Module Processed Successfully\n\n"
                    f"The app **{shortdesc}** (`{mod_name}`) is now installed and active in your system.\n\n"
                    f"You can now create records, orders, and view menus for this module."
                )

        # 3. Clean status message
        if msg:
            return f"✅ **{self.summary}**\n\n{msg}"

        return f"✅ **Action Confirmed and Executed:** {self.summary}"

    def action_reject(self):
        """Reject proposed mutating action without database modification."""
        self.ensure_one()
        if self.state != 'pending':
            raise UserError("Only pending proposals can be rejected.")

        self.write({
            'state': 'rejected',
            'executed_by': self.env.user.id,
            'executed_at': fields.Datetime.now(),
        })

        self.env['gsus.ai.message'].create({
            'conversation_id': self.conversation_id.id,
            'role': 'assistant',
            'content': f"❌ **Action Cancelled:** {self.summary} was rejected by user.",
        })
        return {'status': 'rejected'}
