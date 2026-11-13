# -*- coding: utf-8 -*-
# Part of GSUS AI. See LICENSE file for full copyright and licensing details.

import time
import json
import logging
from odoo import models, fields, api
from odoo.exceptions import AccessError, UserError

_logger = logging.getLogger(__name__)


class GsusAiToolExecutor(models.AbstractModel):
    _name = 'gsus.ai.tool.executor'
    _description = 'GSUS AI Safe Business Tool Execution Sandbox'

    @api.model
    def execute(self, tool_record, arguments: dict, conversation_id: int = None) -> dict:
        """Route tool code to validated server method with audit logging."""
        code = tool_record.code
        start_time = time.time()
        status = 'success'
        error_msg = ""
        result = {}

        try:
            handler_method = f"_tool_{code}"
            if hasattr(self, handler_method):
                result = getattr(self, handler_method)(arguments)
            else:
                raise UserError(f"No execution handler registered for tool '{code}'.")
        except AccessError as ae:
            status = 'error'
            error_msg = f"Access Denied: {str(ae)}"
            result = {'error': error_msg}
        except Exception as e:
            status = 'error'
            error_msg = str(e)
            _logger.exception("Error during execution of tool %s", code)
            result = {'error': error_msg}
        finally:
            duration_ms = round((time.time() - start_time) * 1000, 2)
            # Log execution to audit trail
            try:
                self.env['gsus.ai.audit.log'].sudo().create({
                    'tool_id': tool_record.id,
                    'tool_code': code,
                    'user_id': self.env.user.id,
                    'company_id': self.env.company.id,
                    'conversation_id': conversation_id,
                    'arguments_json': json.dumps(arguments, default=str),
                    'result_status': status,
                    'result_summary': json.dumps(result, default=str)[:1000],
                    'duration_ms': duration_ms,
                })
            except Exception as log_err:
                _logger.warning("Failed to record audit log: %s", str(log_err))

        return result

    # -------------------------------------------------------------
    # SALES & CRM TOOLS
    # -------------------------------------------------------------
    def _tool_crm_search_leads(self, args: dict) -> dict:
        if 'crm.lead' not in self.env:
            return {'error': 'CRM module is not installed in this database.', 'leads': [], 'count': 0}
        query = args.get('query', '').strip()
        domain = []
        if query:
            domain = ['|', ('name', 'ilike', query), ('partner_id.name', 'ilike', query)]
        leads = self.env['crm.lead'].search_read(
            domain,
            ['name', 'partner_id', 'expected_revenue', 'probability', 'stage_id', 'user_id'],
            limit=args.get('limit', 10),
        )
        return {'leads': leads, 'count': len(leads)}

    def _tool_crm_summarize_lead(self, args: dict) -> dict:
        if 'crm.lead' not in self.env:
            return {'error': 'CRM module is not installed in this database.'}
        lead_id = args.get('lead_id')
        lead = self.env['crm.lead'].browse(lead_id)
        if not lead.exists():
            return {'error': f"Lead #{lead_id} not found."}
        return {
            'id': lead.id,
            'name': lead.name,
            'partner': lead.partner_id.name if lead.partner_id else None,
            'revenue': lead.expected_revenue,
            'probability': lead.probability,
            'stage': lead.stage_id.name if lead.stage_id else None,
            'salesperson': lead.user_id.name if lead.user_id else None,
            'description': lead.description or '',
        }

    def _tool_crm_create_lead(self, args: dict) -> dict:
        if 'crm.lead' not in self.env:
            return {'error': 'CRM module is not installed in this database.'}
        name = args.get('name')
        if not name:
            raise UserError("Lead name is required.")
        partner_id = args.get('partner_id')
        vals = {
            'name': name,
            'partner_id': partner_id or False,
            'expected_revenue': args.get('expected_revenue', 0.0),
            'probability': args.get('probability', 10.0),
            'description': args.get('description', ''),
        }
        lead = self.env['crm.lead'].create(vals)
        return {'success': True, 'lead_id': lead.id, 'lead_name': lead.name}

    def _tool_sale_search_orders(self, args: dict) -> dict:
        if 'sale.order' not in self.env:
            return {'error': 'Sales module is not installed in this database.', 'orders': [], 'count': 0}
        query = args.get('query', '').strip()
        domain = []
        if query:
            domain = ['|', ('name', 'ilike', query), ('partner_id.name', 'ilike', query)]
        orders = self.env['sale.order'].search_read(
            domain,
            ['name', 'partner_id', 'date_order', 'amount_total', 'state'],
            limit=args.get('limit', 10),
        )
        return {'orders': orders, 'count': len(orders)}

    def _tool_sale_summarize_order(self, args: dict) -> dict:
        if 'sale.order' not in self.env:
            return {'error': 'Sales module is not installed in this database.'}
        order_id = args.get('order_id')
        order = self.env['sale.order'].browse(order_id)
        if not order.exists():
            return {'error': f"Sale Order #{order_id} not found."}
        lines = []
        for l in order.order_line:
            lines.append({
                'product': l.product_id.display_name,
                'quantity': l.product_uom_qty,
                'price_unit': l.price_unit,
                'subtotal': l.price_subtotal,
            })
        return {
            'name': order.name,
            'partner': order.partner_id.name,
            'state': order.state,
            'amount_total': order.amount_total,
            'date_order': str(order.date_order),
            'lines': lines,
        }

    def _tool_sale_create_order(self, args: dict) -> dict:
        if 'sale.order' not in self.env:
            return {'error': 'Sales module is not installed in this database.'}

        partner_id = args.get('partner_id')
        partner_name = args.get('partner_name', '').strip()

        if not partner_id and partner_name:
            partner = self.env['res.partner'].search([('name', 'ilike', partner_name)], limit=1)
            if not partner:
                partner = self.env['res.partner'].create({'name': partner_name})
            partner_id = partner.id

        if not partner_id:
            partner_id = self.env.user.partner_id.id

        order_lines = []
        for line in args.get('lines', []):
            product_id = line.get('product_id')
            product_name = line.get('product_name', '').strip()
            qty = float(line.get('quantity', 1.0))
            price_unit = line.get('price_unit')

            product = None
            if product_id:
                product = self.env['product.product'].browse(product_id)
            elif product_name:
                product = self.env['product.product'].search([('name', 'ilike', product_name)], limit=1)

            if product and product.exists():
                line_vals = {
                    'product_id': product.id,
                    'product_uom_qty': qty,
                }
                if price_unit is not None:
                    line_vals['price_unit'] = float(price_unit)
                order_lines.append((0, 0, line_vals))

        order_vals = {
            'partner_id': partner_id,
        }
        if order_lines:
            order_vals['order_line'] = order_lines

        order = self.env['sale.order'].create(order_vals)
        return {
            'success': True,
            'model': 'sale.order',
            'id': order.id,
            'order_id': order.id,
            'display_name': order.name,
            'partner': order.partner_id.name,
            'partner_name': order.partner_id.name,
            'amount_total': order.amount_total,
            'state': order.state,
            'message': f"Sales Order {order.name} created successfully for {order.partner_id.name} totaling {order.amount_total}."
        }

    # -------------------------------------------------------------
    # PURCHASE & VENDOR TOOLS
    # -------------------------------------------------------------
    def _tool_purchase_search_orders(self, args: dict) -> dict:
        """Search Purchase Orders and RFQs."""
        if 'purchase.order' not in self.env:
            return {
                'error': "Purchase module ('purchase') is not installed in this system. You can install it using app_install_module.",
                'requires_module': 'purchase',
                'orders': [],
                'count': 0,
            }
        query = args.get('query', '').strip()
        domain = []
        if query:
            domain = ['|', ('name', 'ilike', query), ('partner_id.name', 'ilike', query)]
        orders = self.env['purchase.order'].search_read(
            domain,
            ['name', 'partner_id', 'date_order', 'amount_total', 'state'],
            limit=args.get('limit', 10),
            order='date_order desc, id desc'
        )
        return {'orders': orders, 'count': len(orders)}

    def _tool_purchase_create_order(self, args: dict) -> dict:
        """Create a draft Purchase Order (RFQ) for a vendor."""
        if 'purchase.order' not in self.env:
            return {
                'error': (
                    "The Purchase module ('purchase') is not installed in this Odoo system. "
                    "Please install the 'purchase' app first using the 'app_install_module' tool."
                ),
                'requires_module': 'purchase',
            }

        partner_id = args.get('partner_id')
        partner_name = args.get('partner_name', '').strip()

        if not partner_id and partner_name:
            partner = self.env['res.partner'].search(['|', ('name', '=ilike', partner_name), ('name', 'ilike', partner_name)], limit=1)
            if not partner:
                partner = self.env['res.partner'].create({
                    'name': partner_name,
                    'supplier_rank': 1,
                })
            partner_id = partner.id

        if not partner_id:
            return {'error': "A vendor name ('partner_name') or vendor ID ('partner_id') is required."}

        partner = self.env['res.partner'].browse(partner_id)
        if not partner.exists():
            return {'error': f"Vendor partner #{partner_id} not found."}

        order_lines = []
        pol_fields = self.env['purchase.order.line']._fields if 'purchase.order.line' in self.env else {}
        uom_field = 'uom_id' if 'uom_id' in pol_fields else 'product_uom'

        for line in args.get('lines', []):
            product_id = line.get('product_id')
            product_name = line.get('product_name', '').strip()
            qty = float(line.get('quantity', 1.0))
            price_unit = line.get('price_unit')
            uom_name = line.get('uom_name', '').strip()

            product = None
            if product_id:
                product = self.env['product.product'].browse(product_id)
            elif product_name:
                product = self.env['product.product'].search(['|', ('name', '=ilike', product_name), ('name', 'ilike', product_name)], limit=1)
                if not product:
                    uom = self.env['uom.uom'].search(['|', ('name', '=ilike', uom_name), ('name', 'ilike', uom_name)], limit=1) if uom_name else False
                    product_vals = {
                        'name': product_name,
                        'purchase_ok': True,
                    }
                    if uom:
                        product_vals['uom_id'] = uom.id
                        if 'uom_po_id' in self.env['product.product']._fields:
                            product_vals['uom_po_id'] = uom.id
                    product = self.env['product.product'].create(product_vals)

            if product and product.exists():
                uom = False
                if hasattr(product, 'uom_po_id') and product.uom_po_id:
                    uom = product.uom_po_id
                elif hasattr(product, 'uom_id') and product.uom_id:
                    uom = product.uom_id

                line_vals = {
                    'product_id': product.id,
                    'name': product.display_name or product.name,
                    'product_qty': qty,
                    'price_unit': float(price_unit) if price_unit is not None else (product.standard_price or 1.0),
                }
                if uom and uom_field:
                    line_vals[uom_field] = uom.id
                order_lines.append((0, 0, line_vals))

        order_vals = {
            'partner_id': partner_id,
        }
        if order_lines:
            order_vals['order_line'] = order_lines
        if args.get('notes'):
            order_vals['notes'] = args.get('notes')

        order = self.env['purchase.order'].create(order_vals)
        return {
            'success': True,
            'model': 'purchase.order',
            'id': order.id,
            'order_id': order.id,
            'display_name': order.name,
            'partner': partner.name,
            'amount_total': order.amount_total,
            'state': order.state,
            'message': f"Purchase Order {order.name} created successfully for vendor {partner.name} totaling {order.amount_total}."
        }

    # -------------------------------------------------------------
    # ACCOUNTING & FINANCE TOOLS
    # -------------------------------------------------------------
    def _tool_account_check_partner_balance(self, args: dict) -> dict:
        partner_id = args.get('partner_id')
        partner = self.env['res.partner'].browse(partner_id)
        if not partner.exists():
            return {'error': f"Partner #{partner_id} not found."}
        credit = getattr(partner, 'credit', 0.0)
        debit = getattr(partner, 'debit', 0.0)
        return {
            'partner_name': partner.name,
            'receivable_balance': credit,
            'payable_balance': debit,
            'currency': partner.currency_id.name if partner.currency_id else '',
        }

    def _tool_account_search_invoices(self, args: dict) -> dict:
        domain = [('move_type', 'in', ['out_invoice', 'out_refund'])]
        partner_id = args.get('partner_id')
        if partner_id:
            domain.append(('partner_id', '=', partner_id))
        state = args.get('payment_state')
        if state:
            domain.append(('payment_state', '=', state))

        invoices = self.env['account.move'].search_read(
            domain,
            ['name', 'partner_id', 'invoice_date', 'invoice_date_due', 'amount_total', 'amount_residual', 'payment_state', 'state'],
            limit=args.get('limit', 10),
        )
        return {'invoices': invoices, 'count': len(invoices)}

    # -------------------------------------------------------------
    # INVENTORY & PRODUCTS TOOLS
    # -------------------------------------------------------------
    def _tool_stock_check_availability(self, args: dict) -> dict:
        product_query = args.get('product_name', '').strip()
        domain = [('sale_ok', '=', True)]
        if product_query:
            domain.append(('name', 'ilike', product_query))
        products = self.env['product.product'].search(domain, limit=args.get('limit', 10))
        res = []
        for p in products:
            res.append({
                'id': p.id,
                'name': p.display_name,
                'default_code': p.default_code or '',
                'qty_available': p.qty_available,
                'virtual_available': p.virtual_available,
                'list_price': p.list_price,
            })
        return {'products': res, 'count': len(res)}

    # -------------------------------------------------------------
    # PROJECTS & TASKS TOOLS
    # -------------------------------------------------------------
    def _tool_project_search_tasks(self, args: dict) -> dict:
        domain = []
        query = args.get('query', '').strip()
        if query:
            domain.append(('name', 'ilike', query))
        project_id = args.get('project_id')
        if project_id:
            domain.append(('project_id', '=', project_id))

        tasks = self.env['project.task'].search_read(
            domain,
            ['name', 'project_id', 'stage_id', 'date_deadline', 'user_ids'],
            limit=args.get('limit', 10),
        )
        return {'tasks': tasks, 'count': len(tasks)}

    # -------------------------------------------------------------
    # HELPDESK & SUPPORT TOOLS
    # -------------------------------------------------------------
    def _tool_helpdesk_search_tickets(self, args: dict) -> dict:
        if 'helpdesk.ticket' not in self.env:
            return {'error': 'Helpdesk module is not installed in this database.'}
        domain = []
        query = args.get('query', '').strip()
        if query:
            domain.append(('name', 'ilike', query))
        tickets = self.env['helpdesk.ticket'].search_read(
            domain,
            ['name', 'partner_id', 'stage_id', 'priority', 'user_id'],
            limit=args.get('limit', 10),
        )
        return {'tickets': tickets, 'count': len(tickets)}

    # -------------------------------------------------------------
    # GENERAL ODOO TOOLS (ACTIVITIES & CHATTER)
    # -------------------------------------------------------------
    def _tool_calendar_schedule_activity(self, args: dict) -> dict:
        res_model = args.get('res_model')
        res_id = args.get('res_id')
        summary = args.get('summary', 'AI Scheduled Activity')
        note = args.get('note', '')
        date_deadline = args.get('date_deadline') or fields.Date.today()

        if not res_model or not res_id or res_model not in self.env:
            raise UserError("Invalid target model or record ID.")

        model_record = self.env['ir.model'].search([('model', '=', res_model)], limit=1)
        if not model_record:
            raise UserError(f"Model {res_model} not registered.")

        activity_type = self.env['mail.activity.type'].search([], limit=1)
        activity = self.env['mail.activity'].create({
            'res_model_id': model_record.id,
            'res_id': res_id,
            'summary': summary,
            'note': note,
            'date_deadline': date_deadline,
            'activity_type_id': activity_type.id if activity_type else False,
            'user_id': self.env.user.id,
        })
        return {'success': True, 'activity_id': activity.id, 'summary': summary}

    def _tool_chatter_post_message(self, args: dict) -> dict:
        res_model = args.get('res_model')
        res_id = args.get('res_id')
        body = args.get('body')

        if not res_model or not res_id or not body:
            raise UserError("res_model, res_id, and body are required.")

        record = self.env[res_model].browse(res_id)
        if not record.exists():
            raise UserError(f"Record {res_model}#{res_id} does not exist.")

        if hasattr(record, 'message_post'):
            msg = record.message_post(body=body, message_type='comment')
            return {'success': True, 'message_id': msg.id}
        else:
            raise UserError(f"Record {res_model} does not support message chatter.")

    # -------------------------------------------------------------
    # UNIVERSAL ODOO ORM ACCESS TOOLS (READ, CREATE, WRITE, DELETE)
    # -------------------------------------------------------------
    PROTECTED_MODELS = {
        'res.users', 'res.groups', 'ir.model.access', 'ir.rule',
        'ir.module.module', 'ir.cron', 'ir.config_parameter'
    }

    def _tool_orm_inspect_model(self, args: dict) -> dict:
        """Inspect fields, relational dependencies, and model info for any model in Odoo."""
        model_name = args.get('model')
        if not model_name or model_name not in self.env:
            return {'error': f"Model '{model_name}' does not exist or is not installed in this Odoo system."}

        model = self.env[model_name]
        fields_info = {}
        for fname, field in model._fields.items():
            if fname in ('id', 'create_date', 'write_date', 'create_uid', 'write_uid'):
                continue
            fields_info[fname] = {
                'type': field.type,
                'string': field.string,
                'required': bool(field.required),
                'readonly': bool(field.readonly),
                'relation': getattr(field, 'relation', None),
            }
        return {
            'model': model_name,
            'description': model._description,
            'fields_count': len(fields_info),
            'fields': fields_info,
        }

    def _tool_orm_search_read(self, args: dict) -> dict:
        """Universal search and read records from any installed model."""
        model_name = args.get('model')
        if not model_name or model_name not in self.env:
            return {'error': f"Model '{model_name}' does not exist or is not installed."}

        domain = args.get('domain', [])
        if isinstance(domain, list):
            # Unwrap if the LLM provided an outer list wrapper [[...]]
            if len(domain) == 1 and isinstance(domain[0], list) and any(isinstance(y, (list, tuple)) or y in ('&', '|', '!') for y in domain[0]):
                domain = domain[0]
            clean_dom = []
            for item in domain:
                if isinstance(item, (list, tuple)):
                    clean_dom.append(tuple(item))
                elif isinstance(item, str):
                    clean_dom.append(item)
            domain = clean_dom
        else:
            domain = []
        fields_to_read = args.get('fields') or ['display_name']
        limit = min(int(args.get('limit', 20)), 100)
        order = args.get('order', 'id desc')

        # Intercept res.config.settings (Transient wizard - read via default_get)
        if model_name == 'res.config.settings':
            try:
                valid_fields = [f for f in fields_to_read if f in self.env['res.config.settings']._fields] if fields_to_read else list(self.env['res.config.settings']._fields.keys())
                defaults = self.env['res.config.settings'].default_get(valid_fields)
                defaults['id'] = 1
                defaults['display_name'] = 'System Configuration'
                return {
                    'model': 'res.config.settings',
                    'records': [defaults],
                    'returned_count': 1,
                    'total_count': 1,
                }
            except Exception as e:
                return {'error': f"Failed reading settings from 'res.config.settings': {str(e)}"}

        try:
            records = self.env[model_name].search_read(domain=domain, fields=fields_to_read, limit=limit, order=order)
            total_count = self.env[model_name].search_count(domain)
            return {
                'model': model_name,
                'records': records,
                'returned_count': len(records),
                'total_count': total_count,
            }
        except Exception as e:
            return {'error': f"Failed searching '{model_name}': {str(e)}"}

    def _smart_prepare_orm_values(self, model_name: str, values: dict) -> dict:
        """Intelligently clean, validate, and coerce field values for Odoo ORM create/write.
        Handles Many2one string-name resolution, One2many/Many2many tuple creation [(0, 0, {...})],
        default_get merging, and datatype normalization across all standard and custom models.
        """
        if not model_name or model_name not in self.env or not isinstance(values, dict):
            return values or {}

        model_obj = self.env[model_name]
        fields_meta = model_obj._fields

        # 1. Fetch model defaults so non-provided mandatory fields are satisfied
        try:
            field_keys = [k for k, f in fields_meta.items() if not f.readonly and not f.compute]
            defaults = model_obj.default_get(field_keys)
        except Exception:
            defaults = {}

        clean_vals = dict(defaults)

        # 2. Iterate provided user values and intelligently format each field
        for fname, val in values.items():
            if fname not in fields_meta:
                continue

            field = fields_meta[fname]
            ftype = field.type

            if val is None or val is False:
                clean_vals[fname] = False
                continue

            # A. Many2one relation resolution (supports human name search or ID)
            if ftype == 'many2one':
                if isinstance(val, str) and val.strip():
                    val_str = val.strip()
                    comodel = field.comodel_name
                    if comodel and comodel in self.env:
                        target_rec = self.env[comodel].search([
                            '|', ('name', '=ilike', val_str), ('display_name', '=ilike', val_str)
                        ], limit=1)
                        if not target_rec:
                            target_rec = self.env[comodel].search([
                                '|', ('name', 'ilike', val_str), ('display_name', 'ilike', val_str)
                            ], limit=1)

                        if target_rec:
                            clean_vals[fname] = target_rec.id
                        elif comodel == 'res.partner':
                            created_p = self.env['res.partner'].create({'name': val_str})
                            clean_vals[fname] = created_p.id
                        elif comodel == 'product.product':
                            created_prod = self.env['product.product'].create({'name': val_str, 'sale_ok': True})
                            clean_vals[fname] = created_prod.id
                        elif comodel == 'uom.uom':
                            u = self.env['uom.uom'].search(['|', ('name', '=ilike', val_str), ('name', 'ilike', val_str)], limit=1)
                            clean_vals[fname] = u.id if u else False
                        else:
                            if 'name' in self.env[comodel]._fields and not self.env[comodel]._transient:
                                try:
                                    rec = self.env[comodel].create({'name': val_str})
                                    clean_vals[fname] = rec.id
                                except Exception:
                                    clean_vals[fname] = False
                            else:
                                clean_vals[fname] = False
                    else:
                        clean_vals[fname] = False
                elif isinstance(val, int):
                    clean_vals[fname] = val
                else:
                    clean_vals[fname] = False

            # B. One2many and Many2many line formatting [(0, 0, {...})]
            elif ftype in ('one2many', 'many2many'):
                if isinstance(val, list):
                    commands = []
                    comodel = field.comodel_name
                    for item in val:
                        if isinstance(item, dict):
                            line_vals = self._smart_prepare_orm_values(comodel, item)
                            commands.append((0, 0, line_vals))
                        elif isinstance(item, (tuple, list)):
                            commands.append(tuple(item))
                        elif isinstance(item, int) and ftype == 'many2many':
                            commands.append((4, item))
                    clean_vals[fname] = commands
                else:
                    clean_vals[fname] = val

            # C. Boolean coercion
            elif ftype == 'boolean':
                if isinstance(val, str):
                    clean_vals[fname] = val.strip().lower() in ('true', '1', 'yes', 'enabled', 'on')
                else:
                    clean_vals[fname] = bool(val)

            # D. Numeric fields
            elif ftype in ('integer',):
                try:
                    clean_vals[fname] = int(val)
                except (ValueError, TypeError):
                    clean_vals[fname] = 0
            elif ftype in ('float', 'monetary'):
                try:
                    clean_vals[fname] = float(val)
                except (ValueError, TypeError):
                    clean_vals[fname] = 0.0

            # E. Date and Datetime coercion
            elif ftype == 'date':
                if isinstance(val, str) and val.lower() in ('today', 'now'):
                    clean_vals[fname] = fields.Date.today()
                else:
                    clean_vals[fname] = val
            elif ftype == 'datetime':
                if isinstance(val, str) and val.lower() in ('now', 'today'):
                    clean_vals[fname] = fields.Datetime.now()
                else:
                    clean_vals[fname] = val

            # F. Standard text, selection, char, json
            else:
                clean_vals[fname] = val

        return clean_vals

    def _tool_orm_create_record(self, args: dict) -> dict:
        """Universal create record in any installed model (Mutating)."""
        model_name = args.get('model')
        values = args.get('values', {})

        if not model_name or model_name not in self.env:
            raise UserError(f"Model '{model_name}' does not exist or is not installed.")
        if model_name in self.PROTECTED_MODELS:
            raise AccessError(f"Direct AI creation on system security model '{model_name}' is restricted.")
        if not values or not isinstance(values, dict):
            raise UserError("Valid field values dictionary is required.")

        # Special handling for res.config.settings: instantiate wizard and execute to persist
        if model_name == 'res.config.settings':
            wizard = self.env['res.config.settings'].create(values)
            wizard.execute()
            updated_names = []
            for k in values.keys():
                field_obj = self.env['res.config.settings']._fields.get(k)
                updated_names.append(field_obj.string if field_obj else k)
            return {
                'success': True,
                'model': 'res.config.settings',
                'id': wizard.id,
                'is_settings': True,
                'updated_fields': values,
                'display_name': 'System Configuration',
                'message': f"Updated and applied system configuration: {', '.join(updated_names)}"
            }

        clean_vals = self._smart_prepare_orm_values(model_name, values)
        record = self.env[model_name].create(clean_vals)
        partner_name = getattr(record, 'partner_id', False) and record.partner_id.name or False
        amount_total = getattr(record, 'amount_total', None)
        return {
            'success': True,
            'model': model_name,
            'id': record.id,
            'display_name': record.display_name or f"{model_name} #{record.id}",
            'partner': partner_name,
            'amount_total': amount_total,
            'message': f"Created {model_name} record #{record.id} ({record.display_name})"
        }

    def _tool_orm_write_record(self, args: dict) -> dict:
        """Universal update record in any installed model (Mutating).

        Enhancements:
        - Strips default 'New' name values to prevent sequence-name overwrite bug.
        - Captures old vs new field diffs for transparent execution messages.
        - Routes state changes through native Odoo workflow methods
          (button_confirm, button_cancel, action_post, button_validate, etc.)
          instead of raw ORM writes, ensuring proper validation and side-effects.
        """
        model_name = args.get('model')
        record_id = args.get('id')
        values = args.get('values', {})

        if not model_name or model_name not in self.env:
            raise UserError(f"Model '{model_name}' does not exist or is not installed.")
        if model_name in self.PROTECTED_MODELS:
            raise AccessError(f"Direct AI mutation on system security model '{model_name}' is restricted.")
        if not record_id or not values:
            raise UserError("Record 'id' and 'values' are required for write.")

        # Special handling for res.config.settings: instantiate wizard and execute to persist
        if model_name == 'res.config.settings':
            wizard = self.env['res.config.settings'].create(values)
            wizard.execute()
            updated_names = []
            for k in values.keys():
                field_obj = self.env['res.config.settings']._fields.get(k)
                updated_names.append(field_obj.string if field_obj else k)
            return {
                'success': True,
                'model': 'res.config.settings',
                'id': wizard.id,
                'is_settings': True,
                'updated_fields': values,
                'display_name': 'System Configuration',
                'message': f"Updated and applied system configuration: {', '.join(updated_names)}"
            }

        record = self.env[model_name].browse(record_id)
        if not record.exists():
            raise UserError(f"Record #{record_id} not found in model '{model_name}'.")

        # ── Safety: Never overwrite a real sequence name with generic defaults ──
        if 'name' in values and values.get('name') in ('New', '/', '', None):
            values = {k: v for k, v in values.items() if k != 'name'}
            if not values:
                raise UserError("No valid fields to update after removing reserved name value.")

        # ── Capture pre-update field values for diff reporting ──
        target_state = values.get('state')
        human_friendly_old = {}
        human_friendly_new = {}
        fields_meta = self.env[model_name]._fields

        STATE_LABELS = {
            'purchase.order': {
                'draft': 'Draft (RFQ)', 'sent': 'RFQ Sent', 'to approve': 'Waiting Approval',
                'purchase': 'Confirmed (Purchase Order)', 'done': 'Locked', 'cancel': 'Cancelled',
            },
            'sale.order': {
                'draft': 'Draft (Quotation)', 'sent': 'Quotation Sent', 'sale': 'Confirmed (Sales Order)',
                'done': 'Locked', 'cancel': 'Cancelled',
            },
            'account.move': {
                'draft': 'Draft', 'posted': 'Posted', 'cancel': 'Cancelled',
            },
            'stock.picking': {
                'draft': 'Draft', 'waiting': 'Waiting', 'confirmed': 'Ready', 'assigned': 'Ready',
                'done': 'Done', 'cancel': 'Cancelled',
            },
        }

        for fname, new_val in values.items():
            fobj = fields_meta.get(fname)
            label = fobj.string if fobj else fname.replace('_', ' ').title()
            # Old value
            try:
                old_raw = getattr(record, fname, None)
                if hasattr(old_raw, 'name'):
                    old_str = old_raw.name or str(old_raw)
                elif isinstance(old_raw, bool):
                    old_str = 'Enabled' if old_raw else 'Disabled'
                else:
                    old_str = str(old_raw) if old_raw is not None else ''
                # Apply state label if available
                if fname == 'state':
                    smap = STATE_LABELS.get(model_name, {})
                    old_str = smap.get(str(old_raw), old_str)
            except Exception:
                old_str = ''
            # New value label
            if fname == 'state':
                smap = STATE_LABELS.get(model_name, {})
                new_str = smap.get(str(new_val), str(new_val))
            elif isinstance(new_val, bool):
                new_str = 'Enabled' if new_val else 'Disabled'
            else:
                new_str = str(new_val) if new_val is not None else ''
            human_friendly_old[label] = old_str
            human_friendly_new[label] = new_str

        # ── Route state changes through native Odoo workflow methods ──
        WORKFLOW_METHODS = {
            'purchase.order': {
                'purchase': 'button_confirm',
                'cancel': 'button_cancel',
                'draft': 'button_draft',
            },
            'sale.order': {
                'sale': 'action_confirm',
                'cancel': 'action_cancel',
                'draft': 'action_draft',
            },
            'account.move': {
                'posted': 'action_post',
                'cancel': 'button_cancel',
                'draft': 'button_draft',
            },
            'stock.picking': {
                'done': 'button_validate',
                'cancel': 'action_cancel',
            },
        }

        workflow_called = False
        if target_state:
            wf_map = WORKFLOW_METHODS.get(model_name, {})
            method_name = wf_map.get(target_state)
            if method_name and hasattr(record, method_name):
                try:
                    getattr(record, method_name)()
                    workflow_called = True
                    # Remove 'state' from values so we don't double-write
                    values = {k: v for k, v in values.items() if k != 'state'}
                except Exception as wf_err:
                    raise UserError(f"Workflow action failed: {wf_err}")

        # ── Apply remaining field updates ──
        if values:
            clean_vals = self._smart_prepare_orm_values(model_name, values)
            record.write(clean_vals)

        # Resolve record display name (guaranteed to be the real sequence name)
        rec_display = ''
        try:
            cand = getattr(record, 'name', None)
            if cand and cand not in ('New', '/', False, ''):
                rec_display = cand
            else:
                rec_display = record.display_name or f"{model_name} #{record.id}"
        except Exception:
            rec_display = f"{model_name} #{record.id}"

        partner_name = getattr(record, 'partner_id', False) and record.partner_id.name or False
        amount_total = getattr(record, 'amount_total', None)

        return {
            'success': True,
            'model': model_name,
            'id': record.id,
            'display_name': rec_display,
            'partner': partner_name,
            'amount_total': amount_total,
            'workflow_called': workflow_called,
            'updated_fields_diff': {
                label: {'old': human_friendly_old.get(label, ''), 'new': human_friendly_new.get(label, '')}
                for label in human_friendly_new
            },
            'message': f"Updated {model_name} record #{record.id} ({rec_display})"
        }

    def _tool_orm_unlink_record(self, args: dict) -> dict:
        """Universal delete record in any installed model with automatic pre-requisite cancellation.

        Features:
        - Pre-captures display name, partner, and amounts before deletion.
        - Automatically detects and executes required cancellation workflows across
          Purchase, Sales, Invoicing, Stock, Manufacturing, and any custom models.
        - Suppresses dead links by returning is_deleted=True.
        """
        model_name = args.get('model')
        record_id = args.get('id')

        if not model_name or model_name not in self.env:
            raise UserError(f"Model '{model_name}' does not exist or is not installed.")
        if model_name in self.PROTECTED_MODELS:
            raise AccessError(f"Direct AI deletion on system security model '{model_name}' is restricted.")
        if not record_id:
            raise UserError("Record 'id' is required for deletion.")

        record = self.env[model_name].browse(record_id)
        if not record.exists():
            raise UserError(f"Record #{record_id} not found in model '{model_name}'.")

        # ── Capture record metadata BEFORE unlinking ──
        try:
            cand = getattr(record, 'name', None)
            if cand and cand not in ('New', '/', False, ''):
                rec_display = cand
            else:
                rec_display = record.display_name or f"{model_name} #{record.id}"
        except Exception:
            rec_display = f"{model_name} #{record.id}"

        partner_name = getattr(record, 'partner_id', False) and record.partner_id.name or False
        amount_total = getattr(record, 'amount_total', None)
        try:
            model_desc = self.env[model_name]._description or model_name
        except Exception:
            model_desc = model_name

        pre_actions = []

        # ── Universal Pre-Deletion Cancellation Pipeline ──
        try:
            # 1. Purchase Orders: must cancel pickings and order before unlink
            if model_name == 'purchase.order':
                if getattr(record, 'state', None) != 'cancel':
                    if hasattr(record, 'picking_ids'):
                        for pick in record.picking_ids:
                            if pick.state not in ('done', 'cancel'):
                                try:
                                    pick.action_cancel()
                                except Exception:
                                    pass
                    if hasattr(record, 'button_cancel'):
                        record.button_cancel()
                        pre_actions.append("Automatically cancelled purchase order prior to deletion")

            # 2. Sales Orders: cancel pickings and order
            elif model_name == 'sale.order':
                if getattr(record, 'state', None) != 'cancel':
                    if hasattr(record, 'picking_ids'):
                        for pick in record.picking_ids:
                            if pick.state not in ('done', 'cancel'):
                                try:
                                    pick.action_cancel()
                                except Exception:
                                    pass
                    if hasattr(record, 'action_cancel'):
                        record.action_cancel()
                        pre_actions.append("Automatically cancelled sales order prior to deletion")

            # 3. Account Moves / Invoices / Bills
            elif model_name == 'account.move':
                if getattr(record, 'state', None) != 'cancel':
                    if record.state == 'posted' and hasattr(record, 'button_draft'):
                        try:
                            record.button_draft()
                        except Exception:
                            pass
                    if hasattr(record, 'button_cancel'):
                        record.button_cancel()
                        pre_actions.append("Automatically cancelled accounting entry prior to deletion")

            # 4. Stock Transfers (Pickings)
            elif model_name == 'stock.picking':
                if getattr(record, 'state', None) != 'cancel':
                    if hasattr(record, 'action_cancel'):
                        record.action_cancel()
                        pre_actions.append("Automatically cancelled stock transfer prior to deletion")

            # 5. Manufacturing Orders (MRP)
            elif model_name == 'mrp.production':
                if getattr(record, 'state', None) != 'cancel':
                    if hasattr(record, 'action_cancel'):
                        record.action_cancel()
                        pre_actions.append("Automatically cancelled manufacturing order prior to deletion")

            # 6. Universal Fallback for ANY Standard or Custom Model with state workflow
            elif hasattr(record, 'state') and getattr(record, 'state', None) != 'cancel':
                fields_meta = self.env[model_name]._fields.get('state')
                has_cancel_state = False
                if fields_meta and hasattr(fields_meta, 'selection'):
                    sel = fields_meta.selection
                    if callable(sel):
                        sel = sel(record)
                    has_cancel_state = any(k == 'cancel' for k, _ in sel) if isinstance(sel, list) else False

                if has_cancel_state:
                    if hasattr(record, 'button_cancel'):
                        record.button_cancel()
                        pre_actions.append("Automatically executed cancellation workflow (button_cancel)")
                    elif hasattr(record, 'action_cancel'):
                        record.action_cancel()
                        pre_actions.append("Automatically executed cancellation workflow (action_cancel)")
        except Exception as pre_err:
            _logger.warning("GSUS AI pre-deletion workflow step failed for %s #%s: %s", model_name, record_id, pre_err)

        # ── Execute Unlink with Resilient Exception Recovery ──
        try:
            record.unlink()
        except UserError as ue:
            ue_str = str(ue).lower()
            if 'cancel' in ue_str or 'state' in ue_str:
                # Retry after explicit cancel attempt
                try:
                    if hasattr(record, 'button_cancel'):
                        record.button_cancel()
                    elif hasattr(record, 'action_cancel'):
                        record.action_cancel()
                    elif 'state' in self.env[model_name]._fields:
                        record.write({'state': 'cancel'})
                    record.unlink()
                    pre_actions.append("Resolved state constraint and deleted record")
                except Exception as retry_err:
                    raise UserError(f"Could not delete {model_desc} #{record_id}: {retry_err}")
            else:
                raise ue

        return {
            'success': True,
            'is_deleted': True,
            'model': model_name,
            'id': record_id,
            'display_name': rec_display,
            'model_description': model_desc,
            'partner': partner_name,
            'amount_total': amount_total,
            'pre_actions': pre_actions,
            'message': f"Permanently deleted {model_desc} {rec_display} (#{record_id})"
        }

    # -------------------------------------------------------------
    # APPLICATION LIFECYCLE MANAGEMENT (LIST, INSTALL, UPGRADE, UNINSTALL)
    # -------------------------------------------------------------
    def _tool_app_list_modules(self, args: dict) -> dict:
        """List Odoo apps with their installation status, description, and state."""
        state = args.get('state')
        search_query = args.get('query', '').strip()

        domain = []
        if state:
            domain.append(('state', '=', state))
        if search_query:
            domain.extend(['|', ('name', 'ilike', search_query), ('shortdesc', 'ilike', search_query)])

        modules = self.env['ir.module.module'].sudo().search_read(
            domain,
            ['name', 'shortdesc', 'state', 'author', 'category_id', 'website', 'summary'],
            limit=args.get('limit', 30),
            order='state asc, shortdesc asc'
        )
        return {
            'modules': modules,
            'count': len(modules),
            'filter_state': state,
        }

    def _tool_app_install_module(self, args: dict) -> dict:
        """Install an Odoo module by technical name."""
        if not self.env.user.has_group('base.group_system'):
            raise AccessError("Only System Administrators can install modules.")

        module_name = args.get('module_name', '').strip()
        if not module_name:
            raise UserError("Technical 'module_name' is required.")

        module = self.env['ir.module.module'].sudo().search([('name', '=', module_name)], limit=1)
        if not module:
            raise UserError(f"Module '{module_name}' not found in Odoo addons path.")

        if module.state == 'installed':
            return {'success': True, 'message': f"Module '{module.shortdesc or module_name}' is already installed."}

        module.button_immediate_install()
        return {
            'success': True,
            'action': 'install',
            'module_name': module_name,
            'shortdesc': module.shortdesc,
            'message': f"Module '{module.shortdesc or module_name}' was successfully installed!"
        }

    def _tool_app_upgrade_module(self, args: dict) -> dict:
        """Upgrade/update an installed Odoo module."""
        if not self.env.user.has_group('base.group_system'):
            raise AccessError("Only System Administrators can upgrade modules.")

        module_name = args.get('module_name', '').strip()
        if not module_name:
            raise UserError("Technical 'module_name' is required.")

        module = self.env['ir.module.module'].sudo().search([('name', '=', module_name)], limit=1)
        if not module:
            raise UserError(f"Module '{module_name}' not found.")

        module.button_immediate_upgrade()
        return {
            'success': True,
            'action': 'upgrade',
            'module_name': module_name,
            'shortdesc': module.shortdesc,
            'message': f"Module '{module.shortdesc or module_name}' was successfully upgraded!"
        }

    def _tool_app_uninstall_module(self, args: dict) -> dict:
        """Uninstall an installed Odoo module."""
        if not self.env.user.has_group('base.group_system'):
            raise AccessError("Only System Administrators can uninstall modules.")

        module_name = args.get('module_name', '').strip()
        if not module_name:
            raise UserError("Technical 'module_name' is required.")

        module = self.env['ir.module.module'].sudo().search([('name', '=', module_name)], limit=1)
        if not module:
            raise UserError(f"Module '{module_name}' not found.")

        if module.state != 'installed':
            return {'success': True, 'message': f"Module '{module.shortdesc or module_name}' is not currently installed."}

        module.button_immediate_uninstall()
        return {
            'success': True,
            'action': 'uninstall',
            'module_name': module_name,
            'shortdesc': module.shortdesc,
            'message': f"Module '{module.shortdesc or module_name}' was uninstalled."
        }

    def _tool_automation_create_or_update(self, args: dict) -> dict:
        """Create or configure an automated business rule (base.automation)."""
        if not self.env.user.has_group('base.group_system'):
            raise AccessError("Only System Administrators can create or update automations.")

        name = args.get('name', '').strip()
        model_name = args.get('model_name', '').strip()
        trigger = args.get('trigger', 'on_create_or_write')

        if not name or not model_name:
            raise UserError("'name' and 'model_name' are required to configure an automation.")

        model = self.env['ir.model'].sudo().search([('model', '=', model_name)], limit=1)
        if not model:
            raise UserError(f"Model '{model_name}' not found.")

        automation = self.env['base.automation'].sudo().create({
            'name': name,
            'model_id': model.id,
            'trigger': trigger if hasattr(self.env['base.automation'], 'trigger') else 'on_create',
            'active': True,
        })
        return {
            'success': True,
            'automation_id': automation.id,
            'name': automation.name,
            'model': model_name,
            'message': f"Automated Action '{automation.name}' configured successfully for model {model_name}."
        }

    def _tool_accounting_describe_report(self, args: dict) -> dict:
        """Summarize financial and accounting report figures for management."""
        domain = [('company_id', '=', self.env.company.id)]
        moves = self.env['account.move'].sudo().search(domain + [('state', '=', 'posted')], limit=100)
        invoices = moves.filtered(lambda m: m.move_type in ('out_invoice', 'out_refund'))

        total_receivable = sum(invoices.mapped('amount_residual'))
        total_invoiced = sum(invoices.mapped('amount_total'))

        return {
            'company': self.env.company.name,
            'currency': self.env.company.currency_id.symbol,
            'posted_invoices_count': len(invoices),
            'total_invoiced': round(total_invoiced, 2),
            'total_receivable_due': round(total_receivable, 2),
            'summary': f"Company: {self.env.company.name} | Total Invoiced: {self.env.company.currency_id.symbol}{total_invoiced:,.2f} | Open Receivables: {self.env.company.currency_id.symbol}{total_receivable:,.2f}"
        }

    # -------------------------------------------------------------
    # UNIVERSAL SYSTEM SETTINGS & CONFIGURATION TOOLS
    # -------------------------------------------------------------
    def _resolve_config_field(self, field_key: str):
        """Intelligently map technical or natural names to res.config.settings fields.
        Supports core apps (Inventory, Sales, Purchase, Accounting) and custom modules.
        """
        config_model = self.env['res.config.settings']
        fields = config_model._fields

        if not field_key:
            return None, None

        key_str = str(field_key).strip()

        # 1. Exact match on technical field name
        if key_str in fields:
            return key_str, fields[key_str]

        clean_key = key_str.lower().replace('-', '_').replace(' ', '_')

        # 2. Direct clean key match
        if clean_key in fields:
            return clean_key, fields[clean_key]

        # 3. Common Odoo config prefixes
        candidate_prefixes = [
            f"group_{clean_key}",
            f"group_stock_{clean_key}",
            f"group_sale_{clean_key}",
            f"group_purchase_{clean_key}",
            f"module_{clean_key}",
            f"module_stock_{clean_key}",
        ]
        for candidate in candidate_prefixes:
            if candidate in fields:
                return candidate, fields[candidate]

        # 4. Normalized comparison (handling underscores vs spaces and singular/plural)
        q_norm = key_str.lower().replace('-', ' ').replace('_', ' ').strip()
        q_words = [w for w in q_norm.split() if w]
        q_stems = [w.rstrip('s') for w in q_words]

        # 4a. Exact normalized label match
        for fname, f_obj in fields.items():
            l_norm = (f_obj.string or '').lower().replace('-', ' ').replace('_', ' ').strip()
            if q_norm == l_norm:
                return fname, f_obj
            l_words = [w for w in l_norm.split() if w]
            l_stems = [w.rstrip('s') for w in l_words]
            if q_stems and q_stems == l_stems:
                return fname, f_obj

        # 4b. Substring or subset word matching on label
        for fname, f_obj in fields.items():
            l_norm = (f_obj.string or '').lower().replace('-', ' ').replace('_', ' ').strip()
            l_stems = set([w.rstrip('s') for w in l_norm.split() if w])
            if q_stems and set(q_stems).issubset(l_stems):
                return fname, f_obj

        # 4c. Partial label or technical field name match
        for fname, f_obj in fields.items():
            l_norm = (f_obj.string or '').lower()
            if q_norm in l_norm or clean_key in fname.lower():
                return fname, f_obj

        return None, None

    def _tool_config_get_settings(self, args: dict) -> dict:
        """Inspect configuration settings across any installed Odoo app or custom module (Read)."""
        setting_names = args.get('setting_names') or args.get('query') or []
        if isinstance(setting_names, str):
            setting_names = [s.strip() for s in setting_names.split(',') if s.strip()]

        if not setting_names:
            return {'error': "Please specify at least one setting name or keyword to inspect.", 'settings': []}

        config_model = self.env['res.config.settings']
        resolved_map = {}
        unresolved = []

        for query_name in setting_names:
            fname, f_obj = self._resolve_config_field(query_name)
            if fname:
                resolved_map[fname] = f_obj
            else:
                unresolved.append(query_name)

        if not resolved_map:
            return {
                'settings': [],
                'unresolved': unresolved,
                'message': f"Could not find configuration settings matching: {', '.join(unresolved)}"
            }

        try:
            defaults = config_model.default_get(list(resolved_map.keys()))
        except Exception as e:
            return {'error': f"Failed reading settings: {str(e)}", 'settings': []}

        results = []
        for fname, f_obj in resolved_map.items():
            val = defaults.get(fname)
            results.append({
                'field': fname,
                'name': f_obj.string or fname,
                'value': val,
                'status': 'Enabled' if bool(val) else 'Disabled',
                'type': f_obj.type,
                'help': f_obj.help or '',
            })

        return {
            'settings': results,
            'count': len(results),
            'unresolved': unresolved,
            'summary': "; ".join([f"{r['name']}: {r['status']}" for r in results])
        }

    def _tool_config_set_settings(self, args: dict) -> dict:
        """Enable or disable configuration settings across any installed app or custom module (Mutating)."""
        settings_input = args.get('settings') or {}
        if not settings_input or not isinstance(settings_input, dict):
            raise UserError("A dictionary of settings to configure is required.")

        config_model = self.env['res.config.settings']
        resolved_vals = {}
        details = []

        for key, val in settings_input.items():
            fname, f_obj = self._resolve_config_field(key)
            if not fname:
                raise UserError(f"Configuration setting '{key}' could not be found.")

            target_val = val
            if f_obj.type == 'boolean':
                if isinstance(val, str):
                    target_val = val.lower() in ('true', '1', 'yes', 'enable', 'enabled')
                else:
                    target_val = bool(val)

            resolved_vals[fname] = target_val
            label = f_obj.string or fname
            status_text = "Enabled" if target_val is True else ("Disabled" if target_val is False else str(target_val))
            details.append(f"{label}: {status_text}")

        # Instantiate wizard and execute to persist changes
        wizard = config_model.create(resolved_vals)
        wizard.execute()

        return {
            'success': True,
            'model': 'res.config.settings',
            'id': wizard.id,
            'is_settings': True,
            'updated_fields': resolved_vals,
            'display_name': 'System Configuration',
            'message': f"Updated configuration: {', '.join(details)}",
            'details': details,
        }

    def _tool_config_manage_settings(self, args: dict) -> dict:
        """Unified router for settings management."""
        action = args.get('action', 'get')
        if action == 'set':
            return self._tool_config_set_settings(args)
        return self._tool_config_get_settings(args)


