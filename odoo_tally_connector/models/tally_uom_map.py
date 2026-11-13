from odoo import fields, models


class TallyUomMap(models.Model):
    """
    Maps an Odoo Unit of Measure (uom.uom) to a Tally Prime unit symbol.

    This is critical for Odoo 19's Unified UoM system. Tally stores unit
    symbols as short strings (e.g., 'Nos', 'Kg', 'Mtr') which must match
    exactly the units configured in Tally's Unit of Measure master.
    """
    _name = 'tally.uom.map'
    _description = 'Tally Unit of Measure Mapping'
    _rec_name = 'tally_symbol'
    _order = 'uom_id'

    uom_id = fields.Many2one(
        comodel_name='uom.uom',
        string='Odoo Unit of Measure',
        required=True,
        index=True,
        help='The Odoo UoM to map to a Tally symbol.',
    )
    tally_symbol = fields.Char(
        string='Tally Unit Symbol',
        required=True,
        help=(
            'Exact Tally unit symbol (case-sensitive). '
            'Examples: "Nos", "Kg", "Mtr", "Ltr", "Box", "Pcs".'
        ),
    )

    _sql_constraints = [
        (
            'uom_unique',
            'UNIQUE(uom_id)',
            'Each Odoo UoM can only be mapped to one Tally symbol.',
        ),
    ]
