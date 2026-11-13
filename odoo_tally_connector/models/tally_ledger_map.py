from odoo import api, fields, models

_PARTY_ACCOUNT_TYPES = ('asset_receivable', 'liability_payable')
_DEFAULT_TALLY_GROUPS = {
    'asset_receivable': 'Sundry Debtors',
    'liability_payable': 'Sundry Creditors',
    'income': 'Sales Accounts',
    'income_other': 'Direct Incomes',
    'expense': 'Purchase Accounts',
    'expense_direct_cost': 'Direct Expenses',
}


class TallyLedgerMap(models.Model):
    """
    Maps an Odoo GL account to a named Tally Prime Ledger.

    Every account used on an invoice/bill line MUST have a mapping here
    before the sync can proceed. Missing mappings will block the sync
    with a clear, actionable error message.
    """
    _name = 'tally.ledger.map'
    _description = 'Tally Ledger Mapping'
    _rec_name = 'tally_ledger_name'
    _order = 'account_id'

    account_id = fields.Many2one(
        comodel_name='account.account',
        string='Odoo Account',
        required=True,
        index=True,
        help='The Odoo GL account to be mapped to a Tally ledger.',
    )
    account_code = fields.Char(
        related='account_id.code',
        string='Account Code',
        store=True,
        readonly=True,
    )
    tally_ledger_name = fields.Char(
        string='Tally Ledger Name',
        required=True,
        help=(
            'The exact name of the Ledger in Tally Prime (case-sensitive). '
            'Example: "Debtors", "Creditors", "Output GST @ 18%".'
        ),
    )
    tally_group = fields.Char(
        string='Tally Group',
        help=(
            'Tally Group for this ledger (used when auto-creating the ledger in Tally). '
            'Example: "Sundry Debtors", "Sundry Creditors", "Duties & Taxes".'
        ),
    )
    is_party_account = fields.Boolean(
        string='Is Party Account?',
        default=False,
        help=(
            'Mark this if the account represents a receivable/payable (AR/AP). '
            'The partner name will be used as the ledger name instead of the mapped name.'
        ),
    )
    active = fields.Boolean(default=True)

    _sql_constraints = [
        (
            'account_unique',
            'UNIQUE(account_id)',
            'An Odoo account can only be mapped to one Tally Ledger.',
        ),
    ]

    def _vals_from_account(self, account, vals=None):
        """Fill party flag and Tally group from the Odoo account type."""
        vals = dict(vals or {})
        if not account:
            return vals
        acc_type = account.account_type
        if acc_type in _PARTY_ACCOUNT_TYPES:
            vals['is_party_account'] = True
        if not vals.get('tally_group'):
            name = (vals.get('tally_ledger_name') or '').upper()
            if any(tag in name for tag in ('CGST', 'SGST', 'IGST', 'GST')):
                vals['tally_group'] = 'Duties & Taxes'
            elif acc_type in _DEFAULT_TALLY_GROUPS:
                vals['tally_group'] = _DEFAULT_TALLY_GROUPS[acc_type]
        return vals

    @api.onchange('account_id')
    def _onchange_account_id_tally_defaults(self):
        for rec in self:
            if not rec.account_id:
                continue
            defaults = rec._vals_from_account(rec.account_id, {
                'tally_ledger_name': rec.tally_ledger_name,
                'tally_group': rec.tally_group,
            })
            rec.is_party_account = defaults.get('is_party_account', rec.is_party_account)
            if defaults.get('tally_group') and not rec.tally_group:
                rec.tally_group = defaults['tally_group']

    @api.model_create_multi
    def create(self, vals_list):
        Account = self.env['account.account']
        prepared = []
        for vals in vals_list:
            account = Account.browse(vals['account_id']) if vals.get('account_id') else Account.browse()
            prepared.append(self._vals_from_account(account, vals))
        return super().create(prepared)

    def write(self, vals):
        if 'account_id' in vals or 'tally_ledger_name' in vals:
            for rec in self:
                account = (
                    self.env['account.account'].browse(vals['account_id'])
                    if vals.get('account_id') else rec.account_id
                )
                merged = dict(vals)
                if 'tally_ledger_name' not in merged:
                    merged['tally_ledger_name'] = rec.tally_ledger_name
                if 'tally_group' not in merged:
                    merged['tally_group'] = rec.tally_group
                super(TallyLedgerMap, rec).write(rec._vals_from_account(account, merged))
            return True
        return super().write(vals)

    @api.depends('account_id', 'tally_ledger_name')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = (
                f'{rec.account_id.code} — {rec.tally_ledger_name}'
                if rec.account_id else rec.tally_ledger_name or '/'
            )
