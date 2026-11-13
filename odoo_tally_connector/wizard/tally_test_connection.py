from odoo import fields, models
from odoo.addons.odoo_tally_connector.utils import tally_http


class TallyTestConnection(models.TransientModel):
    """
    Transient wizard to test Tally Prime connectivity from the UI.
    Can be opened standalone from the Tally Connector menu.
    """
    _name = 'tally.test.connection'
    _description = 'Test Tally Connection'

    server_url = fields.Char(
        string='Tally Server URL',
        default=lambda self: self.env['ir.config_parameter'].sudo().get_param(
            'tally_connector.server_url', 'http://localhost:9000'
        ),
        required=True,
    )
    result_status = fields.Selection(
        selection=[('pending', 'Not Tested'), ('ok', 'Connected'), ('fail', 'Failed')],
        string='Status',
        default='pending',
        readonly=True,
    )
    result_message = fields.Text(string='Result', readonly=True)

    def action_test(self):
        """Run the connection test and update the result fields."""
        self.ensure_one()
        success, message = tally_http.test_connection(self.server_url)
        self.result_status = 'ok' if success else 'fail'
        self.result_message = message
        # Return the same wizard view so user sees result without closing
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'tally.test.connection',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
