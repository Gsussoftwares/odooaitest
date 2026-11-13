/** @odoo-module **/

import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class SystrayAIEngine extends Component {
    static template = "gsus_bank_ai.SystrayAIEngine";

    setup() {
        this.action = useService("action");
    }

    async onClick() {
        await this.action.doAction("gsus_bank_ai_bridge.action_gsus_bank_ai_provider");
    }
}

export const systrayAIEngineItem = {
    Component: SystrayAIEngine,
};

registry.category("systray").add("gsus_bank_ai.SystrayAIEngine", systrayAIEngineItem, { sequence: 40 });
