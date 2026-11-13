from odoo import _, fields, models
from odoo.exceptions import UserError

from odoo.addons.odoo_tally_connector.utils import tally_http, xml_builder


class TallyProductCategoryMap(models.Model):
    _name = 'tally.product.category.map'
    _description = 'Tally Product Category Mapping'
    _rec_name = 'category_id'
    _order = 'category_id'

    category_id = fields.Many2one(
        'product.category',
        string='Odoo Product Category',
        required=True,
        index=True,
        ondelete='cascade',
    )
    tally_stock_group_name = fields.Char(
        string='Tally Stock Group',
        required=True,
        help='Exact Tally Stock Group used in the Stock Item "Under" field.',
    )
    tally_parent_stock_group_name = fields.Char(
        string='Tally Parent Stock Group',
        help='Optional parent for this Tally Stock Group. Leave empty for a root group.',
    )
    active = fields.Boolean(default=True)

    _category_unique = models.Constraint(
        'UNIQUE(category_id)',
        'An Odoo Product Category can only have one Tally Stock Group mapping.',
    )

    def action_sync_to_tally_stock_group(self):
        ICP = self.env['ir.config_parameter'].sudo()
        company_name = (ICP.get_param('tally_connector.company_name') or '').strip()
        url = (ICP.get_param('tally_connector.server_url') or 'http://localhost:9000').strip()
        if not company_name:
            raise UserError(_('Configure the Tally Company Name before syncing stock groups.'))
        for mapping in self:
            xml_str = xml_builder.build_stock_group_xml(
                mapping.tally_stock_group_name,
                company_name,
                parent_name=mapping.tally_parent_stock_group_name,
            )
            success, _response, _guid, error = tally_http.post_to_tally(xml_str, url)
            if not success and not tally_http.is_likely_duplicate_master_error(error):
                raise UserError(
                    _('Could not sync Tally Stock Group "%s": %s')
                    % (mapping.tally_stock_group_name, error)
                )
        return True
