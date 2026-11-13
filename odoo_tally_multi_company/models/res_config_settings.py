# -*- coding: utf-8 -*-
from odoo import _, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    def action_open_tally_companies(self):
        """Open the Tally Companies management view."""
        return {
            "name": _("Tally Prime Companies"),
            "type": "ir.actions.act_window",
            "res_model": "tally.company",
            "view_mode": "list,form",
            "target": "current",
        }
