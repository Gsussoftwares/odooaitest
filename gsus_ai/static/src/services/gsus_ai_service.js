/** @odoo-module **/

import { proxy } from "@odoo/owl";
import { registry } from "@web/core/registry";

export const gsusAiService = {
    name: "gsusAi",
    start() {
        const state = proxy({
            isOpen: false,
        });

        return {
            open() {
                state.isOpen = true;
            },
            close() {
                state.isOpen = false;
            },
            toggle() {
                state.isOpen = !state.isOpen;
            },
            get isOpen() {
                return state.isOpen;
            },
            state,
        };
    },
};

registry.category("services").add("gsusAi", gsusAiService);
