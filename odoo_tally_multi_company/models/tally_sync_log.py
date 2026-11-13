# -*- coding: utf-8 -*-
from odoo import fields, models


class TallySyncLog(models.Model):
    _inherit = "tally.sync.log"

    tally_company_id = fields.Many2one(
        "tally.company",
        string="Tally Company",
        index=True,
        help="The Tally company to which this sync request was dispatched.",
    )


class TallyGstSyncLog(models.Model):
    _inherit = "tally.gst.sync.log"

    tally_company_id = fields.Many2one(
        "tally.company",
        string="Tally Company",
        index=True,
        help="The Tally company associated with this GST sync log.",
    )
