from odoo import api, models, fields


class DmsPart(models.Model):
    """零件清單：供傭金折換實物使用，並連結庫存與目錄圖"""
    _name = 'dms.part'
    _description = '零件'
    _rec_name = 'name'
    _order = 'category_id, name'

    name = fields.Char(string='零件名稱', required=True)
    part_number = fields.Char(string='料號', help='原廠料號 / 內部編號')
    category_id = fields.Many2one(
        'dms.part.category', string='分類', ondelete='restrict')
    part_type = fields.Selection(
        [
            ('vehicle_part', '車輛結構零件'),
            ('consumable', '耗材'),
            ('accessory', '精品/副廠配件'),
        ],
        string='零件類型',
        default='vehicle_part',
        required=True,
        help='車輛結構零件：組裝於車體（活塞、煞車墊片等）；耗材：定期更換消耗品（機油、輪胎等）；精品/副廠配件：加裝改裝用途',
    )
    uom = fields.Char(string='單位', default='個', help='瓶、個、組⋯')
    cost_price = fields.Float(
        string='進貨成本', digits=(12, 0),
        help='每單位進貨成本（TWD），用於傭金折換時的成本估算')
    list_price = fields.Float(
        string='公告售價', digits=(12, 0),
        help='建議售價，顯示於零件目錄查詢')
    product_id = fields.Many2one(
        'product.product',
        string='庫存商品',
        ondelete='set null',
        help='對應 Odoo 庫存商品，建立後自動連結；用於庫存查詢與出入庫',
    )
    qty_available = fields.Float(
        string='現有庫存',
        compute='_compute_qty_available',
        digits=(12, 0),
        help='從庫存商品即時取得現有數量',
    )
    superseded_by_id = fields.Many2one(
        'dms.part',
        string='替代料號',
        ondelete='set null',
        help='此料號已停產，由指定料號取代',
    )
    active = fields.Boolean(string='啟用', default=True)
    note = fields.Text(string='備註')

    @api.depends('product_id')
    def _compute_qty_available(self):
        for rec in self:
            rec.qty_available = rec.product_id.qty_available if rec.product_id else 0.0

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            if not rec.product_id:
                rec._auto_create_product()
        return records

    def _auto_create_product(self):
        """自動建立對應的 product.product 供庫存追蹤"""
        self.ensure_one()
        uom = self.env.ref('uom.product_uom_unit', raise_if_not_found=False)
        product = self.env['product.product'].create({
            'name': self.name,
            'default_code': self.part_number or False,
            'type': 'product',
            'uom_id': uom.id if uom else False,
            'uom_po_id': uom.id if uom else False,
            'standard_price': self.cost_price,
            'lst_price': self.list_price,
            'sale_ok': False,
            'purchase_ok': False,
        })
        self.product_id = product
