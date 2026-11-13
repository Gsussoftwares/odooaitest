from odoo import fields, models


class TallyHsnDescriptionMap(models.Model):
    """Map Odoo HSN/SAC codes to Tally stock item HSN description."""

    _name = 'tally.hsn.description.map'
    _description = 'Tally HSN Description Mapping'
    _rec_name = 'hsn_code'
    _order = 'hsn_code'

    hsn_code = fields.Char(
        string='HSN/SAC Code',
        required=True,
        index=True,
        help='Odoo product HSN/SAC code (l10n_in_hsn_code).',
    )
    tally_hsn_description = fields.Char(
        string='Tally HSN Description',
        required=True,
        help='Text sent to Tally Stock Item → Statutory Details → HSN/SAC Description.',
    )
    active = fields.Boolean(default=True)

    _hsn_code_unique = models.Constraint(
        'UNIQUE(hsn_code)',
        'Each HSN/SAC code can only have one Tally description mapping.',
    )
