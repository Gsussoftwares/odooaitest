# -*- coding: utf-8 -*-
"""Module install / upgrade hooks."""


def post_init_hook(env):
    """Disable Tally auto-sync for payments that existed before this feature."""
    ICP = env['ir.config_parameter'].sudo()
    flag = 'tally_connector.payment_auto_sync_initialized'
    if ICP.get_param(flag):
        return
    env['account.payment'].search([]).write({'tally_auto_sync_on_post': False})
    ICP.set_param(flag, 'True')
