from . import models


def post_init_hook(cr, registry):
    """安裝後立即全量同步所有 um 群組成員的 Odoo 原生群組。"""
    from odoo import api, SUPERUSER_ID
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['res.users'].search([('um_group_ids', '!=', False)])._sync_um_odoo_groups()


def post_migrate_hook(cr, registry):
    """每次 --update 後重新全量同步（處理菜單群組設定變更）。"""
    post_init_hook(cr, registry)
