# -*- coding: utf-8 -*-
# Part of GSUS AI. See LICENSE file for full copyright and licensing details.

import re
import json
import logging
from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class GsusAiConversation(models.Model):
    _name = 'gsus.ai.conversation'
    _description = 'GSUS AI Conversational Session'
    _order = 'is_pinned desc, write_date desc'

    name = fields.Char(string='Title', default='New Chat', required=True)
    user_id = fields.Many2one('res.users', string='Owner', default=lambda self: self.env.user, required=True, index=True)
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company, required=True)

    agent_id = fields.Many2one('gsus.ai.agent', string='Active Agent', ondelete='set null')
    provider_id = fields.Many2one('gsus.ai.provider', string='AI Provider', required=True)
    model_name = fields.Char(string='Model', required=True)
    system_prompt = fields.Text(string='System Instructions')

    message_ids = fields.One2many('gsus.ai.message', 'conversation_id', string='Messages')
    proposal_ids = fields.One2many('gsus.ai.action.proposal', 'conversation_id', string='Action Proposals')

    is_pinned = fields.Boolean(string='Pinned', default=False)
    is_archived = fields.Boolean(string='Archived', default=False)

    total_messages_count = fields.Integer(string='Messages Count', compute='_compute_counts', store=True)
    total_tokens_count = fields.Integer(string='Tokens Used', compute='_compute_counts', store=True)

    @api.depends('message_ids')
    def _compute_counts(self):
        for record in self:
            record.total_messages_count = len(record.message_ids)
            record.total_tokens_count = sum(record.message_ids.mapped('token_count'))

    @api.onchange('agent_id')
    def _onchange_agent_id(self):
        if self.agent_id:
            if self.agent_id.provider_id:
                self.provider_id = self.agent_id.provider_id
                self.model_name = self.agent_id.model_override or self.agent_id.provider_id.model_name
            self.system_prompt = self.agent_id.system_prompt

    @api.model
    def _generate_smart_title(self, text: str) -> str:
        """Generate a concise, elegant ChatGPT-style topic title (2 to 4 words in Title Case)."""
        if not text:
            return "Conversation"

        clean = text.strip()
        clean = re.sub(r'(!\[.*?\]\(.*?\)|🖼️.*|📎.*)', '', clean).strip()

        fluff_openers = [
            r'^(i\s+want\s+to|i\s+want|i\s+would\s+like\s+to|i\s+need\s+to|i\s+need)\s+',
            r'^(can\s+you\s+please|could\s+you\s+please|can\s+you|could\s+you|would\s+you)\s+',
            r'^(please\s+check\s+and|please\s+check\s+the|please\s+check|please\s+tell\s+me|please\s+show\s+me|please)\s+',
            r'^(kindly\s+check|kindly\s+tell\s+me|kindly)\s+',
            r'^(tell\s+me\s+about|tell\s+me\s+the|tell\s+me|show\s+me\s+the|show\s+me|check\s+the|check)\s+',
            r'^(how\s+to\s+configure|how\s+to\s+setup|how\s+to\s+set\s+up|how\s+to|what\s+is\s+the|what\s+is)\s+',
            r'^(do\s+you\s+know|help\s+me\s+with|help\s+me)\s+',
            r'^(hi\s+there|hello\s+there|hey\s+there|hi|hello|hey|vanakkam|sollu\s+bro)\s*',
        ]
        topic = clean
        for pattern in fluff_openers:
            topic = re.sub(pattern, '', topic, flags=re.IGNORECASE).strip()

        fluff_closers = [
            r'[\s,\.\?!]+(tell\s+me|please|ok|okay|stricly|strictly|now|right\s+now|for\s+me|in\s+odoo|today|thanks|thank\s+you)[\s,\.\?!]*$',
            r'[\s,\.\?!]+(check\s+or\s+uncheck|enabled\s+or\s+disabled|yes\s+or\s+no)[\s,\.\?!]*$',
        ]
        for pattern in fluff_closers:
            topic = re.sub(pattern, '', topic, flags=re.IGNORECASE).strip()

        if not topic:
            lower = clean.lower()
            if any(g in lower for g in ('hi', 'hey', 'hello', 'vanakkam')):
                return "Quick Chat"
            return "General Inquiry"

        topic_lower = topic.lower()
        if 'storage location' in topic_lower or 'multi location' in topic_lower:
            if 'disable' in topic_lower or 'uncheck' in topic_lower:
                return "Disable Storage Locations"
            elif 'enable' in topic_lower or 'check' in topic_lower:
                return "Enable Storage Locations"
            return "Storage Locations Setup"

        topic = re.sub(r'[^\w\s]', ' ', topic)
        stop_words = {'the', 'a', 'an', 'is', 'it', 'to', 'or', 'and', 'in', 'on', 'at', 'of', 'for', 'with', 'from', 'by', 'my', 'your'}
        words = [w for w in topic.split() if len(w) > 1 and w.lower() not in stop_words]
        if words:
            return " ".join([w.capitalize() for w in words[:4]])
        fallback_words = clean.split()[:4]
        return " ".join([w.capitalize() for w in fallback_words]) if fallback_words else "Conversation"

    def send_user_message(self, content: str, record_context: dict = None, file_data: dict = None) -> dict:
        """Process user message, execute tools, contact provider, and return updated chat state."""
        self.ensure_one()
        if not content and not record_context and not file_data:
            raise UserError("Message content or attached file cannot be empty.")

        file_prompt_context = ""
        user_display_content = content or ""

        # Handle attached file
        if file_data and isinstance(file_data, dict):
            fname = file_data.get('name', 'uploaded_file')
            fsize = file_data.get('size', 0)
            raw_content = file_data.get('content', '')
            is_text = file_data.get('is_text', True)
            is_image = file_data.get('is_image', False) or (file_data.get('type', '').startswith('image/'))

            # Store in ir.attachment
            att = None
            try:
                import base64
                if is_text:
                    if isinstance(raw_content, str):
                        raw_bytes = raw_content.encode('utf-8')
                    elif isinstance(raw_content, bytes):
                        raw_bytes = raw_content
                    else:
                        raw_bytes = b''
                else:
                    if isinstance(raw_content, str):
                        b64_str = raw_content
                        if ',' in b64_str:
                            b64_str = b64_str.split(',', 1)[1]
                        try:
                            raw_bytes = base64.b64decode(b64_str)
                        except Exception:
                            raw_bytes = raw_content.encode('utf-8')
                    elif isinstance(raw_content, bytes):
                        raw_bytes = raw_content
                    else:
                        raw_bytes = b''

                mimetype = file_data.get('type') or ('image/png' if is_image else 'application/octet-stream')
                att = self.env['ir.attachment'].sudo().create({
                    'name': fname,
                    'res_model': 'gsus.ai.conversation',
                    'res_id': self.id,
                    'type': 'binary',
                    'raw': raw_bytes,
                    'mimetype': mimetype,
                })
            except Exception as att_err:
                _logger.warning("Failed to store chat attachment: %s", str(att_err))

            # Build file context for AI
            if is_image:
                file_prompt_context = f"\n\n[USER ATTACHED IMAGE: '{fname}' ({fsize} bytes)]\nThe user uploaded this image to the conversation."
            elif is_text and raw_content:
                text_preview = raw_content[:15000]
                file_prompt_context = (
                    f"\n\n[USER ATTACHED FILE: '{fname}' ({fsize} bytes)]\n"
                    f"--- FILE CONTENT BEGIN ---\n{text_preview}\n--- FILE CONTENT END ---\n"
                    "Analyze and process the attached file data above to answer the user's inquiry or execute requested actions."
                )
            else:
                file_prompt_context = f"\n\n[USER ATTACHED FILE: '{fname}' ({fsize} bytes, binary format)]"

            # Format file size for user display
            fsize_str = ""
            if fsize:
                if fsize < 1024:
                    fsize_str = f"{fsize} B"
                elif fsize < 1024 * 1024:
                    fsize_str = f"{fsize / 1024:.1f} KB"
                else:
                    fsize_str = f"{fsize / (1024 * 1024):.1f} MB"

            if is_image and att:
                img_url = f"/gsus_ai/media/{att.id}"
                badge_title = f"{fname} | {fsize_str}" if fsize_str else fname
                attachment_badge = f"![{badge_title}]({img_url})"
            elif is_image:
                attachment_badge = f"🖼️ **Attached Image:** `{fname}` ({fsize_str})" if fsize_str else f"🖼️ **Attached Image:** `{fname}`"
            else:
                attachment_badge = f"📎 **Attached File:** `{fname}` ({fsize_str})" if fsize_str else f"📎 **Attached File:** `{fname}`"
            user_display_content = f"{attachment_badge}\n\n{content}" if content else attachment_badge

        # Create user message record
        user_msg = self.env['gsus.ai.message'].create({
            'conversation_id': self.id,
            'role': 'user',
            'content': user_display_content,
        })

        # Dynamically set smart ChatGPT-style title if it's the first message
        if len(self.message_ids) <= 2 and self.name in ('New Chat', 'New Conversation'):
            smart_title = self._generate_smart_title(content or (file_data.get('name') if file_data else "Chat"))
            self.name = smart_title

        # Prepare messages history
        messages_payload = []
        if self.system_prompt:
            messages_payload.append({'role': 'system', 'content': self.system_prompt})

        # Inject business record context if provided (e.g. current lead, sale order, partner)
        if record_context:
            context_text = self.env['gsus.ai.context.builder'].build_context_prompt(record_context)
            if context_text:
                messages_payload.append({
                    'role': 'system',
                    'content': f"Current Odoo Business Record Context:\n{context_text}",
                })

        # Append clean dialogue history for context window management (user/assistant turns only)
        # Limit to the last 6 messages and truncate oversized historical assistant turns to prevent TPM exhaustion
        dialogue_messages = self.message_ids.filtered(
            lambda m: m.role in ('user', 'assistant') and m.content and not m.is_error
        ).sorted('id')[-6:]
        for m in dialogue_messages:
            txt = m.content.strip()
            if m.role == 'assistant' and len(txt) > 1200:
                txt = txt[:1200] + "\n...(truncated for context)..."
            messages_payload.append({'role': m.role, 'content': txt})

        # Inject file prompt content into the current message payload
        if file_prompt_context and messages_payload and messages_payload[-1]['role'] == 'user':
            messages_payload[-1]['content'] += file_prompt_context
            if file_data and file_data.get('is_image') and file_data.get('content'):
                messages_payload[-1]['image_data'] = {
                    'mime_type': file_data.get('type') or 'image/png',
                    'data': file_data.get('content'),
                }

        # Retrieve authorized tools
        tools_list = []
        if self.agent_id:
            active_tools = self.agent_id.get_effective_tools()
        else:
            active_tools = self.env['gsus.ai.tool'].search([('is_active', '=', True), ('use_in_ai', '=', True)])

        for t in active_tools:
            tools_list.append({
                'code': t.code,
                'name': t.name,
                'description': t.description,
                'json_schema': t.json_schema,
            })

        # Get adapter and invoke provider
        adapter = self.provider_id.get_adapter()
        response = adapter.generate_response(
            messages_payload, 
            tools=tools_list, 
            options={'model': self.model_name or self.provider_id.model_name}
        )

        # Track usage in provider
        self.provider_id.track_usage(response.total_tokens)

        # Execute tool calls or return direct response
        if response.has_tool_calls:
            return self._run_tool_execution_loop(messages_payload, tools_list, response, adapter)

        # Regular assistant response without tool calls
        final_content = (response.content or "").strip()
        if not final_content and not response.is_success:
            final_content = f"⚠️ Provider notice ({self.model_name or self.provider_id.model_name}): {response.error or 'Temporary error.'}"
        elif not final_content:
            final_content = "No response returned."

        self.env['gsus.ai.message'].create({
            'conversation_id': self.id,
            'role': 'assistant',
            'content': final_content,
            'token_count': response.total_tokens,
            'duration_seconds': response.duration_ms / 1000.0,
            'is_error': not response.is_success,
            'error_text': response.error or "",
        })

        return {'status': 'success', 'proposals': []}

    def _run_tool_execution_loop(self, messages_payload: list, tools_list: list, initial_response, adapter) -> dict:
        """Execute tool calls in a robust multi-turn loop (up to 4 rounds)
        until the AI produces final text or proposes a mutating action.
        """
        max_tool_rounds = 4
        current_round = 0
        current_response = initial_response

        while current_response.has_tool_calls and current_round < max_tool_rounds:
            current_round += 1

            # 1. Check if any tool call requires user confirmation (mutating actions)
            has_pending_mutation = False
            pending_proposals = []
            assistant_msg_record = None

            for call in current_response.tool_calls:
                call_id = call.get('id', '')
                tool_code = call.get('name', '')
                args = call.get('arguments', {})
                tool = self.env['gsus.ai.tool'].search([('code', '=', tool_code), ('is_active', '=', True), ('use_in_ai', '=', True)], limit=1)

                if tool and tool.operation_type == 'mutate' and tool.requires_confirmation:
                    has_pending_mutation = True
                    if not assistant_msg_record:
                        assistant_msg_record = self.env['gsus.ai.message'].create({
                            'conversation_id': self.id,
                            'role': 'assistant',
                            'content': current_response.content or f"I would like to execute {tool.name}. Please confirm or reject below:",
                            'tool_calls_json': json.dumps(current_response.tool_calls),
                            'token_count': current_response.total_tokens,
                            'duration_seconds': current_response.duration_ms / 1000.0,
                        })
                    proposal = self.env['gsus.ai.action.proposal'].create({
                        'conversation_id': self.id,
                        'message_id': assistant_msg_record.id,
                        'tool_id': tool.id,
                        'tool_call_id': call_id,
                        'arguments_json': json.dumps(args, indent=2),
                        'summary': self._generate_smart_proposal_summary(tool, args),
                        'state': 'pending',
                    })
                    pending_proposals.append(proposal.read()[0])

            if has_pending_mutation:
                return {'status': 'success', 'proposals': pending_proposals}

            # 2. Append assistant tool calls to dialogue payload
            formatted_calls = []
            for call in current_response.tool_calls:
                c_args = call.get('arguments', {})
                formatted_calls.append({
                    'id': call.get('id', ''),
                    'name': call.get('name', ''),
                    'thought_signature': call.get('thought_signature'),
                    'type': 'function',
                    'function': {
                        'name': call.get('name', ''),
                        'arguments': json.dumps(c_args) if isinstance(c_args, dict) else str(c_args)
                    }
                })

            messages_payload.append({
                'role': 'assistant',
                'content': current_response.content or "",
                'tool_calls': formatted_calls,
            })

            # 3. Execute all read tools in this round
            for call in current_response.tool_calls:
                call_id = call.get('id', '')
                tool_code = call.get('name', '')
                args = call.get('arguments', {})
                tool = self.env['gsus.ai.tool'].search([('code', '=', tool_code), ('is_active', '=', True), ('use_in_ai', '=', True)], limit=1)

                tool_result_str = "{}"
                if tool:
                    try:
                        tool_result = tool.execute_tool(args, conversation_id=self.id)
                        tool_result_str = json.dumps(tool_result, default=str)
                    except Exception as e:
                        tool_result_str = json.dumps({'error': str(e)})

                self.env['gsus.ai.message'].create({
                    'conversation_id': self.id,
                    'role': 'tool',
                    'tool_call_id': call_id,
                    'content': tool_result_str,
                })

                messages_payload.append({
                    'role': 'tool',
                    'tool_call_id': call_id,
                    'name': tool_code,
                    'content': tool_result_str,
                })

            # 4. Generate next response, passing tools so model can continue or complete
            current_response = adapter.generate_response(
                messages_payload, 
                tools=tools_list,
                options={'model': self.model_name or self.provider_id.model_name}
            )
            self.provider_id.track_usage(current_response.total_tokens)

        # 5. Save final assistant response (NEVER leave empty)
        final_content = (current_response.content or "").strip()

        # If model executed tools but returned empty content, request a direct synthesis without tools
        if not final_content and current_response.is_success and messages_payload and messages_payload[-1].get('role') == 'tool':
            messages_payload.append({
                'role': 'user',
                'content': "Based on the tool results above, provide a direct, clear and helpful response to my request."
            })
            synthesis_resp = adapter.generate_response(
                messages_payload,
                tools=None,
                options={'model': self.model_name or self.provider_id.model_name}
            )
            if synthesis_resp and synthesis_resp.content:
                final_content = synthesis_resp.content.strip()
                current_response = synthesis_resp

        if not final_content and not current_response.is_success:
            final_content = f"⚠️ Provider notice ({self.model_name or self.provider_id.model_name}): {current_response.error or 'Temporary rate limit. Please try again.'}"
        elif not final_content:
            # Factual fallback based on tool results rather than generic canned message
            last_tool_msg = self.env['gsus.ai.message'].search([
                ('conversation_id', '=', self.id),
                ('role', '=', 'tool')
            ], order='id desc', limit=1)
            if last_tool_msg and last_tool_msg.content:
                try:
                    tool_data = json.loads(last_tool_msg.content)
                    if isinstance(tool_data, dict):
                        if tool_data.get('summary'):
                            final_content = tool_data.get('summary')
                        elif tool_data.get('message'):
                            final_content = tool_data.get('message')
                        elif tool_data.get('settings'):
                            lines = ["Here are the current settings:"]
                            for s in tool_data.get('settings', []):
                                lines.append(f"- **{s.get('name', s.get('field'))}**: {s.get('status', s.get('value'))}")
                            final_content = "\n".join(lines)
                except Exception:
                    pass
            if not final_content:
                final_content = "I have completed the requested operation."

        self.env['gsus.ai.message'].create({
            'conversation_id': self.id,
            'role': 'assistant',
            'content': final_content,
            'token_count': current_response.total_tokens,
            'duration_seconds': current_response.duration_ms / 1000.0,
            'is_error': not current_response.is_success,
            'error_text': current_response.error or "",
        })

        return {'status': 'success', 'proposals': []}

    def edit_user_message(self, message_id: int, new_content: str) -> dict:
        """Edit an existing user message in-place (ChatGPT-style):
        1. Updates the message content to new_content.
        2. Truncates all subsequent messages (assistant responses, tools) after this message.
        3. Re-runs the AI from this point and generates the new assistant response.
        """
        self.ensure_one()
        target_msg = self.env['gsus.ai.message'].browse(message_id)
        if not target_msg.exists() or target_msg.conversation_id.id != self.id:
            raise UserError("Target message not found in this conversation.")
        if target_msg.role != 'user':
            raise UserError("Only user messages can be edited.")
        if not new_content or not new_content.strip():
            raise UserError("Message content cannot be empty.")

        # 1. Update the message content
        target_msg.write({'content': new_content.strip()})

        # Sync conversation title if this is the first user message
        first_user_msg = self.message_ids.filtered(lambda m: m.role == 'user').sorted('id')[:1]
        if first_user_msg and target_msg.id == first_user_msg.id:
            new_title = self._generate_smart_title(new_content)
            self.write({'name': new_title})

        # 2. Delete all messages created after this message (truncate conversation history)
        subsequent_msgs = self.message_ids.filtered(lambda m: m.id > target_msg.id)
        if subsequent_msgs:
            proposals = self.env['gsus.ai.action.proposal'].search([
                ('conversation_id', '=', self.id),
                ('message_id', 'in', subsequent_msgs.ids)
            ])
            proposals.unlink()
            subsequent_msgs.unlink()

        # 3. Generate response using updated dialogue up to target_msg
        messages_payload = []
        if self.system_prompt:
            messages_payload.append({'role': 'system', 'content': self.system_prompt})

        dialogue_messages = self.message_ids.filtered(
            lambda m: m.role in ('user', 'assistant') and m.content and not m.is_error and m.id <= target_msg.id
        ).sorted('id')[-6:]
        for m in dialogue_messages:
            txt = m.content.strip()
            if m.role == 'assistant' and len(txt) > 1200:
                txt = txt[:1200] + "\n...(truncated for context)..."
            messages_payload.append({'role': m.role, 'content': txt})

        # Retrieve authorized tools
        tools_list = []
        if self.agent_id:
            active_tools = self.agent_id.get_effective_tools()
        else:
            active_tools = self.env['gsus.ai.tool'].search([('is_active', '=', True), ('use_in_ai', '=', True)])

        for t in active_tools:
            tools_list.append({
                'code': t.code,
                'name': t.name,
                'description': t.description,
                'json_schema': t.json_schema,
            })

        adapter = self.provider_id.get_adapter()
        response = adapter.generate_response(
            messages_payload, 
            tools=tools_list, 
            options={'model': self.model_name or self.provider_id.model_name}
        )
        self.provider_id.track_usage(response.total_tokens)

        if response.has_tool_calls:
            return self._run_tool_execution_loop(messages_payload, tools_list, response, adapter)

        # Regular assistant response without tool calls
        final_content = (response.content or "").strip()
        if not final_content and not response.is_success:
            final_content = f"⚠️ Provider notice ({self.model_name or self.provider_id.model_name}): {response.error or 'Temporary error.'}"
        elif not final_content:
            final_content = "No response returned."

        self.env['gsus.ai.message'].create({
            'conversation_id': self.id,
            'role': 'assistant',
            'content': final_content,
            'token_count': response.total_tokens,
            'duration_seconds': response.duration_ms / 1000.0,
            'is_error': not response.is_success,
            'error_text': response.error or "",
        })

        return {'status': 'success', 'proposals': []}

    def _generate_smart_proposal_summary(self, tool, args: dict) -> str:
        """Generate a human-friendly, context-aware summary for action proposals.

        Instead of generic 'Proposed action: Universal Record Updater', produces
        business-level summaries like 'Confirm Purchase Order P00007'.
        """
        tool_code = tool.code or ''
        model_name = args.get('model', '')
        record_id = args.get('id')
        values = args.get('values', {})

        # --- State-change workflows ---
        STATE_LABELS = {
            'purchase.order': {
                'purchase': 'Confirm Purchase Order',
                'cancel': 'Cancel Purchase Order',
                'draft': 'Reset Purchase Order to Draft',
                'sent': 'Mark Purchase Order as Sent',
            },
            'sale.order': {
                'sale': 'Confirm Sales Order',
                'cancel': 'Cancel Sales Order',
                'draft': 'Reset Sales Order to Draft',
            },
            'account.move': {
                'posted': 'Post Invoice / Bill',
                'cancel': 'Cancel Invoice / Bill',
                'draft': 'Reset Invoice to Draft',
            },
            'stock.picking': {
                'done': 'Validate Transfer',
                'cancel': 'Cancel Transfer',
            },
            'purchase.order.line': {},
        }

        # Friendly model display names
        MODEL_DISPLAY = {
            'purchase.order': 'Purchase Order',
            'sale.order': 'Sales Order',
            'account.move': 'Invoice / Bill',
            'stock.picking': 'Transfer',
            'crm.lead': 'CRM Lead',
            'project.task': 'Task',
            'hr.employee': 'Employee',
            'res.partner': 'Contact',
            'product.template': 'Product',
        }

        try:
            # Lookup record name to use in title (e.g. P00007 instead of New or #4)
            rec_display = ''
            if record_id and model_name and model_name in self.env:
                rec = self.env[model_name].browse(record_id)
                if rec.exists():
                    cand = getattr(rec, 'name', None) or rec.display_name or ''
                    # Only use the candidate if it's not a generic default
                    if cand and cand not in ('New', '/', False, ''):
                        rec_display = cand
                    elif rec.display_name and rec.display_name not in ('New', '/', False, ''):
                        rec_display = rec.display_name

            model_label = MODEL_DISPLAY.get(model_name, model_name.replace('.', ' ').title() if model_name else '')

            # 1. orm_write_record with state change
            if tool_code == 'orm_write_record' and 'state' in values:
                target_state = values['state']
                state_map = STATE_LABELS.get(model_name, {})
                action_label = state_map.get(target_state, f'Update {model_label}')
                if rec_display:
                    return f"{action_label}: {rec_display}"
                return action_label

            # 2. orm_write_record with field updates (no state)
            if tool_code == 'orm_write_record':
                changed_fields = [k for k in values.keys() if k not in ('id',)]
                if changed_fields:
                    field_labels = []
                    if model_name and model_name in self.env:
                        for fname in changed_fields[:3]:
                            fobj = self.env[model_name]._fields.get(fname)
                            field_labels.append(fobj.string if fobj else fname.replace('_', ' ').title())
                    fields_str = ', '.join(field_labels) if field_labels else 'fields'
                    base = f"Update {model_label}"
                    if rec_display:
                        base = f"{base}: {rec_display}"
                    return f"{base} ({fields_str})"
                return f"Update {model_label} #{record_id or '?'}"

            # 3. orm_create_record
            if tool_code == 'orm_create_record':
                rec_name = values.get('name') or ''
                base = f"Create New {model_label}"
                if rec_name:
                    base = f"{base}: {rec_name}"
                return base

            # 4. orm_unlink_record
            if tool_code == 'orm_unlink_record':
                base = f"Delete {model_label}"
                if rec_display:
                    base = f"{base}: {rec_display}"
                return base

            # 5. Specific domain-tuned tools
            TOOL_LABELS = {
                'purchase_create_order': 'Create Purchase Order',
                'sale_create_order': 'Create Sales Order',
                'configure_system_settings': 'Configure System Settings',
                'app_install_module': 'Install Odoo App',
                'app_upgrade_module': 'Upgrade Odoo App',
                'app_uninstall_module': 'Uninstall Odoo App',
            }
            if tool_code in TOOL_LABELS:
                return TOOL_LABELS[tool_code]

        except Exception:
            pass

        # Fallback: clean up the raw tool name
        return tool.name or 'Confirm Action'
