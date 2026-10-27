from odoo import SUPERUSER_ID, api


def post_init_hook(cr, registry):
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['dms.product']._run_product_backfill()
    env['dms.price.version']._run_legacy_backfill()
    env['dms.installment.rule']._run_legacy_backfill()
