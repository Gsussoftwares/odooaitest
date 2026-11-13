/** @odoo-module **/

import { Component, proxy } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { cookie } from "@web/core/browser/cookie";
import { GsusAiChatPanel } from "../chat_panel/chat_panel";

export class GsusAiFloatingPanel extends Component {
    static template = "gsus_ai.FloatingPanel";
    static components = { GsusAiChatPanel };

    setup() {
        this.gsusAiService = useService("gsusAi");
        this.actionService = useService("action");
        this.state = proxy({
            showResumeBanner: true,
            isMinimized: false,
        });
    }

    get isDarkMode() {
        return cookie.get("color_scheme") === "dark" || document.documentElement.dataset.bsTheme === "dark" || document.body.classList.contains("o_dark_mode");
    }

    toggleMinimize() {
        this.state.isMinimized = !this.state.isMinimized;
    }

    dismissBanner() {
        this.state.showResumeBanner = false;
    }

    resumePreviousChat() {
        this.state.showResumeBanner = false;
        document.dispatchEvent(new CustomEvent("o-gsus-ai-resume-prev"));
    }

    toggleHistoryDrawer() {
        document.dispatchEvent(new CustomEvent("o-gsus-ai-toggle-sidebar"));
    }

    openFullScreen() {
        this.gsusAiService.close();
        this.actionService.doAction("gsus_ai.action_gsus_ai_chat_panel");
    }
}

registry.category("main_components").add("GsusAiFloatingPanel", {
    Component: GsusAiFloatingPanel,
    props: {},
});
