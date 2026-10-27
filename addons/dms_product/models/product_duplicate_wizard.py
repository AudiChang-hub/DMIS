from odoo import fields, models


class DmsProductDuplicateWizard(models.TransientModel):
    _name = 'dms.product.duplicate.wizard'
    _description = '複製產品項確認精靈'

    source_product_id = fields.Many2one(
        'dms.product', string='來源產品項', required=True, ondelete='cascade')
    template_id = fields.Many2one(
        related='source_product_id.template_id', string='產品模板', readonly=True)
    production_year = fields.Char(string='出廠年份')
    has_conflict = fields.Boolean(string='年份衝突', default=False)
    conflict_product_name = fields.Char(string='衝突記錄', readonly=True)

    def _check_year_conflict(self):
        """回傳衝突的 dms.product 記錄，若無衝突則回傳空 recordset。"""
        self.ensure_one()
        if not self.template_id or not self.production_year:
            return self.env['dms.product'].browse()
        existing = self.env['dms.product'].with_context(active_test=False).search([
            ('template_id', '=', self.template_id.id),
            ('production_year', '=', self.production_year.strip()),
        ], limit=1)
        return existing

    def _do_duplicate(self):
        """以 skip_product_year_uniqueness 繞過唯一性限制執行複製，並開啟編輯 dialog。"""
        self.ensure_one()
        new_product = self.source_product_id.with_context(
            skip_product_year_uniqueness=True
        ).copy({
            'template_id': self.source_product_id.template_id.id,
            'production_year': self.production_year.strip() if self.production_year else False,
        })
        form_view = self.env.ref('dms_sale.view_product_form')
        return {
            'type': 'ir.actions.act_window',
            'name': f'產品項（複製自 {self.source_product_id.display_name}）',
            'res_model': 'dms.product',
            'res_id': new_product.id,
            'view_mode': 'form',
            'views': [(form_view.id, 'form')],
            'target': 'new',
        }

    def action_check_and_create(self):
        """檢查年份衝突；若有衝突則顯示警告並要求確認，否則直接複製。"""
        self.ensure_one()
        conflict = self._check_year_conflict()
        if conflict:
            self.write({
                'has_conflict': True,
                'conflict_product_name': conflict.internal_code or conflict.display_name,
            })
            form_view = self.env.ref('dms_product.view_product_duplicate_wizard_form')
            return {
                'type': 'ir.actions.act_window',
                'res_model': self._name,
                'res_id': self.id,
                'view_mode': 'form',
                'views': [(form_view.id, 'form')],
                'target': 'new',
            }
        return self._do_duplicate()

    def action_confirm_create(self):
        """使用者確認後，忽略年份重複限制直接複製。"""
        self.ensure_one()
        return self._do_duplicate()
