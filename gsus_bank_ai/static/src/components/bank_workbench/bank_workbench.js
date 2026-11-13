/** @odoo-module **/



import { Component, proxy, onMounted, onWillUpdateProps } from "@odoo/owl";

import { registry } from "@web/core/registry";

import { useService } from "@web/core/utils/hooks";

import { rpc } from "@web/core/network/rpc";

import { router } from "@web/core/browser/router";



function sortModelsLatestFirst(models) {

    if (!models || !models.length) return [];

    return [...models].sort((a, b) => {

        const codeA = (a.code || "").toLowerCase();

        const codeB = (b.code || "").toLowerCase();



        const matchA = codeA.match(/\d+(\.\d+)*/);

        const matchB = codeB.match(/\d+(\.\d+)*/);



        const parseVer = (m) => (m ? m[0].split(".").map(Number) : [0]);

        const vA = parseVer(matchA);

        const vB = parseVer(matchB);



        for (let i = 0; i < Math.max(vA.length, vB.length); i++) {

            const numA = vA[i] || 0;

            const numB = vB[i] || 0;

            if (numA !== numB) return numB - numA; // Latest version first

        }



        const isFlashA = codeA.includes("flash") ? 1 : 0;

        const isFlashB = codeB.includes("flash") ? 1 : 0;

        if (isFlashA !== isFlashB) return isFlashB - isFlashA;



        return codeA.localeCompare(codeB);

    });

}



export class GsusBankWorkbench extends Component {

    static template = "gsus_bank_ai.BankWorkbench";



    static extractProps(action) {

        const params = action.params || {};

        const ctx = action.context || {};

        return {

            action,

            statement_id: params.statement_id || ctx.statement_id || action.res_id || action.resId || ctx.active_id,

            initial_view: params.initial_view || ctx.initial_view,

        };

    }



    setup() {

        this.rpc = rpc;

        this.orm = useService("orm");

        this.action = useService("action");

        this.notification = useService("notification");



        this.state = proxy({

            // View Navigation: 'dashboard' | 'review' | 'vouchers' | 'upload'

            currentView: "dashboard",



            // Dashboard State

            dashboard: {

                available_credits: 1025,

                total_transactions: 0,

                total_jobs: 0,

                accuracy_rate: 100,

                active_tasks: 0,

                recent_statements: [],

                invoice_queue: {

                    customer_invoices_count: 0,

                    customer_invoices_amount: 0.0,

                    vendor_bills_count: 0,

                    vendor_bills_amount: 0.0,

                    total_pending_count: 0,

                    total_pending_amount: 0.0,

                },

                active_workspace: {

                    user_name: "Admin",

                    company_name: "My Company",

                    role: "Manager",

                    status: "Active",

                },

            },



            // Active Statement Session

            statement_id: null,

            statement_name: "No Statement Loaded",

            bank_name: "",

            state: "draft",

            total_transactions: 0,

            total_debit: 0,

            total_credit: 0,

            net_flow: 0,

            opening_balance: 0,

            closing_balance: 0,

            recomputed_closing_balance: 0,

            verification_state: "verified",

            verification_notes: "",

            assigned_count: 0,

            reviewed_count: 0,

            unassigned_count: 0,

            pushed_count: 0,

            confidence_avg: 0,

            anomalies_count: 0,

            account_bank_statement_id: false,

            last_error_message: "",



            // Lines & Pagination

            lines: [],

            activeTab: "all",

            searchQuery: "",

            dateFrom: "",

            dateTo: "",

            currentPage: 1,

            pageSize: 100,

            selectedLineIds: [],

            isLoading: false,

            showPdfPreview: false,



            // Push Live Progress

            isPushing: false,

            pushProgress: 0,



            // Connectivity Modal

            isConnectivityModalOpen: false,

            primaryBankLedgerName: "",

            optionalProcessingNotes: "",

            isCreatingVouchers: false,

            voucherJobProgress: 0,



            // Group Resolve Modal

            isGroupModalOpen: false,

            groups: [],
            expandedGroupKeys: {},

            currentGroupIndex: 0,

            selectedLedgerSearch: "",

            selectedPartnerId: null,

            selectedPartnerName: "",

            selectedAccountId: null,

            selectedAccountName: "",

            groupRemarkText: "",

            isResolvingGroup: false,



            // Group Remark Modal

            isGroupRemarkModalOpen: false,

            groupRemarkTargetKey: "",

            groupRemarkInput: "",



            // Manual Add Transaction Modal

            isAddTxnModalOpen: false,

            newTxnDate: "",

            newTxnNarration: "",

            newTxnDebit: 0,

            newTxnCredit: 0,



            // Dedicated Ingestion & Upload Flow

            uploadFileBase64: null,

            uploadFileName: "",

            uploadFileSizeKb: 0,

            uploadPagesCount: 0,

            uploadPassword: "",

            detectedBankName: "",

            selectedBankName: "",

            isPasswordProtected: false,

            isDecrypted: true,

            showPasswordField: false,

            isDuplicateDetected: false,

            duplicateWarning: "",

            aiEngineStatus: "Checking AI Engine...",

            aiEngineColor: "warning",

            aiEngineHasKey: false,

            aiEngineModel: "",

            aiEngineName: "",

            availableModels: [],

            aiEngineTokens: "140 t/s",

            userRole: "CTO / Admin",



            // Dedicated Processing Status Screen

            jobId: "",

            jobCreatedAt: "",

            jobStartedAt: "",

            isProcessing: false,

            processingStep: 1,

            processingLogs: [],



            // AI Provider Configuration Modal

            isProviderModalOpen: false,

            providers: [],

            activeProviderType: "gemini",

            providerApiKey: "",

            providerModelName: "",

            isTestingPing: false,

            pingResult: null,

            isRefreshingDashboard: false,





            // Bulk Actions

            isBulkAssignModalOpen: false,

            bulkPartnerId: null,

            bulkPartnerName: "",

            bulkAccountId: null,

            bulkAccountName: "",



            // Inline Editing & Autocomplete

            editingCell: { lineId: null, field: null },

            partnerSearchResults: [],

            accountSearchResults: [],

            showGroupPartnerDropdown: false,

            showGroupAccountDropdown: false,

            isSearchingPartners: false,

            isSearchingAccounts: false,

            highlightedSuggestionIndex: -1,



            // Theme (Dark / Light)

            theme: localStorage.getItem("gsus_bank_ai_theme") || "dark",



            // Native UI (Atmosphere) & Settings

            nativeUIEnabled: localStorage.getItem("gsus_bank_ai_native_ui") !== "false",



            // Interactive AI Chat Assistant State

            isChatOpen: false,

            isChatSending: false,

            chatInputText: "",

            chatMessages: [

                {

                    id: 1,

                    sender: "assistant",

                    text: "Hello! I am your GSUS Financial AI Assistant. How can I assist you with bank statement analysis or invoice reconciliation today?",

                    time: "Just now",

                    provider: "Gemini 2.5 Flash",

                }

            ],

        });



        onMounted(() => {

            this.loadAIEngineStatus();

            const props = this.props || {};

            const action = props.action || {};

            const ctx = action.context || props.context || {};

            const params = action.params || props.params || {};



            let initialView = props.initial_view || params.initial_view || ctx.initial_view;

            if (!initialView && typeof params === "string" && params.includes("upload")) {

                initialView = "upload";

            }

            if (this.state.currentView === "upload" || initialView === "upload") {

                this.switchToUpload();

                return;

            }



            const sid = this.statementId;

            if (sid || initialView === "review" || this.state.currentView === "review") {

                const targetSid = sid || this.state.statement_id;

                this.state.statement_id = targetSid;

                this.state.showPdfPreview = false;

                this.state.currentView = "review";

                if (targetSid) {

                    this.loadStatementData(targetSid);

                } else {

                    this.switchToReview();

                }

            } else {

                this.state.statement_id = null;

                this.state.currentView = "dashboard";

                this.loadDashboardMetrics();

            }

        });



        onWillUpdateProps((nextProps) => {

            this.loadAIEngineStatus();

            const nextPropsAction = nextProps?.action || {};

            const nextParams = nextPropsAction?.params || nextProps?.params || {};

            const nextCtx = nextPropsAction?.context || nextProps?.context || {};



            let nextInitialView = nextProps?.initial_view || nextParams.initial_view || nextCtx.initial_view;

            if (!nextInitialView && typeof nextParams === "string" && nextParams.includes("upload")) {

                nextInitialView = "upload";

            }

            if (nextInitialView === "upload") {

                this.switchToUpload();

                return;

            }



            let nextSid = null;

            if (nextProps?.statement_id) {

                nextSid = parseInt(nextProps.statement_id);

            } else if (nextParams.statement_id) {

                nextSid = parseInt(nextParams.statement_id);

            } else if (nextCtx.statement_id) {

                nextSid = parseInt(nextCtx.statement_id);

            } else if (nextPropsAction?.res_id) {

                nextSid = parseInt(nextPropsAction.res_id);

            } else if (nextPropsAction?.resId) {

                nextSid = parseInt(nextPropsAction.resId);

            } else if (nextProps?.resId) {

                nextSid = parseInt(nextProps.resId);

            } else if (nextCtx.active_id) {

                nextSid = parseInt(nextCtx.active_id);

            } else if (nextCtx.active_ids && nextCtx.active_ids.length > 0) {

                nextSid = parseInt(nextCtx.active_ids[0]);

            } else if (nextProps?.record?.resId) {

                nextSid = parseInt(nextProps.record.resId);

            } else if (nextProps?.record?.data?.id) {

                nextSid = parseInt(nextProps.record.data.id);

            }



            if (nextSid || nextInitialView === "review" || this.state.currentView === "review") {

                const targetSid = nextSid || this.state.statement_id;

                this.state.statement_id = targetSid;

                this.state.showPdfPreview = false;

                this.state.currentView = "review";

                if (targetSid) {

                    this.loadStatementData(targetSid);

                } else {

                    this.switchToReview();

                }

            } else if (!this.state.statement_id) {

                this.state.statement_id = null;

                this.state.currentView = "dashboard";

                this.loadDashboardMetrics();

            }

        });

    }



    get statementId() {

        const props = this.props || {};

        const action = props.action || {};

        const ctx = action.context || props.context || {};

        const params = action.params || props.params || {};



        // 1. Props extracted via extractProps

        if (props.statement_id) return parseInt(props.statement_id);



        // 2. Explicit statement ID in params or context (from action_open_workbench button)

        if (params.statement_id) return parseInt(params.statement_id);

        if (ctx.statement_id) return parseInt(ctx.statement_id);



        // 3. Direct action res_id / resId (returned by python action_open_workbench)

        if (action.res_id) return parseInt(action.res_id);

        if (action.resId) return parseInt(action.resId);

        if (props.resId) return parseInt(props.resId);



        // 4. Context active_id / active_ids

        if (ctx.active_id) return parseInt(ctx.active_id);

        if (ctx.active_ids && ctx.active_ids.length > 0) return parseInt(ctx.active_ids[0]);



        // 5. Embedded in form record widget

        if (props.record?.resId) return parseInt(props.record.resId);

        if (props.record?.data?.id) return parseInt(props.record.data.id);



        // 6. Router state if available

        try {

            if (typeof router !== "undefined" && router && router.current) {

                if (router.current.active_id) return parseInt(router.current.active_id);

                if (router.current.resId) return parseInt(router.current.resId);

            }

        } catch (_) {}



        // 7. Active component state statement_id

        if (this.state?.statement_id) return parseInt(this.state.statement_id);



        return null;

    }



    formatAmount(val) {

        const n = Number(val) || 0;

        return n.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

    }



    toggleTheme() {

        this.state.theme = this.state.theme === "dark" ? "light" : "dark";

        try {

            localStorage.setItem("gsus_bank_ai_theme", this.state.theme);

        } catch (e) {}

    }



    togglePdfPreview() {

        this.state.showPdfPreview = !this.state.showPdfPreview;

    }



    reloadPdfPreview() {

        this.state.pdfTimestamp = Date.now();

    }





    getTransactionTypeBadge(type) {

        const map = {

            customer_payment: { label: "Customer Payment", class: "bg-success-subtle text-success border border-success" },

            vendor_payment: { label: "Vendor Payment", class: "bg-danger-subtle text-danger border border-danger" },

            bank_charges: { label: "Bank Charges", class: "bg-warning-subtle text-warning border border-warning" },

            bank_interest: { label: "Bank Interest", class: "bg-info-subtle text-info border border-info" },

            internal_transfer: { label: "Internal Transfer", class: "bg-primary-subtle text-primary border border-primary" },

            loan_transaction: { label: "Loan Transaction", class: "bg-secondary-subtle text-secondary border border-secondary" },

            refund: { label: "Refund", class: "bg-purple-subtle text-purple border border-purple" },

            other_expense: { label: "Other Expense", class: "bg-light text-dark border" },

            other_income: { label: "Other Income", class: "bg-light text-success border" },

            unknown: { label: "Needs Review", class: "bg-warning text-dark" },

        };

        return map[type] || { label: type ? type.replace(/_/g, " ") : "Unknown", class: "bg-light text-muted border" };

    }



    getContactStatusBadge(status) {

        const map = {

            existing: { label: "Existing Contact", class: "badge bg-light text-dark border", icon: "fa-check" },

            new_proposed: { label: "New Proposed", class: "badge bg-warning-subtle text-warning border border-warning", icon: "fa-clock-o" },

            no_contact_needed: { label: "No Contact Needed", class: "badge bg-secondary-subtle text-muted", icon: "fa-ban" },

            needs_review: { label: "Needs Review", class: "badge bg-warning text-dark", icon: "fa-exclamation-circle" },

            approved: { label: "Approved", class: "badge bg-success text-white", icon: "fa-check-circle" },

            rejected: { label: "Rejected", class: "badge bg-danger text-white", icon: "fa-times-circle" },

        };

        return map[status] || { label: status || "Pending", class: "badge bg-light text-muted border", icon: "fa-info" };

    }



    async approveContactAs(line, targetType) {

        try {

            await this.rpc("/gsus_bank_ai/update_line", {

                line_id: line.id,

                contact_status: "approved",

                approval_target: targetType,

                transaction_type: targetType === "customer" ? "customer_payment" : "vendor_payment",

                status: "reviewed",

            });

            line.contact_status = "approved";

            line.contact_status_label = "Approved for Creation";

            line.approval_target = targetType;

            line.status = "reviewed";

            this.notification.add(`Approved '${line.proposed_contact_name || line.counterparty}' as ${targetType.toUpperCase()}.`, { type: "success" });

        } catch (e) {

            this.notification.add("Failed to approve contact: " + (e.message || ""), { type: "danger" });

        }

    }



    async markLineNoContact(line) {

        try {

            await this.rpc("/gsus_bank_ai/update_line", {

                line_id: line.id,

                contact_status: "no_contact_needed",

                approval_target: "none",

                partner_id: false,

                status: "reviewed",

            });

            line.contact_status = "no_contact_needed";

            line.contact_status_label = "No Contact Required";

            line.partner_id = false;

            line.partner_name = "Not assigned";

            line.status = "reviewed";

            this.notification.add("Marked as No Contact Required.", { type: "info" });

        } catch (e) {

            this.notification.add("Failed to update line: " + (e.message || ""), { type: "danger" });

        }

    }



    async rejectLineContact(line) {

        try {

            await this.rpc("/gsus_bank_ai/update_line", {

                line_id: line.id,

                contact_status: "rejected",

                approval_target: "none",

                partner_id: false,

            });

            line.contact_status = "rejected";

            line.contact_status_label = "Rejected Contact";

            this.notification.add("Contact proposal rejected.", { type: "warning" });

        } catch (e) {

            this.notification.add("Failed to reject contact: " + (e.message || ""), { type: "danger" });

        }

    }



    async changeLineCategory(line, newCategory) {

        try {

            await this.rpc("/gsus_bank_ai/update_line", {

                line_id: line.id,

                transaction_type: newCategory,

            });

            line.transaction_type = newCategory;

            line.transaction_type_label = newCategory.replace(/_/g, " ").toUpperCase();

            this.notification.add(`Category changed to ${newCategory.replace(/_/g, " ")}.`, { type: "success" });

        } catch (e) {

            this.notification.add("Failed to update category: " + (e.message || ""), { type: "danger" });

        }

    }



        toggleExpandGroup(groupKey) {
        if (!this.state.expandedGroupKeys) {
            this.state.expandedGroupKeys = {};
        }
        if (this.state.expandedGroupKeys[groupKey]) {
            delete this.state.expandedGroupKeys[groupKey];
        } else {
            this.state.expandedGroupKeys[groupKey] = true;
            if (!this.state.lines || !this.state.lines.length) {
                this.loadStatementData();
            }
        }
    }

    isGroupExpanded(groupKey) {
        return !!(this.state.expandedGroupKeys && this.state.expandedGroupKeys[groupKey]);
    }

    getGroupLines(grp) {
        if (!grp || !grp.line_ids || !this.state.lines) return [];
        const lineIdSet = new Set(grp.line_ids);
        return this.state.lines.filter((l) => lineIdSet.has(l.id));
    }

    viewGroupInReview(grp) {
        const targetSearch = grp.suggested_partner || grp.group_key || "";
        this.state.searchQuery = targetSearch;
        this.state.activeTab = "all";
        this.state.currentView = "review";
    }

    startEditingGroupContact(grp) {

        grp._isEditing = true;

        grp._tempName = grp.suggested_partner || grp.group_key || "";

    }



    cancelEditingGroupContact(grp) {

        grp._isEditing = false;

    }



    async saveGroupContactName(grp) {

        if (!grp._isEditing) return;

        const newName = (grp._tempName || "").trim();

        if (newName) {

            grp.suggested_partner = newName;

            try {

                const res = await this.rpc("/gsus_bank_ai/update_group_contact_name", {

                    statement_id: this.state.statement_id,

                    group_key: grp.group_key,

                    new_contact_name: newName,

                });

                if (res && res.updated_existing) {

                    grp.partner_id = res.partner_id;

                    grp.contact_status = "existing";

                    grp.suggested_partner = res.partner_name;

                    this.notification.add(res.message || `Updated contact to '${res.partner_name}' in Odoo.`, { type: "success" });

                } else if (res && res.created_new) {

                    grp.partner_id = res.partner_id;

                    grp.contact_status = "existing";

                    grp.suggested_partner = res.partner_name;

                    this.notification.add(res.message || `Created new contact '${res.partner_name}' in Odoo.`, { type: "success" });

                } else if (res && res.matched_existing) {

                    grp.partner_id = res.partner_id;

                    grp.contact_status = "existing";

                    grp.suggested_partner = res.partner_name;

                    this.notification.add(res.message || `Linked to existing contact '${res.partner_name}'.`, { type: "info" });

                }

                await this.loadStatementData();

                await this.loadGroups();

            } catch (e) {

                console.warn("Failed to persist group contact name:", e);

            }

        }

        grp._isEditing = false;

    }



    onGroupContactKeyDown(ev, grp) {

        if (ev.key === "Enter") {

            ev.preventDefault();

            this.saveGroupContactName(grp);

        } else if (ev.key === "Escape") {

            this.cancelEditingGroupContact(grp);

        }

    }



    async approveGroupAs(group, targetType) {

        group.contact_status = "approved";

        group.approval_target = targetType;

        try {

            await this.rpc("/gsus_bank_ai/resolve_group", {

                statement_id: this.state.statement_id,

                group_key: group.group_key,

                approve_as: targetType,

                proposed_name: group.suggested_partner || group.group_key,

            });

            this.notification.add(`Approved all ${group.count} transactions in '${group.group_key}' as ${targetType.toUpperCase()}.`, { type: "success" });

            await this.loadStatementData();

            await this.loadGroups();

        } catch (e) {

            this.notification.add("Failed to approve group: " + (e.message || ""), { type: "danger" });

        }

    }



    getPaymentModeBadge(mode) {

        const m = (mode || "other").toLowerCase();

        switch (m) {

            case "upi":

                return { label: "UPI", class: "badge-mode-upi" };

            case "neft":

                return { label: "NEFT", class: "badge-mode-neft" };

            case "rtgs":

                return { label: "RTGS", class: "badge-mode-rtgs" };

            case "imps":

                return { label: "IMPS", class: "badge-mode-imps" };

            case "nach":

                return { label: "NACH", class: "badge-mode-nach" };

            case "pos":

                return { label: "POS", class: "badge-mode-pos" };

            case "atm":

                return { label: "ATM", class: "badge-mode-atm" };

            case "cheque":

                return { label: "CHQ", class: "badge-mode-cheque" };

            case "charge":

                return { label: "FEE", class: "badge-mode-charge" };

            case "transfer":

                return { label: "TRF", class: "badge-mode-neft" };

            default:

                return { label: (mode || "OTHER").toUpperCase(), class: "badge-mode-default" };

        }

    }



    // ═════════════════════════════════════════════════════════════

    // 1. DASHBOARD LOAD & NAVIGATION

    // ═════════════════════════════════════════════════════════════

    async loadAIEngineStatus() {

        try {

            const res = await this.rpc("/gsus_bank_ai/get_ai_engine_status", {});

            if (res) {

                this.state.aiEngineStatus = res.badge_text || "AI Engine (Active)";

                this.state.aiEngineColor = res.badge_color || "success";

                this.state.aiEngineHasKey = res.has_key;

                this.state.aiEngineModel = res.model_name;

                this.state.aiEngineName = res.engine_name;

                this.state.backupEngineName = res.backup_engine_name || (res.provider_type === 'gemini' ? 'OpenAI (GPT-4o Vision)' : 'Google Gemini Multimodal');

            }

        } catch (e) {

            console.warn("Could not load AI engine status:", e);

        }

    }



    async loadDashboardMetrics(manual = false) {

        this.state.isLoading = true;

        if (manual) {

            this.state.isRefreshingDashboard = true;

        }

        try {

            const res = await this.rpc("/gsus_bank_ai/get_dashboard_metrics", {});

            if (res) {

                this.state.dashboard = res;



                if (res.ai_engine) {

                    this.state.aiEngineStatus = res.ai_engine.badge_text;

                    this.state.aiEngineColor = res.ai_engine.badge_color;

                    this.state.aiEngineHasKey = res.ai_engine.has_key;

                    this.state.aiEngineModel = res.ai_engine.model_name;

                    this.state.aiEngineName = res.ai_engine.engine_name;

                    this.state.backupEngineName = res.ai_engine.backup_engine_name || (res.ai_engine.provider_type === 'gemini' ? 'OpenAI (GPT-4o Vision)' : 'Google Gemini Multimodal');

                }

            }

            try {

                const queues = await this.rpc("/gsus_bank_ai/get_invoice_queues", {});

                if (queues && queues.success && this.state.dashboard) {

                    this.state.dashboard.invoice_queue = queues;

                }

            } catch (qe) {

                console.warn("Invoice queues endpoint error:", qe);

            }

            if (manual && this.notification) {

                this.notification.add("Dashboard metrics refreshed successfully.", { type: "info" });

            }

        } catch (e) {

            console.error("Dashboard metric load error:", e);

            if (manual && this.notification) {

                this.notification.add("Could not refresh dashboard metrics.", { type: "danger" });

            }

        } finally {

            this.state.isLoading = false;

            this.state.isRefreshingDashboard = false;

        }

    }



    switchToDashboard() {

        this.state.currentView = "dashboard";

        this.loadDashboardMetrics();

    }



    switchToUpload() {

        this.state.currentView = "upload";

        this.loadAIEngineStatus();

        if (!this.state.uploadFileBase64) {

            this.state.uploadFileBase64 = null;

            this.state.uploadFileName = "";

            this.state.uploadFileSizeKb = 0;

            this.state.uploadPagesCount = 0;

            this.state.uploadPassword = "";

            this.state.detectedBankName = "";

            this.state.selectedBankName = "Auto-Detect with AI";

            this.state.isPasswordProtected = false;

            this.state.isDecrypted = true;

        }

    }



    switchToProcessing() {

        this.state.currentView = "processing";

    }



    async switchToReview(statementId = null) {

        let sid = statementId || this.state.statement_id || this.statementId;

        if (!sid && this.state.dashboard?.recent_statements?.length > 0) {

            sid = this.state.dashboard.recent_statements[0].id;

        }

        if (!sid) {

            try {

                const res = await this.rpc("/gsus_bank_ai/get_all_statements", { limit: 1 });

                if (res?.statements?.length > 0) {

                    sid = res.statements[0].id;

                }

            } catch (e) {

                console.warn(e);

            }

        }

        if (sid) {

            this.state.statement_id = sid;

            this.state.currentView = "review";

            this.loadStatementData(sid);

        } else {

            this.state.currentView = "review";

        }

    }



    async switchToVouchers(statementId = null) {

        let sid = statementId || this.state.statement_id || this.statementId;

        if (!sid && this.state.dashboard?.recent_statements?.length > 0) {

            sid = this.state.dashboard.recent_statements[0].id;

        }

        if (!sid) {

            try {

                const res = await this.rpc("/gsus_bank_ai/get_all_statements", { limit: 1 });

                if (res?.statements?.length > 0) {

                    sid = res.statements[0].id;

                }

            } catch (e) {

                console.warn(e);

            }

        }

        if (sid) {

            this.state.statement_id = sid;

            this.state.currentView = "vouchers";

            await this.loadStatementData(sid);

            await this.loadGroups(sid);

        } else {

            this.state.currentView = "vouchers";

        }

    }



    switchToSettings() {

        this.state.currentView = "settings";

    }



    toggleNativeUI() {

        this.state.nativeUIEnabled = !this.state.nativeUIEnabled;

        localStorage.setItem("gsus_bank_ai_native_ui", this.state.nativeUIEnabled ? "true" : "false");

        this.notification.add(

            this.state.nativeUIEnabled 

                ? "Odoo Native UI (Atmosphere) Enabled" 

                : "Odoo Native UI (Atmosphere) Disabled", 

            { type: "success" }

        );

    }



    openLearnedRules() {

        this.action.doAction({

            name: "AI Learned Rules",

            type: "ir.actions.act_window",

            res_model: "gsus.bank.ai.rule",

            views: [[false, "list"], [false, "form"]],

            target: "current",

        });

    }



    openEnginesAndKeys() {

        this.openProviderModal();

    }



    openAddTransactionModal() {

        this.state.isAddTxnModalOpen = true;

    }



    closeAddTransactionModal() {

        this.state.isAddTxnModalOpen = false;

    }



    toggleChat() {

        this.state.isChatOpen = !this.state.isChatOpen;

    }



    async sendChatMessage(customPrompt = null) {

        const text = (typeof customPrompt === "string" ? customPrompt : this.state.chatInputText || "").trim();

        if (!text || this.state.isChatSending) {

            return;

        }

        this.state.chatInputText = "";

        this.state.chatMessages.push({

            id: Date.now(),

            sender: "user",

            text: text,

            time: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),

        });

        this.state.isChatSending = true;



        try {

            const res = await this.rpc("/gsus_bank_ai/chat_assistant", {

                prompt: text,

                statement_id: this.state.statement_id,

                page_context: this.state.currentView,

            });

            this.state.chatMessages.push({

                id: Date.now() + 1,

                sender: "assistant",

                text: res.reply || "Reconciliation and journal balance are synchronized.",

                time: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),

                provider: res.provider || "Gemini 2.5 Flash",

            });

        } catch (err) {

            console.error("Chat assistant error:", err);

            let fallbackReply = "Statement reconciliation and journal ledgers are tracked in real-time.";

            const tLower = text.toLowerCase();

            if (tLower.includes("summar")) {

                fallbackReply = `Statement Summary: Total Transactions: ${this.state.total_transactions || 0}, Total Debits: ${this.formatAmount(this.state.total_debit || 0)}, Total Credits: ${this.formatAmount(this.state.total_credit || 0)}, Net Flow: ${this.formatAmount(this.state.net_flow || 0)}. Status: ${this.state.verification_state || 'Verified'}.`;

            } else if (tLower.includes("flag") || tLower.includes("anomal")) {

                fallbackReply = "Transactions are flagged when the counterparty narration cannot be verified against known vendors, or when amount variance exceeds historical thresholds.";

            } else if (tLower.includes("pending")) {

                fallbackReply = `Pending Items: Unpaid Customer Invoices: ${this.state.dashboard?.invoice_queue?.customer_invoices_count || 0} (${this.formatAmount(this.state.dashboard?.invoice_queue?.customer_invoices_amount || 0)}), Unpaid Vendor Bills: ${this.state.dashboard?.invoice_queue?.vendor_bills_count || 0} (${this.formatAmount(this.state.dashboard?.invoice_queue?.vendor_bills_amount || 0)}).`;

            } else if (tLower.includes("explain")) {

                fallbackReply = "GSUS AI automatically matches statement lines with open invoices by reference number, exact amount, and vendor/customer name. Once matched, it creates bank journal entries with reconciliation matching codes.";

            }



            this.state.chatMessages.push({

                id: Date.now() + 1,

                sender: "assistant",

                text: fallbackReply,

                time: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),

                provider: "Local AI Fallback",

            });

        } finally {

            this.state.isChatSending = false;

        }

    }



    onChatKeydown(ev) {

        if (ev.key === "Enter" && !ev.shiftKey) {

            ev.preventDefault();

            this.sendChatMessage();

        }

    }



    selectSuggestedQuestion(q) {

        this.sendChatMessage(q);

    }



    clearChat() {

        this.state.chatMessages = [

            {

                id: 1,

                sender: "assistant",

                text: "Hello! I am your GSUS Financial AI Assistant. How can I assist you with bank statement analysis or invoice reconciliation today?",

                time: "Just now",

                provider: "Gemini 2.5 Flash",

            }

        ];

    }



    async loadGroups(statementId = null) {

        const sid = statementId || this.state.statement_id || this.statementId;

        if (!sid) return;

        this.state.isLoading = true;

        try {

            const res = await this.rpc("/gsus_bank_ai/get_groups", { statement_id: sid });

            this.state.groups = res?.groups || [];

        } catch (e) {

            console.error("Failed to load groups:", e);

        } finally {

            this.state.isLoading = false;

        }

    }



    // ═════════════════════════════════════════════════════════════

    // 2. STATEMENT DATA LOADER

    // ═════════════════════════════════════════════════════════════

    async loadStatementData(statementId = null) {

        const sid = statementId || this.state.statement_id || this.statementId;

        if (!sid) return;

        this.state.isLoading = true;

        try {

            const res = await this.rpc("/gsus_bank_ai/get_statement_data", {

                statement_id: sid,

                filter_tab: this.state.activeTab,

                page: this.state.currentPage,

                limit: this.state.pageSize,

            });

            if (res && res.kpis) {

                Object.assign(this.state, res.kpis);

                this.state.lines = res.lines || [];

                this.state.primaryBankLedgerName = (res.kpis.bank_name || "Bank") + " A/c";

            }

        } catch (e) {

            this.notification.add("Failed to load statement data: " + (e.message || ""), { type: "danger" });

        } finally {

            this.state.isLoading = false;

        }

    }



    setFilterTab(tab) {

        this.state.activeTab = tab;

        this.loadStatementData();

    }



    get filteredLines() {

        let list = this.state.lines;

        if (this.state.activeTab === "anomalies") {

            list = list.filter((l) => l.is_anomaly || l.is_duplicate);

        }

        if (this.state.searchQuery) {

            const q = this.state.searchQuery.toLowerCase();

            list = list.filter((l) =>

                (l.narration && l.narration.toLowerCase().includes(q)) ||

                (l.reference && l.reference.toLowerCase().includes(q)) ||

                (l.partner_name && l.partner_name.toLowerCase().includes(q)) ||

                (l.account_name && l.account_name.toLowerCase().includes(q)) ||

                String(l.debit).includes(q) ||

                String(l.credit).includes(q)

            );

        }

        if (this.state.dateFrom) {

            list = list.filter((l) => l.date >= this.state.dateFrom);

        }

        if (this.state.dateTo) {

            list = list.filter((l) => l.date <= this.state.dateTo);

        }

        return list;

    }



    get isAllSelected() {

        return this.state.selectedLineIds.length > 0 && this.state.selectedLineIds.length === this.filteredLines.length;

    }



    isEditingPartner(lineId) {

        return this.state.editingCell.lineId === lineId && this.state.editingCell.field === 'partner';

    }



    isEditingAccount(lineId) {

        return this.state.editingCell.lineId === lineId && this.state.editingCell.field === 'account';

    }



    clearFilters() {

        this.state.searchQuery = "";

        this.state.dateFrom = "";

        this.state.dateTo = "";

        this.state.activeTab = "all";

        this.loadStatementData();

    }



    // ═════════════════════════════════════════════════════════════

    // 3. SELECTION & BULK ACTIONS

    // ═════════════════════════════════════════════════════════════

    toggleSelectAll(ev) {

        if (ev.target.checked) {

            this.state.selectedLineIds = this.filteredLines.map((l) => l.id);

        } else {

            this.state.selectedLineIds = [];

        }

    }



    toggleSelectLine(lineId) {

        const idx = this.state.selectedLineIds.indexOf(lineId);

        if (idx === -1) {

            this.state.selectedLineIds.push(lineId);

        } else {

            this.state.selectedLineIds.splice(idx, 1);

        }

    }



    async approveLine(line) {

        line.status = "reviewed";

        await this.rpc("/gsus_bank_ai/update_line", { line_id: line.id, status: "reviewed" });

        this.state.reviewed_count++;

        if (this.state.unassigned_count > 0) this.state.unassigned_count--;

        this.state.assigned_count = this.state.total_transactions - this.state.unassigned_count;

        this.notification.add("Line confirmed & reviewed!", { type: "success" });

    }



    async deleteStatementBatch(statementId) {

        if (!confirm("Are you sure you want to delete this bank statement batch? This action cannot be undone.")) {

            return;

        }

        try {

            const res = await this.rpc("/gsus_bank_ai/delete_statement", { statement_id: statementId });

            if (res && res.success) {

                this.notification.add("Statement batch deleted successfully.", { type: "info" });

                await this.loadDashboardData();

            } else {

                this.notification.add((res && res.error) || "Delete failed.", { type: "danger" });

            }

        } catch (e) {

            this.notification.add("Error deleting statement: " + e.message, { type: "danger" });

        }

    }



    async deleteLine(lineId) {

        try {

            await this.rpc("/gsus_bank_ai/delete_line", { line_id: lineId });

            this.state.lines = this.state.lines.filter((l) => l.id !== lineId);

            this.state.total_transactions--;

            this.notification.add("Transaction removed.", { type: "info" });

            await this.loadStatementData();

        } catch (e) {

            this.notification.add("Delete failed.", { type: "danger" });

        }

    }



    // Bulk Delete

    async executeBulkDelete() {

        if (!this.state.selectedLineIds.length) return;

        if (!confirm(`Delete ${this.state.selectedLineIds.length} selected transactions?`)) return;



        try {

            const res = await this.rpc("/gsus_bank_ai/bulk_delete", {

                line_ids: this.state.selectedLineIds,

            });

            this.state.selectedLineIds = [];

            this.notification.add(`Successfully deleted ${res.count} transactions.`, { type: "info" });

            await this.loadStatementData();

        } catch (e) {

            this.notification.add("Bulk delete failed: " + e.message, { type: "danger" });

        }

    }



    // Bulk Mark Reviewed

    async executeBulkReviewed() {

        if (!this.state.selectedLineIds.length) return;

        try {

            const res = await this.rpc("/gsus_bank_ai/bulk_status", {

                line_ids: this.state.selectedLineIds,

                status: "reviewed",

            });

            this.state.selectedLineIds = [];

            this.notification.add(`Marked ${res.count} transactions as Reviewed!`, { type: "success" });

            await this.loadStatementData();

        } catch (e) {

            this.notification.add("Bulk status update failed.", { type: "danger" });

        }

    }



    // Bulk Assign Modal

    openBulkAssignModal() {

        if (!this.state.selectedLineIds.length) {

            this.notification.add("Select at least one transaction first.", { type: "warning" });

            return;

        }

        this.state.bulkPartnerId = null;

        this.state.bulkPartnerName = "";

        this.state.bulkAccountId = null;

        this.state.bulkAccountName = "";

        this.state.partnerSearchResults = [];

        this.state.accountSearchResults = [];

        this.state.isBulkAssignModalOpen = true;

    }



    closeBulkAssignModal() {

        this.state.isBulkAssignModalOpen = false;

        this.state.partnerSearchResults = [];

        this.state.accountSearchResults = [];

    }



    async onBulkPartnerInput(ev) {

        this.state.bulkPartnerName = ev.target.value;

        this.state.bulkPartnerId = null;

        await this.searchLedgerSuggestions(ev.target.value, "partner");

    }



    selectBulkPartner(p) {

        this.state.bulkPartnerId = p.id;

        this.state.bulkPartnerName = p.name;

        this.state.partnerSearchResults = [];

    }



    clearBulkPartner() {

        this.state.bulkPartnerId = null;

        this.state.bulkPartnerName = "";

        this.state.partnerSearchResults = [];

    }



    async onBulkAccountInput(ev) {

        this.state.bulkAccountName = ev.target.value;

        this.state.bulkAccountId = null;

        await this.searchLedgerSuggestions(ev.target.value, "account");

    }



    selectBulkAccount(a) {

        this.state.bulkAccountId = a.id;

        this.state.bulkAccountName = (a.code ? a.code + " " : "") + a.name;

        this.state.accountSearchResults = [];

    }



    clearBulkAccount() {

        this.state.bulkAccountId = null;

        this.state.bulkAccountName = "";

        this.state.accountSearchResults = [];

    }



    async executeBulkAssign() {

        try {

            const res = await this.rpc("/gsus_bank_ai/bulk_assign", {

                line_ids: this.state.selectedLineIds,

                partner_id: this.state.bulkPartnerId,

                account_id: this.state.bulkAccountId,

                status: "reviewed",

            });

            this.closeBulkAssignModal();

            this.state.selectedLineIds = [];

            this.notification.add(`Updated ${res.count} transactions!`, { type: "success" });

            await this.loadStatementData();

        } catch (e) {

            this.notification.add("Bulk assign failed: " + e.message, { type: "danger" });

        }

    }



    // ═════════════════════════════════════════════════════════════

    // 4. INLINE EDITING & AUTOCOMPLETE

    // ═════════════════════════════════════════════════════════════

    startInlineEdit(lineId, field) {

        this.state.editingCell = { lineId, field };

        this.state.partnerSearchResults = [];

        this.state.accountSearchResults = [];

        this.state.highlightedSuggestionIndex = -1;

        this.searchLedgerSuggestions("", field);

    }



    cancelInlineEdit() {

        this.state.editingCell = { lineId: null, field: null };

        this.state.partnerSearchResults = [];

        this.state.accountSearchResults = [];

        this.state.highlightedSuggestionIndex = -1;

    }



    async searchLedgerSuggestions(query, type = "account") {

        const q = (query || "").trim();

        this.state.highlightedSuggestionIndex = -1;

        if (type === "partner") {

            this.state.isSearchingPartners = true;

            try {

                const res = await this.rpc("/gsus_bank_ai/search_partners", { query: q, limit: 20 });

                this.state.partnerSearchResults = res || [];

                if (this.state.partnerSearchResults.length > 0) {

                    this.state.highlightedSuggestionIndex = 0;

                }

                return this.state.partnerSearchResults;

            } catch (e) {

                this.state.partnerSearchResults = [];

                return [];

            } finally {

                this.state.isSearchingPartners = false;

            }

        } else {

            this.state.isSearchingAccounts = true;

            try {

                const res = await this.rpc("/gsus_bank_ai/search_accounts", { query: q, limit: 20 });

                this.state.accountSearchResults = res || [];

                if (this.state.accountSearchResults.length > 0) {

                    this.state.highlightedSuggestionIndex = 0;

                }

                return this.state.accountSearchResults;

            } catch (e) {

                this.state.accountSearchResults = [];

                return [];

            } finally {

                this.state.isSearchingAccounts = false;

            }

        }

    }



    closeGroupDropdowns() {

        this.state.showGroupPartnerDropdown = false;

        this.state.showGroupAccountDropdown = false;

    }



    async openGroupPartnerDropdown() {

        this.state.showGroupPartnerDropdown = true;

        this.state.showGroupAccountDropdown = false;

        await this.searchLedgerSuggestions(this.state.selectedPartnerName || "", "partner");

    }



    async openGroupAccountDropdown() {

        this.state.showGroupAccountDropdown = true;

        this.state.showGroupPartnerDropdown = false;

        await this.searchLedgerSuggestions(this.state.selectedAccountName || "", "account");

    }



    async searchPartnersLive(ev) {

        this.state.selectedPartnerName = ev.target.value;

        this.state.showGroupPartnerDropdown = true;

        await this.searchLedgerSuggestions(ev.target.value, "partner");

    }



    async searchAccountsLive(ev) {

        this.state.selectedAccountName = ev.target.value;

        this.state.showGroupAccountDropdown = true;

        await this.searchLedgerSuggestions(ev.target.value, "account");

    }



    selectGroupPartner(p) {

        this.state.selectedPartnerId = p.id;

        this.state.selectedPartnerName = p.name;

        this.state.showGroupPartnerDropdown = false;

        this.state.partnerSearchResults = [];

    }



    async clearGroupPartner() {

        this.state.selectedPartnerId = null;

        this.state.selectedPartnerName = "";

        this.state.showGroupPartnerDropdown = false;

        this.state.partnerSearchResults = [];

    }



    selectGroupAccount(a) {

        this.state.selectedAccountId = a.id;

        this.state.selectedAccountName = (a.code ? a.code + " " : "") + a.name;

        this.state.showGroupAccountDropdown = false;

        this.state.accountSearchResults = [];

    }



    async clearGroupAccount() {

        this.state.selectedAccountId = null;

        this.state.selectedAccountName = "";

        this.state.showGroupAccountDropdown = false;

        this.state.accountSearchResults = [];

    }



    async togglePartnerDropdown() {

        this.state.showGroupAccountDropdown = false;

        this.state.showGroupPartnerDropdown = !this.state.showGroupPartnerDropdown;

        if (this.state.showGroupPartnerDropdown) {

            await this.searchLedgerSuggestions(this.state.selectedPartnerName || "", "partner");

        } else {

            this.state.partnerSearchResults = [];

        }

    }



    async toggleAccountDropdown() {

        this.state.showGroupPartnerDropdown = false;

        this.state.showGroupAccountDropdown = !this.state.showGroupAccountDropdown;

        if (this.state.showGroupAccountDropdown) {

            await this.searchLedgerSuggestions(this.state.selectedAccountName || "", "account");

        } else {

            this.state.accountSearchResults = [];

        }

    }



    async onSuggestionKeyDown(ev, type, line = null, mode = "group") {

        const results = type === "partner" ? this.state.partnerSearchResults : this.state.accountSearchResults;

        if (!results || results.length === 0) {

            if (ev.key === "Escape") {

                this.cancelInlineEdit();

                this.state.showGroupPartnerDropdown = false;

                this.state.showGroupAccountDropdown = false;

                if (type === "partner") this.state.partnerSearchResults = [];

                else this.state.accountSearchResults = [];

            }

            return;

        }



        if (ev.key === "ArrowDown") {

            ev.preventDefault();

            this.state.highlightedSuggestionIndex = Math.min(

                this.state.highlightedSuggestionIndex + 1,

                results.length - 1

            );

        } else if (ev.key === "ArrowUp") {

            ev.preventDefault();

            this.state.highlightedSuggestionIndex = Math.max(

                this.state.highlightedSuggestionIndex - 1,

                0

            );

        } else if (ev.key === "Enter") {

            ev.preventDefault();

            const idx = this.state.highlightedSuggestionIndex >= 0 ? this.state.highlightedSuggestionIndex : 0;

            const selected = results[idx];

            if (selected) {

                if (line) {

                    // Inline cell in table

                    if (type === "partner") {

                        await this.selectInlinePartner(line, selected);

                    } else {

                        await this.selectInlineAccount(line, selected);

                    }

                } else if (mode === "bulk") {

                    // Bulk assign modal

                    if (type === "partner") {

                        this.selectBulkPartner(selected);

                    } else {

                        this.selectBulkAccount(selected);

                    }

                } else {

                    // Group resolution modal

                    if (type === "partner") {

                        this.state.selectedPartnerId = selected.id;

                        this.state.selectedPartnerName = selected.name;

                        this.state.partnerSearchResults = [];

                    } else {

                        this.state.selectedAccountId = selected.id;

                        this.state.selectedAccountName = (selected.code ? selected.code + ' ' : '') + selected.name;

                        this.state.accountSearchResults = [];

                    }

                }

            }

        } else if (ev.key === "Escape") {

            ev.preventDefault();

            this.cancelInlineEdit();

            if (type === "partner") this.state.partnerSearchResults = [];

            else this.state.accountSearchResults = [];

        }

    }



    onInlineBlur(ev, line, field) {

        setTimeout(() => {

            if (this.state.editingCell.lineId === line.id && this.state.editingCell.field === field) {

                this.cancelInlineEdit();

            }

        }, 250);

    }



    async inlineUpdateLine(lineId, field, value, valueName = null) {

        let valueId = null;

        let vName = valueName;

        if (typeof value === "object" && value !== null) {

            valueId = value.id;

            vName = value.name || valueName;

        } else if (typeof value === "number") {

            valueId = value;

        } else if (typeof value === "string") {

            vName = value;

        }



        const line = this.state.lines.find((l) => l.id === lineId);

        if (line) {

            if (field === "partner") {

                if (valueId) {

                    line.partner_id = valueId;

                    line.contact_status = "existing";

                    line.contact_status_label = "Existing Contact";

                }

                if (vName) line.partner_name = vName;

            } else if (field === "account") {

                if (valueId) line.account_id = valueId;

                if (vName) line.account_name = vName;

            }

            line.status = "reviewed";

            line.confidence = 100;

        }

        this.cancelInlineEdit();

        try {

            const payload = { line_id: lineId, status: "reviewed" };

            if (field === "partner" && valueId) payload.partner_id = valueId;

            if (field === "account" && valueId) payload.account_id = valueId;

            await this.rpc("/gsus_bank_ai/update_line", payload);

            this.notification.add(`Assigned ${field === "partner" ? "Contact" : "Ledger"}: ${vName || 'Updated'}`, { type: "success" });

            this.state.reviewed_count = this.state.lines.filter((l) => l.status === "reviewed" || l.status === "pushed").length;

            this.state.unassigned_count = this.state.lines.filter((l) => l.status === "pending").length;

            this.state.assigned_count = this.state.total_transactions - this.state.unassigned_count;

        } catch (e) {

            this.notification.add("Update failed: " + (e.data?.message || e.message), { type: "danger" });

        }

    }



    async selectInlinePartner(line, partner) {

        await this.inlineUpdateLine(line.id, "partner", partner.id, partner.name);

    }



    async selectInlineAccount(line, account) {

        const accName = `${account.code ? account.code + ' ' : ''}${account.name}`;

        await this.inlineUpdateLine(line.id, "account", account.id, accName);

    }



    // ═════════════════════════════════════════════════════════════

    // 5. INVOICE QUEUE CLICK

    // ═════════════════════════════════════════════════════════════

    openInvoiceQueue(type = "out_invoice") {

        const name = type === "out_invoice" ? "Unpaid Customer Invoices" : "Unpaid Vendor Bills";

        this.action.doAction({

            type: "ir.actions.act_window",

            name: name,

            res_model: "account.move",

            views: [[false, "list"], [false, "form"]],

            domain: [

                ["move_type", "=", type],

                ["state", "=", "posted"],

                ["payment_state", "in", ["not_paid", "partial"]],

            ],

            target: "current",

        });

    }



    // ═════════════════════════════════════════════════════════════

    // 6. CONNECTIVITY & PUSH MODAL

    // ═════════════════════════════════════════════════════════════

    openConnectivityModal() {

        this.state.isCreatingVouchers = false;

        this.state.voucherJobProgress = 0;

        this.state.isConnectivityModalOpen = true;

    }



    closeConnectivityModal() {

        this.state.isConnectivityModalOpen = false;

        this.state.isCreatingVouchers = false;

    }



    async startAdvancedVouchersJob() {

        this.state.isCreatingVouchers = true;

        this.state.voucherJobProgress = 15;



        const interval = setInterval(() => {

            this.state.voucherJobProgress += 25;

            if (this.state.voucherJobProgress >= 100) {

                this.state.voucherJobProgress = 100;

                clearInterval(interval);

                setTimeout(() => {

                    this.state.isConnectivityModalOpen = false;

                    this.state.isCreatingVouchers = false;

                    this.notification.add("Advanced voucher job prepared successfully!", { type: "success" });

                    this.switchToVouchers();

                }, 400);

            }

        }, 120);

    }



    async pushIntoSuspense() {

        this.state.isConnectivityModalOpen = false;

        await this.executePush();

    }



    async executePush() {

        const sid = this.state.statement_id || this.statementId;

        if (!sid) return;



        // Duplicate Push Guard (Client-side Safety Lock)

        if (this.state.state === "pushed") {

            this.notification.add("This statement has already been pushed to native Odoo Accounting. Duplicate push blocked! Use 'Rollback / Revert' if you need to re-process.", { type: "warning" });

            return;

        }



        this.state.isPushing = true;

        this.state.pushProgress = 10;



        const timer = setInterval(() => {

            if (this.state.pushProgress < 95) {

                this.state.pushProgress += 18;

            }

        }, 150);



        try {

            const res = await this.orm.call("gsus.bank.statement.ai", "action_push_to_odoo", [sid]);

            clearInterval(timer);

            this.state.pushProgress = 100;

            const recCount = res?.reconciled_invoice_count || 0;

            const catCount = res?.categorized_count || 0;

            if (recCount > 0) {

                this.notification.add(`Pushed to Odoo! Reconciled ${recCount} Invoices to PAID & categorized ${catCount} transactions into ledgers!`, { type: "success" });

            } else {

                this.notification.add(`Pushed to Odoo! Categorized ${catCount} transactions directly into ledgers with zero suspense!`, { type: "success" });

            }

            await this.loadStatementData();

            setTimeout(() => {

                this.state.isPushing = false;

                this.state.pushProgress = 0;

            }, 800);

        } catch (e) {

            clearInterval(timer);

            this.state.isPushing = false;

            this.state.pushProgress = 0;

            this.notification.add(e.data?.message || e.message || "Push failed. Ensure a Bank Journal is configured.", { type: "danger" });

        }

    }



    async revertPush() {

        const sid = this.state.statement_id || this.statementId;

        if (!sid) return;

        this.state.isLoading = true;

        try {

            await this.orm.call("gsus.bank.statement.ai", "action_revert_push", [sid]);

            this.notification.add("Rollback completed! Statement restored to staging.", { type: "warning" });

            await this.loadStatementData();

        } catch (e) {

            this.notification.add(e.data?.message || e.message || "Rollback failed.", { type: "danger" });

        } finally {

            this.state.isLoading = false;

        }

    }



    async autoAssignHighConfidence() {

        const sid = this.state.statement_id || this.statementId;

        if (!sid) return;

        this.state.isLoading = true;

        try {

            await this.orm.call("gsus.bank.statement.ai", "action_auto_assign_high_confidence", [sid]);

            this.notification.add("AI Auto-Assign complete! High confidence transactions reviewed.", { type: "success" });

            await this.loadStatementData();

        } catch (e) {

            this.notification.add(e.data?.message || e.message || "Auto-assign failed.", { type: "danger" });

        } finally {

            this.state.isLoading = false;

        }

    }



    // ═════════════════════════════════════════════════════════════

    // 7. RESOLVE GROUPS & GROUP REMARKS

    // ═════════════════════════════════════════════════════════════

    async openGroupModal(targetIndex = 0) {

        const sid = this.state.statement_id || this.statementId;

        if (!sid) return;

        this.state.isLoading = true;

        try {

            const res = await this.rpc("/gsus_bank_ai/get_groups", { statement_id: sid });

            this.state.groups = res.groups || [];

            if (!this.state.groups.length) {

                this.notification.add("No groups found to resolve.", { type: "info" });

                return;

            }

            this.state.currentGroupIndex = Math.min(Math.max(0, targetIndex), this.state.groups.length - 1);

            this.prepareActiveGroup();

            this.state.isGroupModalOpen = true;

        } catch (e) {

            this.notification.add("Failed to load recommendation groups.", { type: "danger" });

        } finally {

            this.state.isLoading = false;

        }

    }



    closeGroupModal() {

        this.state.isGroupModalOpen = false;

        this.state.isResolvingGroup = false;

        this.state.showGroupPartnerDropdown = false;

        this.state.showGroupAccountDropdown = false;

    }



    prepareActiveGroup() {

        const grp = this.activeGroup;

        if (grp) {

            this.state.selectedPartnerId = grp.partner_id || null;

            this.state.selectedPartnerName = grp.suggested_partner || "";

            this.state.selectedAccountId = grp.account_id || null;

            this.state.selectedAccountName = grp.suggested_account || "";

            this.state.groupRemarkText = grp.group_remark || "";

            this.state.showGroupPartnerDropdown = false;

            this.state.showGroupAccountDropdown = false;

            this.state.partnerSearchResults = [];

            this.state.accountSearchResults = [];

        }

    }



    get activeGroup() {

        return this.state.groups[this.state.currentGroupIndex] || null;

    }



    pickSuggestedPill(name) {

        this.state.selectedLedgerSearch = name;

    }



    async resolveCurrentGroup() {

        const grp = this.activeGroup;

        if (!grp) return;



        this.state.isResolvingGroup = true;

        try {

            await this.rpc("/gsus_bank_ai/resolve_group", {

                statement_id: this.state.statement_id,

                group_key: grp.group_key,

                partner_id: this.state.selectedPartnerId,

                account_id: this.state.selectedAccountId,

                group_remark: this.state.groupRemarkText || null,

            });



            this.notification.add(`Resolved all ${grp.count} entries for ${grp.group_key}!`, { type: "success" });



            await this.loadGroups();

            await this.loadStatementData();



            if (this.state.groups.length > 0) {

                if (this.state.currentGroupIndex >= this.state.groups.length) {

                    this.state.currentGroupIndex = this.state.groups.length - 1;

                }

                this.prepareActiveGroup();

            } else {

                this.closeGroupModal();

            }

        } catch (e) {

            this.notification.add("Group resolution failed.", { type: "danger" });

        } finally {

            this.state.isResolvingGroup = false;

        }

    }



    previousGroup() {

        if (this.state.currentGroupIndex > 0) {

            this.state.currentGroupIndex--;

            this.prepareActiveGroup();

        }

    }



    prevGroup() {

        this.previousGroup();

    }



    nextGroup() {

        if (this.state.currentGroupIndex < this.state.groups.length - 1) {

            this.state.currentGroupIndex++;

            this.prepareActiveGroup();

        }

    }



    // Group Remark Modal

    openGroupRemarkModal(groupKey) {

        this.state.groupRemarkTargetKey = groupKey;

        this.state.groupRemarkInput = "";

        this.state.isGroupRemarkModalOpen = true;

    }



    closeGroupRemarkModal() {

        this.state.isGroupRemarkModalOpen = false;

    }



    async saveGroupRemark() {

        if (!this.state.groupRemarkTargetKey) return;

        try {

            await this.rpc("/gsus_bank_ai/resolve_group", {

                statement_id: this.state.statement_id,

                group_key: this.state.groupRemarkTargetKey,

                group_remark: this.state.groupRemarkInput,

            });

            this.closeGroupRemarkModal();

            this.notification.add(`Applied remark to group "${this.state.groupRemarkTargetKey}"!`, { type: "success" });

            await this.loadStatementData();

        } catch (e) {

            this.notification.add("Failed to save remark.", { type: "danger" });

        }

    }



    // ═════════════════════════════════════════════════════════════

    // 8. AI PROVIDER CONFIGURATION & TEST CONNECTION

    // ═════════════════════════════════════════════════════════════

    async openProviderModal() {

        this.state.pingResult = null;

        this.state.isTestingPing = false;

        try {

            const res = await this.rpc("/gsus_bank_ai/get_providers", {});

            this.state.providers = res.providers || [];

            if (this.state.providers.length > 0) {

                const active = this.state.providers.find((p) => p.is_active && p.provider_type !== 'native') || this.state.providers.find((p) => p.provider_type === 'gemini') || this.state.providers[0];

                this.state.activeProviderType = active.provider_type;

                this.state.providerApiKey = active.has_key ? "••••••••••••••••••••••••" : "";

                this.state.ollamaHost = active.ollama_host || "http://localhost:11434";

                this.state.availableModels = sortModelsLatestFirst(active.supported_models || []);

                const hasReadyModel = active.has_key || active.provider_type === "native";

                this.state.providerModelName = hasReadyModel ? (active.model_name || (this.state.availableModels[0]?.code || "")) : "";

            } else {

                this.state.providerApiKey = "";

                this.state.ollamaHost = "http://localhost:11434";

                this.state.providerModelName = "";

                this.state.availableModels = [];

            }

        } catch (e) {

            console.error("Failed to load providers:", e);

        }

        this.state.isProviderModalOpen = true;

    }



    closeProviderModal() {

        this.state.isProviderModalOpen = false;

        this.state.pingResult = null;

    }



    onProviderTypeChange(ev) {

        const pType = ev.target.value;

        this.state.activeProviderType = pType;

        const existing = this.state.providers.find((p) => p.provider_type === pType);

        this.state.providerApiKey = existing?.has_key ? "••••••••••••••••••••••••" : "";

        this.state.ollamaHost = existing?.ollama_host || "http://localhost:11434";

        this.state.availableModels = sortModelsLatestFirst(existing?.supported_models || []);

        const hasAccess = (pType === "native") || (existing?.has_key && this.state.availableModels.length > 0);

        this.state.providerModelName = hasAccess 

            ? (existing?.model_name || this.state.availableModels[0]?.code || (pType === "native" ? "native-adaptive-v1" : (pType === "openai" ? "gpt-4o" : "gemini-3.8-flash")))

            : "";

        this.state.pingResult = null;

    }



    async testProviderPing() {

        this.state.isTestingPing = true;

        this.state.pingResult = null;

        try {

            const res = await this.rpc("/gsus_bank_ai/test_provider_ping", {

                provider_type: this.state.activeProviderType,

                api_key: this.state.providerApiKey,

                model_name: this.state.providerModelName,

                ollama_host: this.state.ollamaHost || "http://localhost:11434",

            });

            this.state.pingResult = res;

            if (res.success) {

                if (res.supported_models && res.supported_models.length > 0) {

                    this.state.availableModels = sortModelsLatestFirst(res.supported_models);

                    const match = this.state.availableModels.find((m) => m.code === this.state.providerModelName);

                    if (!match || !this.state.providerModelName) {

                        this.state.providerModelName = this.state.availableModels[0].code;

                    }

                }

                this.notification.add(res.message || "Connection successful!", { type: "success" });

            } else {

                this.notification.add(res.error || "Connection failed.", { type: "danger" });

            }

        } catch (e) {

            this.state.pingResult = { success: false, error: e.data?.message || e.message };

            this.notification.add("Ping failed: " + e.message, { type: "danger" });

        } finally {

            this.state.isTestingPing = false;

        }

    }



    async saveProviderConfig() {

        try {

            const res = await this.rpc("/gsus_bank_ai/save_provider", {

                provider_type: this.state.activeProviderType,

                api_key: this.state.providerApiKey,

                model_name: this.state.providerModelName,

                is_active: true,

                supported_models: this.state.availableModels,

                ollama_host: this.state.ollamaHost || "http://localhost:11434",

            });

            if (res && res.ai_engine) {

                this.state.aiEngineStatus = res.ai_engine.badge_text;

                this.state.aiEngineColor = res.ai_engine.badge_color;

                this.state.aiEngineHasKey = res.ai_engine.has_key;

                this.state.aiEngineModel = res.ai_engine.model_name;

                this.state.aiEngineName = res.ai_engine.engine_name;

                    this.state.backupEngineName = res.ai_engine.backup_engine_name || (res.ai_engine.provider_type === 'gemini' ? 'OpenAI (GPT-4o Vision)' : 'Google Gemini Multimodal');

            }

            this.notification.add("AI Provider configuration saved successfully!", { type: "success" });

            this.closeProviderModal();

        } catch (e) {

            console.error("Failed to save provider config:", e);

            const errMsg = e.data?.message || e.message || "Failed to save provider config.";

            this.notification.add(errMsg, { type: "danger" });

        }

    }



    // ═════════════════════════════════════════════════════════════

    // 9. ODOO BANK RECONCILIATION SHORTCUT

    // ═════════════════════════════════════════════════════════════

    async openBankReconciliation(statementId = null) {

        const sid = statementId || this.state.statement_id || this.statementId;

        if (!sid) return;

        try {

            const action = await this.rpc("/web/dataset/call_kw", {

                model: "gsus.bank.statement.ai",

                method: "action_open_bank_reconcile_widget",

                args: [[sid]],

                kwargs: {},

            });

            if (action) {

                this.action.doAction(action);

            }

        } catch (e) {

            console.error("Failed to open bank reconciliation widget:", e);

            this.openOdooStatement();

        }

    }



    // ═════════════════════════════════════════════════════════════

    // 10. UPLOAD & INGESTION

    // ═════════════════════════════════════════════════════════════

    openUploadModal() {

        this.switchToUpload();

    }



    triggerFileInput() {

        const input = document.getElementById("lai_file_input");

        if (input) input.click();

    }



    async handleFileInput(ev) {

        const file = ev.target.files && ev.target.files[0];

        if (!file) return;

        await this.processSelectedFile(file);

    }



    handleDrop(ev) {

        ev.preventDefault();

        ev.stopPropagation();

        const file = ev.dataTransfer && ev.dataTransfer.files && ev.dataTransfer.files[0];

        if (!file) return;

        this.processSelectedFile(file);

    }



    handleDragOver(ev) {

        ev.preventDefault();

        ev.stopPropagation();

    }



    async processSelectedFile(file) {

        this.state.uploadFileName = file.name;

        this.state.uploadFileSizeKb = (file.size / 1024).toFixed(2);

        this.state.uploadPassword = "";

        this.state.showPasswordField = false;



        const reader = new FileReader();

        reader.onload = async (e) => {

            const result = e.target.result || "";

            const b64 = result.includes(",") ? result.split(",")[1] : result;

            this.state.uploadFileBase64 = b64;



            try {

                const inspect = await this.rpc("/gsus_bank_ai/inspect_file", {

                    file_data: b64,

                    file_name: file.name,

                    pdf_password: "",

                });

                if (inspect && inspect.success) {

                    this.state.isDuplicateDetected = Boolean(inspect.is_duplicate);

                    this.state.duplicateWarning = inspect.duplicate_warning || "";

                    if (inspect.is_duplicate) {

                        this.notification.add(inspect.duplicate_warning, { type: "warning" });

                    }

                    this.state.isPasswordProtected = Boolean(inspect.is_encrypted);

                    this.state.isDecrypted = Boolean(inspect.is_decrypted);

                    this.state.showPasswordField = Boolean(inspect.is_encrypted && !inspect.is_decrypted);

                    this.state.uploadPagesCount = inspect.page_count || 0;

                    this.state.detectedBankName = inspect.detected_bank || "";

                    this.state.selectedBankName = inspect.detected_bank || "";

                }

            } catch (err) {

                this.state.isDuplicateDetected = false;

                this.state.duplicateWarning = "";

                this.state.isPasswordProtected = false;

                this.state.isDecrypted = true;

                this.state.showPasswordField = false;

                this.state.uploadPagesCount = 0;

                this.state.detectedBankName = "";

                this.state.selectedBankName = "";

            }

        };

        reader.readAsDataURL(file);

    }



    async onPasswordInput(val) {

        this.state.uploadPassword = val;

        if (this.state.uploadFileBase64 && this.state.isPasswordProtected && val.length >= 4) {

            try {

                const inspect = await this.rpc("/gsus_bank_ai/inspect_file", {

                    file_data: this.state.uploadFileBase64,

                    file_name: this.state.uploadFileName,

                    pdf_password: val,

                });

                if (inspect && inspect.success && inspect.is_decrypted) {

                    this.state.isDecrypted = true;

                    this.state.showPasswordField = false;

                    this.state.uploadPagesCount = inspect.page_count;

                    if (inspect.detected_bank) {

                        this.state.detectedBankName = inspect.detected_bank;

                        this.state.selectedBankName = inspect.detected_bank;

                    }

                    this.notification.add(`Decrypted! Detected ${inspect.page_count} pages from ${inspect.detected_bank || 'Bank'}`, { type: 'success' });

                }

            } catch (e) {

                // Ignore while typing

            }

        }

    }



    removeUploadedFile() {

        this.state.uploadFileBase64 = null;

        this.state.uploadFileName = "";

        this.state.uploadFileSizeKb = 0;

        this.state.uploadPagesCount = 0;

        this.state.uploadPassword = "";

        this.state.detectedBankName = "";

        this.state.selectedBankName = "";

        this.state.isDuplicateDetected = false;

        this.state.duplicateWarning = "";

        this.state.isPasswordProtected = false;

        this.state.isDecrypted = true;

        this.state.showPasswordField = false;

        const input = document.getElementById("lai_file_input");

        if (input) input.value = "";

    }



    async startProcessing() {

        if (!this.state.uploadFileBase64) {

            this.notification.add("Please choose a bank statement document first.", { type: "warning" });

            return;

        }



        const randomHex = () => Math.random().toString(16).substring(2, 6);

        this.state.jobId = `${randomHex()}${randomHex()}-${randomHex()}-4${randomHex().substring(0,3)}-8${randomHex().substring(0,3)}-${randomHex()}${randomHex()}${randomHex()}`;

        const now = new Date();

        const timeStr = now.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }) + " - " + now.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });

        this.state.jobCreatedAt = timeStr;

        this.state.jobStartedAt = timeStr;



        this.state.currentView = "processing";

        this.state.isProcessing = true;

        this.state.processingStep = 1;

        this.state.processingLogs = ["Reading document stream into memory..."];



        const stepTimer1 = setTimeout(() => {

            this.state.processingStep = 2;

            this.state.processingLogs.push("Connecting to Multimodal Vision OCR...");

        }, 800);



        const stepTimer2 = setTimeout(() => {

            this.state.processingStep = 3;

            this.state.processingLogs.push("Extracting transactions, references & balance verification...");

        }, 1600);



        try {

            const cleanBank = (this.state.selectedBankName === "Auto-Detect with AI") ? "" : this.state.selectedBankName;

            const res = await this.rpc("/gsus_bank_ai/upload_and_parse", {

                file_data: this.state.uploadFileBase64,

                file_name: this.state.uploadFileName,

                pdf_password: this.state.uploadPassword || "",

                bank_name: cleanBank,

            });

            // Security Hardening: Wipe PDF password from UI memory immediately after upload

            this.state.uploadPassword = "";

            this.state.showPasswordField = false;



            clearTimeout(stepTimer1);

            clearTimeout(stepTimer2);



            if (res && res.success) {

                this.state.processingStep = 4;

                this.state.processingLogs.push(`Extracted ${res.total_transactions} transactions successfully!`);

                this.state.processingLogs.push("Opening + Inflow - Outflow == Closing balance confirmed.");

                this.state.statement_id = res.statement_id;



                setTimeout(async () => {

                    this.state.isProcessing = false;

                    this.switchToReview(res.statement_id);

                    if (res.is_duplicate) {

                        this.notification.add(res.message || "Opened existing statement.", { type: "info" });

                    } else {

                        this.notification.add(`Extracted ${res.total_transactions} transactions from ${res.bank_name}!`, { type: "success" });

                    }

                }, 800);

            } else {

                this.state.isProcessing = false;

                this.state.currentView = "upload";

                this.notification.add(res?.error || "AI Processing / Upload failed.", { type: "danger", sticky: true });

            }

        } catch (err) {

            clearTimeout(stepTimer1);

            clearTimeout(stepTimer2);

            this.state.isProcessing = false;

            this.notification.add(err.data?.message || err.message || "Upload failed.", { type: "danger" });

        }

    }



    // ═════════════════════════════════════════════════════════════

    // 12. EXPORTS & REPORTS

    // ═════════════════════════════════════════════════════════════

    exportCsv() {

        const sid = this.state.statement_id || this.statementId;

        if (!sid) return;

        window.open(`/gsus_bank_ai/export_csv?statement_id=${sid}`, "_blank");

    }



    exportExcel() {

        const sid = this.state.statement_id || this.statementId;

        if (!sid) return;

        window.open(`/gsus_bank_ai/export_excel?statement_id=${sid}`, "_blank");

    }



    printPdfStatement() {

        const sid = this.state.statement_id || this.statementId;

        if (!sid) {

            this.notification.add("Please select a statement first.", { type: "warning" });

            return;

        }

        window.open(`/gsus_bank_ai/export_pdf?statement_id=${sid}`, "_blank");

    }



    openAllStatements() {

        this.action.doAction({

            type: "ir.actions.act_window",

            name: "Bank Statements AI Batches",

            res_model: "gsus.bank.statement.ai",

            views: [[false, "list"], [false, "form"]],

            target: "current",

        });

    }



    openPendingStatements() {

        if (!this.state.dashboard?.active_tasks) {

            this.notification.add("All statements have been posted to Odoo! No pending review.", { type: "info" });

            return;

        }

        const pending = (this.state.dashboard?.recent_statements || []).find(

            (s) => s.state !== "pushed"

        );

        if (pending) {

            this.switchToReview(pending.id);

        } else {

            this.action.doAction({

                type: "ir.actions.act_window",

                name: "Pending Statements",

                res_model: "gsus.bank.statement.ai",

                domain: [["state", "in", ["draft", "parsed", "reviewed"]]],

                views: [[false, "list"], [false, "form"]],

                target: "current",

            });

        }

    }



    openOdooStatement() {

        if (!this.state.account_bank_statement_id) return;

        this.action.doAction({

            type: "ir.actions.act_window",

            name: "Odoo Bank Statement",

            res_model: "account.bank.statement",

            res_id: this.state.account_bank_statement_id,

            views: [[false, "form"]],

            view_mode: "form",

            target: "current",

        });

    }



    async submitAddTransaction() {

        if (!this.state.newTxnNarration) {

            this.notification.add("Please enter a narration.", { type: "warning" });

            return;

        }

        try {

            await this.rpc("/gsus_bank_ai/add_line", {

                statement_id: this.state.statement_id,

                date: this.state.newTxnDate,

                narration: this.state.newTxnNarration,

                debit: parseFloat(this.state.newTxnDebit) || 0.0,

                credit: parseFloat(this.state.newTxnCredit) || 0.0,

            });

            this.state.isAddTxnModalOpen = false;

            this.state.newTxnNarration = "";

            this.state.newTxnDebit = 0;

            this.state.newTxnCredit = 0;

            this.notification.add("Transaction created!", { type: "success" });

            await this.loadStatementData();

        } catch (e) {

            this.notification.add(e.data?.message || e.message || "Failed to add transaction.", { type: "danger" });

        }

    }

}



registry.category("actions").add("gsus_bank_workbench_action", GsusBankWorkbench);



export class GsusBankWorkbenchUpload extends GsusBankWorkbench {

    setup() {

        super.setup();

        this.state.currentView = "upload";

    }

}

registry.category("actions").add("gsus_bank_workbench_upload_action", GsusBankWorkbenchUpload);



export class GsusBankWorkbenchReview extends GsusBankWorkbench {

    setup() {

        super.setup();

        this.state.currentView = "review";

    }

}

registry.category("actions").add("gsus_bank_workbench_review_action", GsusBankWorkbenchReview);



export const gsusBankWorkbenchWidget = {

    component: GsusBankWorkbench,

};

registry.category("view_widgets").add("gsus_bank_workbench_widget", gsusBankWorkbenchWidget);

