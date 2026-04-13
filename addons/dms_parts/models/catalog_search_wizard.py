from odoo import api, models, fields


class DmsPartCatalogSearchWizard(models.TransientModel):
    """零件目錄搜尋精靈：依引擎號碼或車型查詢對應目錄"""
    _name = 'dms.part.catalog.search.wizard'
    _description = '零件目錄搜尋'

    engine_number = fields.Char(
        string='引擎號碼',
        help='輸入引擎號碼，系統自動比對前綴找到對應目錄',
    )
    template_id = fields.Many2one(
        'dms.product.template',
        string='車型',
        help='直接選擇車型',
    )
    section_category = fields.Selection(
        [('all', '全部'), ('engine', '引擎'), ('frame', '車架')],
        string='部位',
        default='all',
    )

    def action_search(self):
        self.ensure_one()
        domain = [('active', '=', True)]

        if self.engine_number and self.engine_number.strip():
            engine_no = self.engine_number.strip().upper()
            # 找到前綴符合的目錄
            catalogs = self.env['dms.part.catalog'].search([('active', '=', True)])
            matched_ids = [
                c.id for c in catalogs
                if c.engine_prefix and engine_no.startswith(c.engine_prefix.upper())
            ]
            if matched_ids:
                domain += [('catalog_id', 'in', matched_ids)]
            else:
                # 無符合前綴，回傳空結果並提示
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': '查無目錄',
                        'message': f'找不到引擎號碼 {engine_no} 對應的車型目錄，請確認引擎號碼或改用車型選單查詢。',
                        'type': 'warning',
                        'sticky': False,
                    },
                }
        elif self.template_id:
            catalog_ids = self.env['dms.part.catalog'].search(
                [('template_id', '=', self.template_id.id), ('active', '=', True)]
            ).ids
            if catalog_ids:
                domain += [('catalog_id', 'in', catalog_ids)]
            else:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': '查無目錄',
                        'message': f'車型「{self.template_id.display_name}」尚未建立零件目錄。',
                        'type': 'warning',
                        'sticky': False,
                    },
                }

        if self.section_category and self.section_category != 'all':
            domain += [('category', '=', self.section_category)]

        return {
            'name': '零件目錄分區',
            'type': 'ir.actions.act_window',
            'res_model': 'dms.part.catalog.section',
            'view_mode': 'kanban,tree,form',
            'domain': domain,
            'context': {'search_default_group_catalog': 1},
        }
