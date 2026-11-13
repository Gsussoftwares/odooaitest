from odoo import fields, models
from odoo.exceptions import UserError


class AccountPayment(models.Model):
    _inherit = 'account.payment'

    tally_sync_status = fields.Selection(related='move_id.tally_sync_status', readonly=True)
    tally_guid = fields.Char(related='move_id.tally_guid', readonly=True)
    tally_last_sync = fields.Datetime(related='move_id.tally_last_sync', readonly=True)
    tally_sync_log_count = fields.Integer(related='move_id.tally_sync_log_count', readonly=True)

    def action_sync_to_tally(self):
        """Push payment to Tally only when this button is used (no auto-sync on post)."""
        for payment in self:
            if not payment.move_id:
                raise UserError(
                    'This payment has no journal entry yet. Validate the payment first, '
                    'then use Sync to Tally.'
                )
            if payment.move_id.state != 'posted':
                raise UserError('Only posted payments can be synced to Tally.')
            payment.move_id.action_sync_to_tally()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Tally Payment Sync',
                'message': f'Sync completed for {len(self)} payment(s). Check Tally Logs for details.',
                'type': 'info',
                'sticky': False,
            },
        }

    def action_view_tally_logs(self):
        self.ensure_one()
        if not self.move_id:
            raise UserError('This payment has no posted journal entry.')
        return self.move_id.action_view_tally_logs()
