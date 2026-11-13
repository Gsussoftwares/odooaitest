# -*- coding: utf-8 -*-
# Part of GSUS AI. See LICENSE file for full copyright and licensing details.

import json
import logging
import re
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class GsusAiChatController(http.Controller):

    @http.route(['/gsus_ai/media/<int:attachment_id>'], type='http', auth='public', csrf=False)
    def get_chat_media(self, attachment_id: int, download=False, **kwargs):
        """Serve conversation attachments directly and reliably with HTTP caching."""
        att = request.env['ir.attachment'].sudo().browse(attachment_id)
        if not att.exists():
            raise request.not_found()
        raw_data = att.raw
        if not raw_data:
            placeholder = request.env.ref('web.image_placeholder', raise_if_not_found=False)
            if placeholder and placeholder.sudo().raw:
                raw_data = placeholder.sudo().raw
                mimetype = 'image/png'
            else:
                raise request.not_found()
        else:
            mimetype = att.mimetype or 'image/png'

        headers = [
            ('Content-Type', mimetype),
            ('Content-Length', str(len(raw_data))),
            ('Cache-Control', 'public, max-age=604800'),
        ]
        if download:
            headers.append(('Content-Disposition', f'attachment; filename="{att.name}"'))
        return request.make_response(raw_data, headers)

    @http.route('/gsus_ai/chat/init', type='json', auth='user')
    def get_chat_init_data(self):
        """Load bootstrap metadata for OWL chat interface."""
        env = request.env
        providers = env['gsus.ai.provider'].search_read(
            [('is_active', '=', True)],
            ['id', 'name', 'provider_type', 'model_name', 'state', 'is_active'],
        )
        agents = env['gsus.ai.agent'].search_read(
            [('is_active', '=', True)],
            ['id', 'name', 'code', 'role_description', 'is_default'],
            order='sequence, id',
        )
        conversations = env['gsus.ai.conversation'].search_read(
            [('user_id', '=', env.user.id), ('is_archived', '=', False)],
            ['id', 'name', 'model_name', 'write_date', 'is_pinned', 'total_messages_count'],
            order='is_pinned desc, write_date desc',
            limit=50,
        )
        return {
            'providers': providers,
            'agents': agents,
            'conversations': conversations,
            'user_name': env.user.name,
        }

    @http.route('/gsus_ai/chat/load_conversation', type='json', auth='user')
    def load_conversation(self, conversation_id: int):
        """Retrieve all messages and pending proposals for a conversation."""
        env = request.env
        conv = env['gsus.ai.conversation'].browse(conversation_id)
        if not conv.exists():
            return {'error': 'Conversation not found'}

        messages = []
        for m in conv.message_ids.sorted('id'):
            content = m.content or ''
            if '/web/image/' in content:
                content = re.sub(r'/web/image/(\d+)(?:\?[^)\s]*)?', r'/gsus_ai/media/\1', content)
            messages.append({
                'id': m.id,
                'role': m.role,
                'content': content,
                'token_count': m.token_count,
                'duration_seconds': m.duration_seconds,
                'is_error': m.is_error,
                'error_text': m.error_text,
            })

        proposals = []
        for p in conv.proposal_ids.filtered(lambda pr: pr.state == 'pending'):
            proposals.append({
                'id': p.id,
                'summary': p.summary,
                'tool_name': p.tool_id.name,
                'arguments_json': p.arguments_json,
                'state': p.state,
            })

        return {
            'id': conv.id,
            'name': conv.name,
            'model_name': conv.model_name,
            'provider_id': conv.provider_id.id,
            'provider_name': conv.provider_id.name,
            'messages': messages,
            'pending_proposals': proposals,
        }

    @http.route('/gsus_ai/chat/create_conversation', type='json', auth='user')
    def create_conversation(self, agent_id: int = None, provider_id: int = None):
        """Initialize a new conversation session."""
        env = request.env
        agent = env['gsus.ai.agent'].browse(agent_id) if agent_id else env['gsus.ai.agent'].get_default_agent()
        provider = env['gsus.ai.provider'].browse(provider_id) if provider_id else (agent.provider_id if agent and agent.provider_id else False)
        if not provider:
            provider = env['gsus.ai.provider'].search([('is_active', '=', True), ('state', '=', 'connected')], limit=1)
        if not provider:
            provider = env['gsus.ai.provider'].search([('is_active', '=', True)], limit=1)

        if not provider:
            return {'error': 'No active AI Provider configured. Please add a Groq, Gemini, or Claude provider in Configuration.'}

        model = (agent.model_override if agent and agent.model_override else provider.model_name) or 'default'
        system_prompt = agent.system_prompt if agent else ""

        conv = env['gsus.ai.conversation'].create({
            'name': 'New Chat',
            'agent_id': agent.id if agent else False,
            'provider_id': provider.id,
            'model_name': model,
            'system_prompt': system_prompt,
        })
        return {
            'id': conv.id,
            'name': conv.name,
            'model_name': conv.model_name,
            'provider_id': provider.id,
            'provider_name': provider.name,
        }

    @http.route('/gsus_ai/chat/send', type='json', auth='user')
    def send_chat_message(self, conversation_id: int, message: str, record_context: dict = None, file_data: dict = None):
        """Send user message, execute tools, process optional file, and return updated conversation messages."""
        env = request.env
        conv = env['gsus.ai.conversation'].browse(conversation_id)
        if not conv.exists():
            return {'error': 'Conversation not found'}

        result = conv.send_user_message(message, record_context=record_context, file_data=file_data)
        return self.load_conversation(conv.id)

    @http.route('/gsus_ai/chat/edit_message', type='json', auth='user')
    def edit_chat_message(self, conversation_id: int, message_id: int, new_content: str):
        """Edit a user message in-place and re-generate the assistant response (ChatGPT style)."""
        env = request.env
        conv = env['gsus.ai.conversation'].browse(conversation_id)
        if not conv.exists():
            return {'error': 'Conversation not found'}

        result = conv.edit_user_message(message_id, new_content)
        return self.load_conversation(conv.id)

    @http.route('/gsus_ai/chat/proposal_action', type='json', auth='user')
    def handle_proposal_action(self, proposal_id: int, action: str):
        """Confirm or reject a mutating proposal."""
        env = request.env
        proposal = env['gsus.ai.action.proposal'].browse(proposal_id)
        if not proposal.exists():
            return {'error': 'Proposal not found'}

        if action == 'confirm':
            res = proposal.action_confirm()
        elif action == 'reject':
            res = proposal.action_reject()
        else:
            return {'error': f"Unknown action: {action}"}

        return self.load_conversation(proposal.conversation_id.id)

    @http.route('/gsus_ai/chat/switch_model', type='json', auth='user')
    def switch_model(self, conversation_id: int, provider_id: int, model_name: str):
        """Switch the active provider/model for an existing conversation."""
        env = request.env
        conv = env['gsus.ai.conversation'].browse(conversation_id)
        if not conv.exists():
            return {'error': 'Conversation not found'}
        provider = env['gsus.ai.provider'].browse(provider_id)
        if not provider.exists():
            return {'error': 'Provider not found'}
        conv.write({
            'provider_id': provider.id,
            'model_name': model_name or provider.model_name,
        })
        return {
            'provider_id': provider.id,
            'provider_name': provider.name,
            'model_name': conv.model_name,
        }

    @http.route('/gsus_ai/chat/rename', type='json', auth='user')
    def rename_conversation(self, conversation_id: int, name: str):
        """Rename a conversation."""
        env = request.env
        conv = env['gsus.ai.conversation'].browse(conversation_id)
        if not conv.exists():
            return {'error': 'Conversation not found'}
        name = (name or '').strip()
        if not name:
            return {'error': 'Name cannot be empty'}
        conv.write({'name': name})
        return {'id': conv.id, 'name': conv.name}

    @http.route('/gsus_ai/chat/delete_conversation', type='json', auth='user')
    def delete_conversation(self, conversation_id: int):
        """Delete a conversation, all its messages, and any action proposals."""
        env = request.env
        conv = env['gsus.ai.conversation'].browse(conversation_id)
        if not conv.exists():
            return {'error': 'Conversation not found'}
        if conv.user_id.id != env.user.id and not env.user.has_group('base.group_system'):
            return {'error': 'Unauthorized to delete this conversation'}

        proposals = env['gsus.ai.action.proposal'].search([('conversation_id', '=', conv.id)])
        proposals.unlink()
        conv.message_ids.unlink()
        conv.unlink()
        return {'status': 'success', 'deleted_id': conversation_id}

    @http.route('/gsus_ai/chat/toggle_pin', type='json', auth='user')
    def toggle_pin(self, conversation_id: int):
        """Toggle pinned status of a conversation."""
        env = request.env
        conv = env['gsus.ai.conversation'].browse(conversation_id)
        if not conv.exists():
            return {'error': 'Conversation not found'}
        conv.is_pinned = not conv.is_pinned
        return {'id': conv.id, 'is_pinned': conv.is_pinned}

    @http.route('/gsus_ai/chat/toggle_archive', type='json', auth='user')
    def toggle_archive(self, conversation_id: int):
        """Toggle archived status of a conversation."""
        env = request.env
        conv = env['gsus.ai.conversation'].browse(conversation_id)
        if not conv.exists():
            return {'error': 'Conversation not found'}
        conv.is_archived = not conv.is_archived
        return {'id': conv.id, 'is_archived': conv.is_archived}

    @http.route('/gsus_ai/chat/get_share_transcript', type='json', auth='user')
    def get_share_transcript(self, conversation_id: int):
        """Generate a clean shareable transcript for the conversation."""
        env = request.env
        conv = env['gsus.ai.conversation'].browse(conversation_id)
        if not conv.exists():
            return {'error': 'Conversation not found'}
        lines = [f"# {conv.name}\n"]
        for m in conv.message_ids.sorted('id'):
            speaker = "User" if m.role == 'user' else "AI Assistant"
            lines.append(f"### {speaker}:\n{m.content}\n")
        return {
            'id': conv.id,
            'title': conv.name,
            'transcript': "\n".join(lines).strip(),
        }