from odoo import _, fields, models
from odoo.exceptions import UserError

from odoo.addons.odoo_tally_connector.utils import tally_http, xml_builder


class ProductCategory(models.Model):
    _inherit = 'product.category'

    tally_stock_group_name = fields.Char(
        string='Tally Stock Group',
        help='Exact Tally Stock Group used in the Stock Item "Under" field.',
    )
    tally_parent_stock_group_name = fields.Char(
        string='Tally Parent Stock Group',
        help='Optional parent for this Tally Stock Group. Leave empty for a root group.',
    )

    def action_sync_to_tally_stock_group(self):
        ICP = self.env['ir.config_parameter'].sudo()
        company_name = (ICP.get_param('tally_connector.company_name') or '').strip()
        url = (ICP.get_param('tally_connector.server_url') or 'http://localhost:9000').strip()
        if not company_name:
            raise UserError(_('Configure the Tally Company Name before syncing stock groups.'))

        for category in self:
            group_name = (category.tally_stock_group_name or '').strip()
            if not group_name:
                raise UserError(
                    _('Set a Tally Stock Group on product category "%s".') % category.display_name
                )
            xml_str = xml_builder.build_stock_group_xml(
                group_name,
                company_name,
                parent_name=category.tally_parent_stock_group_name,
            )
            success, _response, _guid, error = tally_http.post_to_tally(xml_str, url)
            if not success and not tally_http.is_likely_duplicate_master_error(error):
                raise UserError(_('Could not sync Tally Stock Group "%s": %s') % (group_name, error))
        return True
