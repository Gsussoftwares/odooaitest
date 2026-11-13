# -*- coding: utf-8 -*-
"""Audit log for e-Invoice / e-Way Bill pushes to Tally."""

from odoo import api, fields, models
from odoo.exceptions import UserError


class TallyGstSyncLog(models.Model):
    """E-Invoice / e-Way Bill Tally sync log."""

    _name = 'tally.gst.sync.log'
    _description = 'Tally E-Invoice / E-Way Bill Sync Log'
    _rec_name = 'move_name'
    _order = 'sync_date desc'

    move_id = fields.Many2one(
        comodel_name='account.move',
        string='Source Document',
        ondelete='set null',
        index=True,
        readonly=True,
    )
    move_name = fields.Char(
        string='Document Number',
        readonly=True,
    )
    partner_id = fields.Many2one(
        comodel_name='res.partner',
        string='Partner',
        compute='_compute_partner_id',
        store=True,
        readonly=True,
    )

    @api.depends('move_id')
    def _compute_partner_id(self):
        for log in self:
            log.partner_id = log.move_id.partner_id if log.move_id else False

    sync_date = fields.Datetime(
        string='Sync Date/Time',
        default=fields.Datetime.now,
        readonly=True,
        index=True,
    )
    status = fields.Selection(
        selection=[
            ('success', 'Success'),
            ('failed', 'Failed'),
            ('skipped', 'Skipped'),
        ],
        string='Status',
        required=True,
        readonly=True,
        index=True,
    )
    irn = fields.Char(string='IRN', readonly=True)
    irn_ack_no = fields.Char(string='IRN Ack No.', readonly=True)
    ewaybill_no = fields.Char(string='E-Way Bill No.', readonly=True)
    ewaybill_date = fields.Char(string='E-Way Bill Date', readonly=True)
    dispatch_from = fields.Char(string='Dispatch From', readonly=True)
    ship_to = fields.Char(string='Ship To', readonly=True)
    transporter_id = fields.Char(string='Transporter GSTIN', readonly=True)
    transporter_name = fields.Char(string='Transporter Name', readonly=True)
    transport_mode = fields.Char(string='Transport Mode', readonly=True)
    vehicle_no = fields.Char(string='Vehicle No.', readonly=True)
    vehicle_type = fields.Char(string='Vehicle Type', readonly=True)
    transport_doc_no = fields.Char(string='Transporter Doc No.', readonly=True)
    transport_doc_date = fields.Char(string='Transporter Doc Date', readonly=True)
    distance = fields.Char(string='Distance (km)', readonly=True)
    einvoice_sent = fields.Boolean(string='E-Invoice Sent', readonly=True)
    ewaybill_sent = fields.Boolean(string='E-Way Bill Sent', readonly=True)
    tally_guid = fields.Char(string='Tally GUID', readonly=True)
    request_xml = fields.Text(string='Request XML (Sent to Tally)', readonly=True)
    response_xml = fields.Text(string='Response XML (Received from Tally)', readonly=True)
    error_message = fields.Text(string='Error / Notes', readonly=True)
    tally_server_url = fields.Char(string='Tally URL Used', readonly=True)

    def action_retry_gst_sync(self):
        """Re-trigger e-Invoice / e-Way Bill sync for the linked document."""
        self.ensure_one()
        if not self.move_id:
            raise UserError(
                'This log is not linked to an invoice. '
                'Open the invoice and use “Sync E-Invoice / E-Way Bill to Tally”.'
            )
        self.move_id.action_sync_gst_to_tally()
        return {'type': 'ir.actions.act_window_close'}
