# -*- coding: utf-8 -*-
# Part of GSUS AI. See LICENSE file for full copyright and licensing details.

import logging
from odoo import models, api

_logger = logging.getLogger(__name__)


class GsusAiContextBuilder(models.AbstractModel):
    _name = 'gsus.ai.context.builder'
    _description = 'Odoo Business Record Context Extractor'

    @api.model
    def build_context_prompt(self, context_dict: dict) -> str:
        """Extract structured business data for the active record and format as prompt context."""
        model_name = context_dict.get('res_model')
        record_id = context_dict.get('res_id')
        if not model_name or not record_id or model_name not in self.env:
            return ""

        try:
            record = self.env[model_name].browse(record_id)
            if not record.exists():
                return ""

            lines = [f"Active Document: {model_name} (ID: {record_id})"]

            if model_name == 'res.partner':
                lines.append(f"- Partner Name: {record.display_name}")
                lines.append(f"- Email: {record.email or 'N/A'}, Phone: {record.phone or 'N/A'}")
                if hasattr(record, 'credit'):
                    lines.append(f"- Outstanding Receivable: {record.credit} {record.currency_id.name or ''}")
                if hasattr(record, 'sale_order_count'):
                    lines.append(f"- Total Sales Orders: {record.sale_order_count}")

            elif model_name == 'sale.order':
                lines.append(f"- Order Reference: {record.name}")
                lines.append(f"- Customer: {record.partner_id.display_name}")
                lines.append(f"- Status: {record.state}")
                lines.append(f"- Total Amount: {record.amount_total} {record.currency_id.name or ''}")
                if record.order_line:
                    lines.append("- Line Items:")
                    for line in record.order_line[:8]:
                        lines.append(f"  * {line.name} | Qty: {line.product_uom_qty} | Subtotal: {line.price_subtotal}")

            elif model_name == 'crm.lead':
                lines.append(f"- Opportunity Name: {record.name}")
                lines.append(f"- Partner: {record.partner_id.display_name if record.partner_id else 'None'}")
                lines.append(f"- Expected Revenue: {record.expected_revenue} {record.company_currency.name or ''}")
                lines.append(f"- Probability: {record.probability}%")
                lines.append(f"- Stage: {record.stage_id.name if record.stage_id else 'N/A'}")

            elif model_name == 'account.move':
                lines.append(f"- Invoice Number: {record.name}")
                lines.append(f"- Customer/Vendor: {record.partner_id.display_name}")
                lines.append(f"- Invoice Date: {record.invoice_date}")
                lines.append(f"- Due Date: {record.invoice_date_due}")
                lines.append(f"- Amount Total: {record.amount_total} {record.currency_id.name or ''}")
                lines.append(f"- Payment State: {record.payment_state}")
                lines.append(f"- Residual Amount: {record.amount_residual}")

            elif model_name == 'project.task':
                lines.append(f"- Task: {record.name}")
                lines.append(f"- Project: {record.project_id.name if record.project_id else 'None'}")
                lines.append(f"- Stage: {record.stage_id.name if record.stage_id else 'None'}")
                if hasattr(record, 'user_ids'):
                    lines.append(f"- Assigned: {', '.join(record.user_ids.mapped('name'))}")

            elif model_name == 'stock.picking':
                lines.append(f"- Transfer: {record.name}")
                lines.append(f"- Operation Type: {record.picking_type_id.name if record.picking_type_id else ''}")
                lines.append(f"- Status: {record.state}")
                if record.move_ids_without_package:
                    lines.append("- Move Items:")
                    for m in record.move_ids_without_package[:8]:
                        lines.append(f"  * {m.product_id.display_name} | Demand: {m.product_uom_qty}")

            else:
                # Generic fallback for any other model
                lines.append(f"- Display Name: {record.display_name}")

            return "\n".join(lines)
        except Exception as e:
            _logger.debug("Error building context for %s %s: %s", model_name, record_id, str(e))
            return ""
