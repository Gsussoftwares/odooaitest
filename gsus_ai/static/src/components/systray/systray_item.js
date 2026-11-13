/** @odoo-module **/

import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

/**
 * GSUS AI Systray Item
 * Replaces the built-in Odoo ai.systray_action with our branded
 * gradient icon that opens the GSUS AI Chat Panel.
 */
export class GsusAiSystrayItem extends Component {
    static template = "gsus_ai.SystrayItem";

    setup() {
        this.gsusAi = useService("gsusAi");
    }

    onClickOpenAI() {
        this.gsusAi.toggle();
    }
}

// Override the built-in Odoo AI systray with our branded component.
// Using force:true replaces it under the same key — no duplicate, no remove needed.
registry.category("systray").add(
    "ai.systray_action",
    { Component: GsusAiSystrayItem },
    { force: true, sequence: 30 }
);

