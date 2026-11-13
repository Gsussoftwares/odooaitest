from odoo import api, fields, models
from odoo.exceptions import UserError


class TallySyncLog(models.Model):
    """
    Audit log for every Tally sync attempt.

    Records the full Request XML, Response XML, parsed status and any
    error messages. Used for debugging and retry decisions.
    """
    _name = 'tally.sync.log'
    _description = 'Tally Sync Log'
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
        help='Stored separately so logs remain readable even if the move is deleted.',
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
    tally_guid = fields.Char(
        string='Tally GUID',
        readonly=True,
        help='The unique identifier returned by Tally on successful import.',
    )
    request_xml = fields.Text(
        string='Request XML (Sent to Tally)',
        readonly=True,
    )
    response_xml = fields.Text(
        string='Response XML (Received from Tally)',
        readonly=True,
    )
    error_message = fields.Text(
        string='Error / Notes',
        readonly=True,
        help='Parsed error detail from Tally response, or skip reason.',
    )
    tally_server_url = fields.Char(
        string='Tally URL Used',
        readonly=True,
    )

    def action_retry_sync(self):
        """Re-trigger sync for the linked document."""
        self.ensure_one()
        if not self.move_id:
            raise UserError(
                'This log entry is not linked to an invoice or bill. '
                'Open the document from Accounting and use “Sync to Tally” there.'
            )
        self.move_id.action_sync_to_tally()
        return {'type': 'ir.actions.act_window_close'}
