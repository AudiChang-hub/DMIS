from odoo import api, fields, models
from odoo.exceptions import ValidationError


class VisitItem(models.Model):
    _name = 'dms.visit.item'
    _description = '拜訪送出物品'
    _order = 'id'

    visit_id = fields.Many2one(
        'dms.visit', string='拜訪紀錄',
        required=True, ondelete='cascade', index=True,
    )
    item_name = fields.Char(string='送出物品')
    product_id = fields.Many2one(
        'dms.product', string='產品',
        ondelete='set null',
        help='歷史相容欄位；本輪主要以送出物品文字記錄為主。',
    )
    quantity = fields.Float(string='數量', default=1.0)
    note = fields.Text(string='備註')

    @api.constrains('item_name', 'product_id')
    def _check_item_reference(self):
        for record in self:
            if not record.item_name and not record.product_id:
                raise ValidationError('送出物品至少需要填寫物品名稱或選擇歷史產品。')

    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id and not self.item_name:
            self.item_name = self.product_id.display_name or self.product_id.name

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('product_id') and not vals.get('item_name'):
                product = self.env['dms.product'].browse(vals['product_id'])
                vals['item_name'] = product.display_name or product.name
        return super().create(vals_list)

    def init(self):
        self._cr.execute(
            """
            UPDATE dms_visit_item item
               SET item_name = product.name
              FROM dms_product product
             WHERE item.product_id = product.id
               AND (item.item_name IS NULL OR item.item_name = '')
            """
        )
