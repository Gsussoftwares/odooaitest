from odoo import fields, models


class TallyVoucherMap(models.Model):
    """
    Maps an Odoo journal type to a Tally Prime Voucher Type.

    Tally voucher types determine how the double-entry is presented in Tally.
    This mapping is used to pick the correct Tally voucher type when creating
    the ENVELOPE XML for a posted account.move.
    """
    _name = 'tally.voucher.map'
    _description = 'Tally Voucher Type Mapping'
    _rec_name = 'tally_voucher_type'
    _order = 'move_type'

    move_type = fields.Selection(
        selection=[
            ('out_invoice', 'Customer Invoice'),
            ('in_invoice', 'Vendor Bill'),
            ('out_refund', 'Customer Credit Note'),
            ('in_refund', 'Vendor Credit Note / Debit Note'),
            ('out_receipt', 'Customer Receipt'),
            ('in_receipt', 'Vendor Payment'),
        ],
        string='Odoo Document Type',
        required=True,
        index=True,
        help=(
            'Use Tally type **Sales** + **Invoice Voucher View** for Customer Invoice, and '
            '**Purchase** + **Invoice Voucher View** for Vendor Bill (not Purchase Order view).'
        ),
    )
    tally_voucher_type = fields.Char(
        string='Tally Voucher Type',
        required=True,
        help=(
            'Exact Tally Voucher Type name (case-sensitive). '
            'Standard Tally types: Sales, Purchase, Receipt, Payment, Credit Note, Debit Note, Journal.'
        ),
    )
    tally_persistedview = fields.Char(
        string='Tally Persisted View',
        default='Invoice Voucher View',
        help=(
            'Tally internal view name for the voucher. '
            'Examples: "Invoice Voucher View", "Accounting Voucher View".'
        ),
    )

    _sql_constraints = [
        (
            'move_type_unique',
            'UNIQUE(move_type)',
            'Each Odoo document type can only be mapped to one Tally Voucher Type.',
        ),
    ]
