/** @odoo-module **/

import { Component, proxy, onWillStart, onMounted, onPatched, onWillUnmount, useProps, markup } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { rpc } from "@web/core/network/rpc";
import { cookie } from "@web/core/browser/cookie";
import { markdownToHtml } from "../../utils/markdown";

export class GsusAiChatPanel extends Component {
    static template = "gsus_ai.ChatPanel";
    props = useProps();

    renderMarkdown(content) {
        if (!content) return "";
        try {
            return markup(markdownToHtml(content, this._mediaPreviewMap));
        } catch (e) {
            console.error("Markdown render error:", e);
            return content;
        }
    }

    setup() {
        this.rpc = rpc;
        this.notification = useService("notification");
        this.action = useService("action");
        this._mediaPreviewMap = new Map();

        this.drafts = {};
        try {
            const savedDrafts = sessionStorage.getItem("gsus_ai_drafts");
            if (savedDrafts) {
                this.drafts = JSON.parse(savedDrafts) || {};
            }
        } catch (e) {
            this.drafts = {};
        }

        const isFloating = Boolean(this.props?.isFloating);

        this.state = proxy({
            isLoading: true,
            isSending: false,
            providers: [],
            agents: [],
            conversations: [],
            activeConversation: null,
            messages: [],
            pendingProposals: [],
            processingProposalId: null,
            processingProposalAction: null,
            inputMessage: "",
            searchQuery: "",
            showSidebar: !isFloating,
            attachedFile: null,
            showModelDropdown: false,
            isRenamingChat: false,
            renameValue: "",
            editingMessageId: null,
            editingText: "",
            isDraggingFile: false,
            activeMenuConvId: null,
            inlineRenamingConvId: null,
            inlineRenamingValue: "",
            isRecentsCollapsed: false,
            showSearchModal: false,
            modalSearchQuery: "",
            showRenameModal: false,
            modalRenameValue: "",
            modalRenameConvId: null,
            showHeaderMenu: false,
            showVisionInspector: false,
            visionImageUrl: "",
            visionImageName: "",
            visionZoom: 100,
            visionRotation: 0,
        });

        this._docClickHandler = (e) => {
            if (!e.target.closest(".o_gsus_ai_model_pill_wrapper") && !e.target.closest(".o_gsus_ai_model_dropdown_wrapper")) {
                this.state.showModelDropdown = false;
            }
            if (!e.target.closest(".o_gsus_ai_item_menu_wrapper") && !e.target.closest(".o_gsus_ai_item_menu_btn")) {
                this.state.activeMenuConvId = null;
            }
            if (!e.target.closest(".o_gsus_ai_header_right")) {
                this.state.showHeaderMenu = false;
            }
        };

        this._recordClickHandler = (e) => {
            const actionLink = e.target.closest(".o_gsus_ai_action_link");
            if (actionLink) {
                e.preventDefault();
                e.stopPropagation();
                const actionId = actionLink.dataset.odooAction;
                if (actionId) {
                    this.action.doAction(actionId);
                }
                return;
            }
            const link = e.target.closest(".o_gsus_ai_record_link");
            if (link) {
                e.preventDefault();
                e.stopPropagation();
                const model = link.dataset.odooModel;
                const id = parseInt(link.dataset.odooId, 10);
                if (model && id) {
                    this.openOdooRecord(model, id);
                }
            }
        };

        this._resumePrevHandler = async () => {
            await this.resumePreviousConversation();
        };

        this._toggleSidebarHandler = () => {
            this.toggleSidebar();
        };

        this._keydownHandler = (e) => {
            if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
                e.preventDefault();
                if (this.state.showSearchModal) {
                    this.closeSearchModal();
                } else {
                    this.openSearchModal();
                }
            } else if (e.key === "Escape") {
                if (this.state.showRenameModal) {
                    e.preventDefault();
                    this.closeRenameModal();
                } else if (this.state.showSearchModal) {
                    e.preventDefault();
                    this.closeSearchModal();
                }
            }
        };

        onWillStart(async () => {
            await this.loadInitialData();
        });

        onMounted(() => {
            this.scrollToBottom();
            document.addEventListener("click", this._docClickHandler);
            document.addEventListener("click", this._recordClickHandler);
            document.addEventListener("keydown", this._keydownHandler);
            document.addEventListener("o-gsus-ai-resume-prev", this._resumePrevHandler);
            document.addEventListener("o-gsus-ai-toggle-sidebar", this._toggleSidebarHandler);
        });

        onPatched(() => {
            this.scrollToBottom();
        });

        onWillUnmount(() => {
            document.removeEventListener("click", this._docClickHandler);
            document.removeEventListener("click", this._recordClickHandler);
            document.removeEventListener("keydown", this._keydownHandler);
            document.removeEventListener("o-gsus-ai-resume-prev", this._resumePrevHandler);
            document.removeEventListener("o-gsus-ai-toggle-sidebar", this._toggleSidebarHandler);
        });
    }

    async loadInitialData() {
        try {
            const data = await this.rpc("/gsus_ai/chat/init", {});
            this.state.providers = data.providers || [];
            this.state.agents = data.agents || [];
            this.state.conversations = data.conversations || [];

            if (this.state.conversations.length > 0) {
                await this.selectConversation(this.state.conversations[0].id);
            } else {
                await this.createNewConversation();
            }
        } catch (error) {
            this.notification.add("Failed to initialize GSUS AI: " + (error.message || error), { type: "danger" });
        } finally {
            this.state.isLoading = false;
        }
    }

    get isFloating() {
        return Boolean(this.props?.isFloating);
    }

    get isDarkMode() {
        return cookie.get("color_scheme") === "dark" || document.documentElement.dataset.bsTheme === "dark" || document.body.classList.contains("o_dark_mode");
    }

    toggleSidebar() {
        this.state.showSidebar = !this.state.showSidebar;
    }

    get allProviderModels() {
        const providers = this.state.providers || [];
        const active = providers.filter((p) => p.is_active !== false);
        const working = active.filter((p) => p.state === "connected" || p.state === "draft");
        const list = working.length > 0 ? working : (active.length > 0 ? active : providers);
        return list.map((p) => ({
            provider_id: p.id,
            provider_name: p.name,
            model_name: p.model_name,
            state: p.state,
            label: (p.name || "") + " - " + (p.model_name || ""),
        }));
    }

    get activeModelLabel() {
        const c = this.state.activeConversation;
        if (!c) return "Select model";
        return (c.provider_name || "AI") + " - " + (c.model_name || "");
    }

    toggleModelDropdown(ev) {
        ev.stopPropagation();
        this.state.showModelDropdown = !this.state.showModelDropdown;
    }

    async selectModel(option) {
        this.state.showModelDropdown = false;
        if (!this.state.activeConversation) return;
        try {
            const result = await this.rpc("/gsus_ai/chat/switch_model", {
                conversation_id: this.state.activeConversation.id,
                provider_id: option.provider_id,
                model_name: option.model_name,
            });
            if (result && !result.error) {
                this.state.activeConversation = Object.assign({}, this.state.activeConversation, result);
                this.notification.add("Switched to " + option.label, { type: "success" });
            }
        } catch (e) {
            this.notification.add("Model switch failed: " + (e.message || e), { type: "danger" });
        }
    }

    startRename() {
        if (!this.state.activeConversation) return;
        this.state.renameValue = this.state.activeConversation.name || "";
        this.state.isRenamingChat = true;
        setTimeout(() => {
            const input = document.querySelector(".o_gsus_ai_rename_input");
            if (input) { input.focus(); input.select(); }
        }, 50);
    }

    async commitRename() {
        const newName = (this.state.renameValue || "").trim();
        this.state.isRenamingChat = false;
        if (!newName || !this.state.activeConversation) return;
        try {
            await this.rpc("/gsus_ai/chat/rename", {
                conversation_id: this.state.activeConversation.id,
                name: newName,
            });
            this.state.activeConversation = Object.assign({}, this.state.activeConversation, { name: newName });
            const item = this.state.conversations.find((c) => c.id === this.state.activeConversation.id);
            if (item) item.name = newName;
            this.notification.add("Chat renamed.", { type: "success" });
        } catch (e) {
            this.notification.add("Rename failed: " + (e.message || e), { type: "danger" });
        }
    }

    onRenameKeydown(ev) {
        if (ev.key === "Enter") { ev.preventDefault(); this.commitRename(); }
        if (ev.key === "Escape") { this.state.isRenamingChat = false; }
    }

    startEditingMessage(msg) {
        let content = msg.content || "";
        const lines = content.split("\n");
        if (lines.length > 2 && (lines[0].startsWith("📎") || lines[0].startsWith("![") || lines[0].startsWith("🖼️"))) {
            content = lines.slice(2).join("\n");
        }
        this.state.editingMessageId = msg.id;
        this.state.editingText = content;
        setTimeout(() => {
            const ta = document.querySelector(".o_gsus_ai_edit_textarea");
            if (ta) {
                ta.focus();
                ta.setSelectionRange(ta.value.length, ta.value.length);
            }
        }, 50);
    }

    cancelEditing() {
        this.state.editingMessageId = null;
        this.state.editingText = "";
    }

    onEditingInput(ev) {
        this.state.editingText = ev.target.value;
    }

    onEditingKeydown(ev, msg) {
        if (ev.key === "Enter" && !ev.shiftKey) {
            ev.preventDefault();
            this.submitEditedMessage(msg);
        } else if (ev.key === "Escape") {
            ev.preventDefault();
            this.cancelEditing();
        }
    }

    async submitEditedMessage(msg) {
        const newText = (this.state.editingText || "").trim();
        if (!newText || this.state.isSending) return;

        const messageId = msg.id;
        this.cancelEditing();
        this.state.isSending = true;

        try {
            const data = await this.rpc("/gsus_ai/chat/edit_message", {
                conversation_id: this.state.activeConversation.id,
                message_id: messageId,
                new_content: newText,
            });

            if (data && data.messages) {
                this.state.activeConversation = data;
                this.state.messages = data.messages;
                this.state.pendingProposals = data.pending_proposals || [];

                // Sync sidebar item title and messages count
                const item = this.state.conversations.find((c) => c.id === data.id);
                if (item) {
                    item.name = data.name;
                    item.total_messages_count = data.messages.length;
                }
            }
        } catch (e) {
            this.notification.add("Failed to edit message: " + (e.message || e), { type: "danger" });
        } finally {
            this.state.isSending = false;
            this.scrollToBottom();
        }
    }

    openOdooRecord(model, recordId) {
        if (!model || !recordId) return;
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: model,
            res_id: parseInt(recordId, 10),
            views: [[false, "form"]],
            target: "current",
        });
    }

    async resumePreviousConversation() {
        if (this.state.conversations && this.state.conversations.length > 0) {
            const currentId = this.state.activeConversation?.id;
            const prev = this.state.conversations.find((c) => c.id !== currentId) || this.state.conversations[0];
            if (prev) {
                await this.selectConversation(prev.id);
            }
        }
    }

    async sendQuickPrompt(promptText) {
        if (!promptText || this.state.isSending) return;
        this.state.inputMessage = promptText;
        setTimeout(() => this.autoResizeTextarea(), 0);
        await this.sendMessage();
    }

    saveCurrentDraft() {
        const convId = this.state.activeConversation?.id;
        if (!convId) return;
        const text = this.state.inputMessage || "";
        const file = this.state.attachedFile || null;
        if (text.trim() || file) {
            this.drafts[convId] = { text, file };
        } else {
            delete this.drafts[convId];
        }
        this._persistDrafts();
    }

    restoreDraft(conversationId) {
        const draft = this.drafts[conversationId];
        if (draft) {
            this.state.inputMessage = draft.text || "";
            this.state.attachedFile = draft.file || null;
        } else {
            this.state.inputMessage = "";
            this.state.attachedFile = null;
        }
        setTimeout(() => this.autoResizeTextarea(), 0);
    }

    _persistDrafts() {
        try {
            const toStore = {};
            for (const [k, v] of Object.entries(this.drafts)) {
                if (v && v.text) {
                    toStore[k] = { text: v.text };
                }
            }
            sessionStorage.setItem("gsus_ai_drafts", JSON.stringify(toStore));
        } catch (e) {
            // Ignore quota errors
        }
    }

    async selectConversation(conversationId) {
        if (this.isFloating) {
            this.state.showSidebar = false;
        }
        if (this.state.activeConversation?.id && this.state.activeConversation.id !== conversationId) {
            this.saveCurrentDraft();
        }
        this.state.isLoading = true;
        try {
            const data = await this.rpc("/gsus_ai/chat/load_conversation", {
                conversation_id: conversationId,
            });
            if (data.error) {
                this.notification.add(data.error, { type: "warning" });
            } else {
                this.state.activeConversation = data;
                this.state.messages = data.messages || [];
                this.state.pendingProposals = data.pending_proposals || [];
                this.restoreDraft(conversationId);
            }
        } catch (error) {
            this.notification.add("Error loading conversation: " + (error.message || error), { type: "danger" });
        } finally {
            this.state.isLoading = false;
        }
    }

    async createNewConversation(agentId = null) {
        if (this.isFloating) {
            this.state.showSidebar = false;
        }
        this.saveCurrentDraft();
        this.state.inputMessage = "";
        this.state.attachedFile = null;
        this.state.isLoading = true;
        try {
            const newConv = await this.rpc("/gsus_ai/chat/create_conversation", {
                agent_id: agentId,
            });
            if (newConv.error) {
                this.notification.add(newConv.error, { type: "danger" });
            } else {
                this.state.conversations.unshift({
                    id: newConv.id,
                    name: newConv.name,
                    model_name: newConv.model_name,
                    total_messages_count: 0,
                    is_pinned: false,
                });
                await this.selectConversation(newConv.id);
            }
        } catch (error) {
            this.notification.add("Failed to start new chat: " + (error.message || error), { type: "danger" });
        } finally {
            this.state.isLoading = false;
        }
    }

    triggerFileInput() {
        const input = document.querySelector(".o_gsus_ai_file_input");
        if (input) {
            input.click();
        }
    }

    onDragOver(ev) {
        ev.preventDefault();
        if (!this.state.isDraggingFile) {
            this.state.isDraggingFile = true;
        }
    }

    onDragLeave(ev) {
        ev.preventDefault();
        if (ev.currentTarget && !ev.currentTarget.contains(ev.relatedTarget)) {
            this.state.isDraggingFile = false;
        }
    }

    onDrop(ev) {
        ev.preventDefault();
        this.state.isDraggingFile = false;
        const files = ev.dataTransfer?.files;
        if (files && files.length > 0) {
            this.processFile(files[0]);
        }
    }

    onFileSelected(event) {
        const file = event.target?.files?.[0];
        if (!file) return;
        this.processFile(file);
        event.target.value = "";
    }

    processFile(file) {
        if (!file) return;

        // Size limit: 10MB
        if (file.size > 10 * 1024 * 1024) {
            this.notification.add("File is too large (max 10MB)", { type: "warning" });
            return;
        }

        const isImage = file.type && file.type.startsWith("image/");
        const isTextFile = /\.(csv|txt|json|log|xml|md|py|js|html|yml|yaml|sql)$/i.test(file.name) || (file.type && file.type.startsWith("text/"));

        const reader = new FileReader();
        if (isImage) {
            reader.onload = (e) => {
                const dataUrl = e.target.result;
                const base64Data = (dataUrl || "").split(",")[1] || dataUrl;
                this._mediaPreviewMap.set(file.name, dataUrl);
                this.state.attachedFile = {
                    name: file.name,
                    size: file.size,
                    type: file.type || "image/png",
                    previewUrl: dataUrl,
                    content: base64Data,
                    is_image: true,
                    is_text: false,
                };
                this.notification.add(`Image "${file.name}" attached.`, { type: "info" });
            };
            reader.readAsDataURL(file);
        } else if (isTextFile) {
            reader.onload = (e) => {
                this.state.attachedFile = {
                    name: file.name,
                    size: file.size,
                    type: file.type || "text/plain",
                    content: e.target.result,
                    is_image: false,
                    is_text: true,
                };
                this.notification.add(`File "${file.name}" attached.`, { type: "info" });
            };
            reader.readAsText(file);
        } else {
            reader.onload = (e) => {
                const dataUrl = e.target.result;
                const base64Data = (dataUrl || "").split(",")[1] || dataUrl;
                this.state.attachedFile = {
                    name: file.name,
                    size: file.size,
                    type: file.type || "application/octet-stream",
                    content: base64Data,
                    is_image: false,
                    is_text: false,
                };
                this.notification.add(`File "${file.name}" attached.`, { type: "info" });
            };
            reader.readAsDataURL(file);
        }
    }

    removeAttachedFile() {
        this.state.attachedFile = null;
    }

    formatFileSize(bytes) {
        if (!bytes) return "0 B";
        const k = 1024;
        const sizes = ["B", "KB", "MB"];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + " " + sizes[i];
    }

    getFileIcon(filename) {
        if (!filename) return "description";
        const ext = filename.split(".").pop().toLowerCase();
        if (["csv", "xlsx", "xls"].includes(ext)) return "table_chart";
        if (["pdf"].includes(ext)) return "picture_as_pdf";
        if (["json", "js", "py", "xml", "html", "sql"].includes(ext)) return "code";
        if (["zip", "tar", "gz", "rar", "7z"].includes(ext)) return "folder_zip";
        return "description";
    }

    async sendMessage() {
        const text = (this.state.inputMessage || "").trim();
        const file = this.state.attachedFile;
        if ((!text && !file) || this.state.isSending || !this.state.activeConversation) {
            return;
        }

        // Clear active conversation draft upon sending
        if (this.state.activeConversation?.id) {
            delete this.drafts[this.state.activeConversation.id];
            this._persistDrafts();
        }

        this.state.isSending = true;
        this.state.inputMessage = "";
        this.state.attachedFile = null;
        this.autoResizeTextarea();

        // Optimistically add user message with attached file badge/preview if present
        let optimisticContent = text;
        if (file) {
            if (file.is_image && file.previewUrl) {
                this._mediaPreviewMap.set(file.name, file.previewUrl);
                optimisticContent = text 
                    ? `![${file.name}](${file.previewUrl})\n\n${text}`
                    : `![${file.name}](${file.previewUrl})`;
            } else {
                optimisticContent = text
                    ? `📎 **Attached File:** \`${file.name}\` (${this.formatFileSize(file.size)})\n\n${text}`
                    : `📎 **Attached File:** \`${file.name}\` (${this.formatFileSize(file.size)})`;
            }
        }

        this.state.messages.push({
            id: Date.now(),
            role: "user",
            content: optimisticContent,
            create_date: "Just now",
        });
        this.scrollToBottom();

        try {
            const result = await this.rpc("/gsus_ai/chat/send", {
                conversation_id: this.state.activeConversation.id,
                message: text,
                file_data: file,
            });

            if (result.error) {
                this.notification.add(result.error, { type: "danger" });
            } else {
                this.state.activeConversation = result;
                this.state.messages = result.messages || [];
                this.state.pendingProposals = result.pending_proposals || [];

                // Update title in sidebar
                const item = this.state.conversations.find((c) => c.id === result.id);
                if (item) {
                    item.name = result.name;
                    item.total_messages_count = this.state.messages.length;
                }
            }
        } catch (error) {
            this.notification.add("Send failed: " + (error.message || error), { type: "danger" });
        } finally {
            this.state.isSending = false;
            this.scrollToBottom();
        }
    }

    async deleteConversation(convId, ev) {
        if (ev) {
            ev.stopPropagation();
            ev.preventDefault();
        }
        if (!confirm("Are you sure you want to delete this chat?")) {
            return;
        }
        if (convId && this.drafts[convId]) {
            delete this.drafts[convId];
            this._persistDrafts();
        }
        try {
            const res = await this.rpc("/gsus_ai/chat/delete_conversation", {
                conversation_id: convId,
            });
            if (res.error) {
                this.notification.add(res.error, { type: "danger" });
                return;
            }
            this.state.conversations = this.state.conversations.filter((c) => c.id !== convId);
            this.notification.add("Chat deleted.", { type: "info" });

            if (this.state.activeConversation?.id === convId) {
                if (this.state.conversations.length > 0) {
                    await this.selectConversation(this.state.conversations[0].id);
                } else {
                    await this.createNewConversation();
                }
            }
        } catch (e) {
            this.notification.add("Failed to delete chat: " + (e.message || e), { type: "danger" });
        }
    }

    getProposalDetails(prop) {
        if (!prop || !prop.arguments_json) {
            return { title: prop?.summary || "Confirmation Required", entries: [] };
        }
        try {
            const parsed = typeof prop.arguments_json === "string" ? JSON.parse(prop.arguments_json) : prop.arguments_json;
            const entries = [];
            let title = prop.summary || "Confirm Action";

            // Clean up prefix
            if (title.toLowerCase().startsWith("proposed action: ")) {
                title = title.substring(17).trim();
            }

            // Simplify title from technical strings like "Universal Record Creator"
            if (title.toLowerCase().includes("universal record creator")) {
                const modelName = (parsed.model || "").replace(/^.*\./, "");
                const prettyModel = modelName ? (modelName.charAt(0).toUpperCase() + modelName.slice(1)) : "Record";
                const recName = parsed.values?.name || "";
                title = recName && recName !== "New" && recName !== "/" ? `Create ${prettyModel}: ${recName}` : `Create New ${prettyModel}`;
            }

            // Universal Record Updater: turn generic title into clear business action
            if (title.toLowerCase().includes("universal record updater") || title.toLowerCase() === "orm_write_record") {
                const model = parsed.model || "";
                const stateVal = parsed.values?.state;
                if (model === "purchase.order") {
                    if (stateVal === "purchase") title = "Confirm Purchase Order";
                    else if (stateVal === "cancel") title = "Cancel Purchase Order";
                    else if (stateVal === "draft") title = "Reset Purchase Order to Draft";
                    else title = "Update Purchase Order";
                } else if (model === "sale.order") {
                    if (stateVal === "sale") title = "Confirm Sales Order";
                    else if (stateVal === "cancel") title = "Cancel Sales Order";
                    else if (stateVal === "draft") title = "Reset Sales Order to Draft";
                    else title = "Update Sales Order";
                } else if (model === "account.move") {
                    if (stateVal === "posted") title = "Post Journal Entry / Invoice";
                    else if (stateVal === "cancel") title = "Cancel Journal Entry";
                    else title = "Update Invoice / Journal Entry";
                } else if (model === "stock.picking") {
                    if (stateVal === "done") title = "Validate Stock Transfer";
                    else if (stateVal === "cancel") title = "Cancel Stock Transfer";
                    else title = "Update Stock Transfer";
                } else {
                    const modelName = model.replace(/^.*\./, "");
                    const prettyModel = modelName ? (modelName.charAt(0).toUpperCase() + modelName.slice(1)) : "Record";
                    title = `Update ${prettyModel}`;
                }
            }

            // Universal Record Deleter: turn generic title into clear business deletion action
            if (title.toLowerCase().includes("universal record deleter") || title.toLowerCase() === "orm_unlink_record") {
                const model = parsed.model || "";
                const MODEL_LABELS = {
                    "purchase.order": "Purchase Order",
                    "sale.order": "Sales Order",
                    "account.move": "Invoice / Bill",
                    "stock.picking": "Stock Transfer",
                    "mrp.production": "Manufacturing Order",
                    "mrp.bom": "Bill of Materials",
                    "crm.lead": "CRM Lead",
                    "res.partner": "Contact",
                    "product.template": "Product",
                };
                const modelLabel = MODEL_LABELS[model] || model.replace(/^.*\./, "").replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()) || "Record";
                const recId = parsed.id ? `#${parsed.id}` : "";
                title = `Delete ${modelLabel} ${recId}`.trim();
            }

            // Res.config.settings special handling: clean setting names and status
            if (parsed.model === "res.config.settings") {
                title = "Update System Configuration";
                const values = parsed.values || {};
                const SETTING_LABELS = {
                    group_stock_multi_locations: "Storage Locations",
                    group_stock_adv_location: "Multi-Step Routes",
                    group_stock_tracking_lot: "Packages",
                    group_stock_tracking_owner: "Consignment",
                    group_uom: "Units of Measure",
                    group_product_variant: "Product Variants",
                    group_stock_picking_batch: "Batch & Wave Transfers",
                    group_stock_production_lot: "Lots & Serial Numbers",
                };
                for (const [k, v] of Object.entries(values)) {
                    const label = SETTING_LABELS[k] || k.replace(/^group_/, "").replace(/^stock_/, "").replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
                    const valStr = typeof v === "boolean" ? (v ? "Enable" : "Disable") : String(v);
                    entries.push({ key: label, value: valStr });
                }
                return { title, entries };
            }

            // State dictionary for human-friendly labels
            const STATE_LABELS = {
                purchase: "Confirmed (Purchase Order)",
                draft: "Draft (RFQ)",
                sale: "Confirmed (Sales Order)",
                cancel: "Cancelled",
                posted: "Posted",
                done: "Done",
                to_approve: "Waiting Approval",
            };

            // If deleting an existing record, show clear context and safeguard notes
            if (title.toLowerCase().includes("delete")) {
                const model = parsed.model || "";
                const modelName = model.replace(/^.*\./, "").replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
                if (parsed.id) {
                    entries.push({ key: "Target Record", value: `${modelName} #${parsed.id}` });
                }
                entries.push({ key: "Operation", value: "Permanent Deletion" });
                entries.push({ key: "Safety Workflow", value: "Automatically cancels record before deletion" });
                return { title, entries };
            }

            // If updating an existing record, show record identifier first
            if (parsed.model && parsed.id) {
                const modelName = (parsed.model || "").replace(/^.*\./, "").replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
                entries.push({ key: "Target Record", value: `${modelName} #${parsed.id}` });
            }

            // Clean, friendly business entries (excluding technical internal fields)
            const excludedKeys = new Set(["active", "model", "id", "sequence"]);
            if (parsed.values && typeof parsed.values === "object") {
                for (const [k, v] of Object.entries(parsed.values)) {
                    if (excludedKeys.has(k)) continue;
                    if ((k === "sale_ok" || k === "purchase_ok") && typeof v === "boolean") continue;
                    // Never show generic 'New' name in proposal entries
                    if (k === "name" && (v === "New" || v === "/" || !v)) continue;
                    const label = k.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
                    let valStr = "";
                    if (k === "state" && STATE_LABELS[v]) {
                        valStr = STATE_LABELS[v];
                    } else if (typeof v === "boolean") {
                        valStr = v ? "Yes" : "No";
                    } else if (v === null || v === undefined) {
                        continue;
                    } else {
                        valStr = String(v);
                    }
                    entries.push({ key: label, value: valStr });
                }
            } else if (parsed.lines && Array.isArray(parsed.lines)) {
                if (parsed.partner_name) {
                    entries.push({ key: "Partner / Vendor", value: parsed.partner_name });
                }
                for (const line of parsed.lines) {
                    const name = line.product_name || `Product #${line.product_id || ""}`;
                    entries.push({ key: name, value: `${line.quantity || 1} ${line.uom_name || "Units"}` });
                }
            } else {
                for (const [k, v] of Object.entries(parsed)) {
                    if (excludedKeys.has(k)) continue;
                    if (k === "name" && (v === "New" || v === "/" || !v)) continue;
                    if (typeof v !== "object") {
                        const label = k.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
                        let valStr = String(v);
                        if (k === "state" && STATE_LABELS[v]) {
                            valStr = STATE_LABELS[v];
                        }
                        entries.push({ key: label, value: valStr });
                    }
                }
            }
            return {
                title,
                entries,
            };
        } catch (e) {
            return { title: prop.summary || "Confirm Action", entries: [] };
        }
    }

    async handleProposal(proposalId, action) {
        if (this.state.processingProposalId) {
            return;
        }
        this.state.processingProposalId = proposalId;
        this.state.processingProposalAction = action;
        try {
            const result = await this.rpc("/gsus_ai/chat/proposal_action", {
                proposal_id: proposalId,
                action: action,
            });
            if (result.error) {
                this.notification.add(result.error, { type: "danger" });
            } else {
                this.state.activeConversation = result;
                this.state.messages = result.messages || [];
                this.state.pendingProposals = result.pending_proposals || [];
                const actionText = action === "confirm" ? "executed successfully" : "rejected";
                this.notification.add(`Proposal ${actionText}.`, { type: "info" });

                // If an app/module was installed or modified, reload menu to update navbar icons
                if (this.env.services.menu && this.env.services.menu.reload) {
                    try {
                        await this.env.services.menu.reload();
                    } catch (e) {
                        console.warn("Failed to reload menu:", e);
                    }
                }
            }
        } catch (error) {
            this.notification.add("Action failed: " + (error.message || error), { type: "danger" });
        } finally {
            this.state.processingProposalId = null;
            this.state.processingProposalAction = null;
        }
    }

    copyToClipboard(text) {
        if (navigator.clipboard) {
            navigator.clipboard.writeText(text);
            this.notification.add("Copied to clipboard!", { type: "success" });
        }
    }

    onComposerInput(ev) {
        if (ev && ev.target) {
            this.state.inputMessage = ev.target.value;
            this.autoResizeTextarea(ev.target);
        }
    }

    autoResizeTextarea(textareaEl) {
        const el = textareaEl || document.querySelector(".o_gsus_ai_textarea");
        if (!el) return;
        el.style.height = "auto";
        const maxHeight = 200;
        const newHeight = Math.min(el.scrollHeight, maxHeight);
        el.style.height = `${newHeight}px`;
        if (el.scrollHeight > maxHeight) {
            el.style.overflowY = "auto";
        } else {
            el.style.overflowY = "hidden";
        }
    }

    onKeydown(event) {
        if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            if (event.target && event.target.value !== undefined) {
                this.state.inputMessage = event.target.value;
            }
            this.sendMessage();
            this.autoResizeTextarea(event.target);
        }
    }

    scrollToBottom() {
        setTimeout(() => {
            const area = document.querySelector(".o_gsus_ai_messages_area");
            if (area) {
                area.scrollTop = area.scrollHeight;
            }
        }, 50);
    }

    get filteredConversations() {
        const query = (this.state.searchQuery || "").toLowerCase().trim();
        if (!query) {
            return this.state.conversations;
        }
        return this.state.conversations.filter((c) => (c.name || "").toLowerCase().includes(query));
    }

    get pinnedConversations() {
        return this.filteredConversations.filter((c) => c.is_pinned && !c.is_archived);
    }

    get recentConversations() {
        return this.filteredConversations.filter((c) => !c.is_pinned && !c.is_archived);
    }

    openSearchModal() {
        this.state.showSearchModal = true;
        this.state.modalSearchQuery = "";
        setTimeout(() => {
            const inputEl = document.querySelector(".o_gsus_ai_search_input");
            if (inputEl) {
                inputEl.focus();
            }
        }, 50);
    }

    closeSearchModal() {
        this.state.showSearchModal = false;
        this.state.modalSearchQuery = "";
    }

    clearModalSearch() {
        this.state.modalSearchQuery = "";
        const inputEl = document.querySelector(".o_gsus_ai_search_input");
        if (inputEl) {
            inputEl.focus();
        }
    }

    async selectModalConversation(convId) {
        this.closeSearchModal();
        await this.selectConversation(convId);
    }

    onSearchModalKeydown(ev) {
        if (ev.key === "Escape") {
            ev.preventDefault();
            this.closeSearchModal();
        } else if (ev.key === "Enter") {
            const filtered = this.modalFilteredConversations;
            if (filtered.length > 0) {
                ev.preventDefault();
                this.selectModalConversation(filtered[0].id);
            }
        }
    }

    get modalFilteredConversations() {
        const query = (this.state.modalSearchQuery || "").toLowerCase().trim();
        const activeConvs = this.state.conversations.filter((c) => !c.is_archived);
        if (!query) {
            return activeConvs.slice(0, 15);
        }
        return activeConvs.filter((c) => (c.name || "").toLowerCase().includes(query)).slice(0, 20);
    }

    toggleRecentsCollapse() {
        this.state.isRecentsCollapsed = !this.state.isRecentsCollapsed;
    }

    toggleItemMenu(convId, ev) {
        if (ev) {
            ev.stopPropagation();
            ev.preventDefault();
        }
        if (this.state.activeMenuConvId === convId) {
            this.state.activeMenuConvId = null;
        } else {
            this.state.activeMenuConvId = convId;
        }
    }

    closeItemMenu() {
        this.state.activeMenuConvId = null;
    }

    async togglePin(convId, ev) {
        if (ev) {
            ev.stopPropagation();
            ev.preventDefault();
        }
        this.closeItemMenu();
        try {
            const res = await this.rpc("/gsus_ai/chat/toggle_pin", { conversation_id: convId });
            if (res && !res.error) {
                const item = this.state.conversations.find((c) => c.id === convId);
                if (item) item.is_pinned = res.is_pinned;
                if (this.state.activeConversation?.id === convId) {
                    this.state.activeConversation = Object.assign({}, this.state.activeConversation, { is_pinned: res.is_pinned });
                }
                this.notification.add(res.is_pinned ? "Chat pinned" : "Chat unpinned", { type: "info" });
            }
        } catch (e) {
            this.notification.add("Failed to pin chat: " + (e.message || e), { type: "danger" });
        }
    }

    async toggleArchive(convId, ev) {
        if (ev) {
            ev.stopPropagation();
            ev.preventDefault();
        }
        this.closeItemMenu();
        try {
            const res = await this.rpc("/gsus_ai/chat/toggle_archive", { conversation_id: convId });
            if (res && !res.error) {
                const item = this.state.conversations.find((c) => c.id === convId);
                if (item) item.is_archived = res.is_archived;
                this.notification.add(res.is_archived ? "Chat archived" : "Chat unarchived", { type: "info" });
                if (this.state.activeConversation?.id === convId && res.is_archived) {
                    const remaining = this.recentConversations[0] || this.pinnedConversations[0];
                    if (remaining) {
                        await this.selectConversation(remaining.id);
                    } else {
                        await this.createNewConversation();
                    }
                }
            }
        } catch (e) {
            this.notification.add("Failed to archive chat: " + (e.message || e), { type: "danger" });
        }
    }

    openRenameModal(conv, ev) {
        if (ev) {
            ev.stopPropagation();
            ev.preventDefault();
        }
        this.closeItemMenu();
        this.state.showHeaderMenu = false;
        const targetConv = conv || this.state.activeConversation;
        if (!targetConv) return;
        this.state.modalRenameConvId = targetConv.id;
        this.state.modalRenameValue = targetConv.name || "";
        this.state.showRenameModal = true;
        setTimeout(() => {
            const input = document.querySelector(".o_gsus_ai_rename_modal_input");
            if (input) {
                input.focus();
                input.select();
            }
        }, 50);
    }

    closeRenameModal() {
        this.state.showRenameModal = false;
        this.state.modalRenameConvId = null;
        this.state.modalRenameValue = "";
    }

    onRenameModalKeydown(ev) {
        if (ev.key === "Enter") {
            ev.preventDefault();
            this.commitModalRename();
        } else if (ev.key === "Escape") {
            ev.preventDefault();
            this.closeRenameModal();
        }
    }

    async commitModalRename() {
        const convId = this.state.modalRenameConvId || (this.state.activeConversation ? this.state.activeConversation.id : null);
        const newName = (this.state.modalRenameValue || "").trim();
        this.closeRenameModal();
        if (!convId || !newName) return;

        try {
            await this.rpc("/gsus_ai/chat/rename", {
                conversation_id: convId,
                name: newName,
            });
            const item = this.state.conversations.find((c) => c.id === convId);
            if (item) item.name = newName;
            if (this.state.activeConversation?.id === convId) {
                this.state.activeConversation = Object.assign({}, this.state.activeConversation, { name: newName });
            }
            this.notification.add("Chat renamed successfully.", { type: "success" });
        } catch (e) {
            this.notification.add("Rename failed: " + (e.message || e), { type: "danger" });
        }
    }

    toggleHeaderMenu(ev) {
        if (ev) {
            ev.stopPropagation();
            ev.preventDefault();
        }
        this.state.showHeaderMenu = !this.state.showHeaderMenu;
    }

    async togglePinFromHeader(ev) {
        if (this.state.activeConversation) {
            this.state.showHeaderMenu = false;
            await this.togglePin(this.state.activeConversation.id, ev);
        }
    }

    async toggleArchiveFromHeader(ev) {
        if (this.state.activeConversation) {
            this.state.showHeaderMenu = false;
            await this.toggleArchive(this.state.activeConversation.id, ev);
        }
    }

    async deleteFromHeader(ev) {
        if (this.state.activeConversation) {
            this.state.showHeaderMenu = false;
            await this.deleteConversation(this.state.activeConversation.id, ev);
        }
    }

    startInlineRename(conv, ev) {
        if (ev) {
            ev.stopPropagation();
            ev.preventDefault();
        }
        this.closeItemMenu();
        this.state.inlineRenamingConvId = conv.id;
        this.state.inlineRenamingValue = conv.name || "";
        setTimeout(() => {
            const input = document.querySelector(`.o_gsus_ai_inline_rename_input[data-conv-id="${conv.id}"]`);
            if (input) {
                input.focus();
                input.select();
            }
        }, 50);
    }

    onInlineRenameKeydown(ev, convId) {
        if (ev.key === "Enter") {
            ev.preventDefault();
            this.commitInlineRename(convId);
        } else if (ev.key === "Escape") {
            ev.preventDefault();
            this.state.inlineRenamingConvId = null;
        }
    }

    async commitInlineRename(convId) {
        const newName = (this.state.inlineRenamingValue || "").trim();
        this.state.inlineRenamingConvId = null;
        if (!newName) return;

        try {
            await this.rpc("/gsus_ai/chat/rename", {
                conversation_id: convId,
                name: newName,
            });
            const item = this.state.conversations.find((c) => c.id === convId);
            if (item) item.name = newName;
            if (this.state.activeConversation?.id === convId) {
                this.state.activeConversation = Object.assign({}, this.state.activeConversation, { name: newName });
            }
            this.notification.add("Chat renamed.", { type: "success" });
        } catch (e) {
            this.notification.add("Rename failed: " + (e.message || e), { type: "danger" });
        }
    }

    async shareConversation(conv, ev) {
        if (ev) {
            ev.stopPropagation();
            ev.preventDefault();
        }
        this.closeItemMenu();
        try {
            const res = await this.rpc("/gsus_ai/chat/get_share_transcript", { conversation_id: conv.id });
            if (res && res.transcript) {
                await navigator.clipboard.writeText(res.transcript);
                this.notification.add("Conversation transcript copied to clipboard!", { type: "success" });
            }
        } catch (e) {
            this.notification.add("Share failed: " + (e.message || e), { type: "danger" });
        }
    }

    onMessagesAreaClick(ev) {
        // 1. Check for Media Card clicks (Image inspector)
        const mediaCard = ev.target.closest(".o_gsus_ai_media_card");
        if (mediaCard) {
            ev.preventDefault();
            ev.stopPropagation();
            const url = mediaCard.getAttribute("data-media-url") || mediaCard.querySelector("img")?.src;
            const name = mediaCard.getAttribute("data-media-name") || "Attached Image";
            if (url) {
                this.openVisionInspector(url, name);
            }
            return;
        }

        // 2. Check for Odoo Action link clicks
        const actionLink = ev.target.closest(".o_gsus_ai_action_link");
        if (actionLink) {
            ev.preventDefault();
            ev.stopPropagation();
            const actionXmlId = actionLink.getAttribute("data-odoo-action");
            if (actionXmlId && this.env.services.action) {
                this.env.services.action.doAction(actionXmlId);
            }
            return;
        }

        // 3. Check for Odoo Record link clicks
        const recordLink = ev.target.closest(".o_gsus_ai_record_link");
        if (recordLink) {
            ev.preventDefault();
            ev.stopPropagation();
            const model = recordLink.getAttribute("data-odoo-model");
            const id = parseInt(recordLink.getAttribute("data-odoo-id"), 10);
            if (model && id && this.env.services.action) {
                this.env.services.action.doAction({
                    type: "ir.actions.act_window",
                    res_model: model,
                    res_id: id,
                    views: [[false, "form"]],
                    target: "current",
                });
            }
            return;
        }
    }

    openVisionInspector(url, name) {
        this.state.visionImageUrl = url;
        this.state.visionImageName = name || "Image Preview";
        this.state.visionZoom = 100;
        this.state.visionRotation = 0;
        this.state.showVisionInspector = true;
    }

    closeVisionInspector() {
        this.state.showVisionInspector = false;
        this.state.visionImageUrl = "";
        this.state.visionImageName = "";
        this.state.visionZoom = 100;
        this.state.visionRotation = 0;
    }

    zoomInVision() {
        this.state.visionZoom = Math.min(400, this.state.visionZoom + 25);
    }

    zoomOutVision() {
        this.state.visionZoom = Math.max(25, this.state.visionZoom - 25);
    }

    resetVisionZoom() {
        this.state.visionZoom = 100;
        this.state.visionRotation = 0;
    }

    fitVisionZoom() {
        this.state.visionZoom = 80;
    }

    rotateVision() {
        this.state.visionRotation = (this.state.visionRotation + 90) % 360;
    }

    onVisionWheel(ev) {
        ev.preventDefault();
        if (ev.deltaY < 0) {
            this.zoomInVision();
        } else {
            this.zoomOutVision();
        }
    }

    downloadVisionImage() {
        if (!this.state.visionImageUrl) return;
        const a = document.createElement("a");
        a.href = this.state.visionImageUrl;
        a.download = this.state.visionImageName || "image.png";
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
    }

    async triggerVisionPrompt(promptText) {
        this.closeVisionInspector();
        await this.sendQuickPrompt(promptText);
    }
}

registry.category("actions").add("gsus_ai.chat_panel", GsusAiChatPanel);
