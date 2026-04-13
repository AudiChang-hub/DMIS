from odoo import api, models, fields


class DmsPartCatalogLine(models.Model):
    """零件目錄明細：爆炸圖上每個零件的對應記錄"""
    _name = 'dms.part.catalog.line'
    _description = '目錄零件明細'
    _rec_name = 'name'
    _order = 'section_id, seq_no'

    section_id = fields.Many2one(
        'dms.part.catalog.section',
        string='所屬分區',
        required=True,
        ondelete='cascade',
    )
    seq_no = fields.Integer(string='序號', help='爆炸圖上的數字標記')
    part_id = fields.Many2one(
        'dms.part',
        string='零件',
        required=True,
        ondelete='restrict',
    )
    part_number = fields.Char(
        string='料號',
        compute='_compute_from_part',
        store=True,
        readonly=False,
        help='從零件主檔帶入，可於此覆寫',
    )
    name = fields.Char(
        string='零件名稱',
        compute='_compute_from_part',
        store=True,
        readonly=False,
        help='從零件主檔帶入，可於此覆寫',
    )
    qty = fields.Float(string='用量', default=1.0, digits=(12, 2))
    list_price = fields.Float(
        string='公告售價',
        compute='_compute_from_part',
        store=True,
        readonly=False,
        digits=(12, 0),
        help='從零件主檔帶入，可於此覆寫',
    )
    qty_available = fields.Float(
        string='現有庫存',
        compute='_compute_qty_available',
        digits=(12, 0),
    )
    note = fields.Char(string='備註', help='如「適用引擎號 DD000001~DD050000」')

    @api.depends('part_id')
    def _compute_from_part(self):
        for rec in self:
            if rec.part_id:
                if not rec.part_number:
                    rec.part_number = rec.part_id.part_number
                if not rec.name:
                    rec.name = rec.part_id.name
                if not rec.list_price:
                    rec.list_price = rec.part_id.list_price
            else:
                rec.part_number = False
                rec.name = False
                rec.list_price = 0.0

    @api.depends('part_id')
    def _compute_qty_available(self):
        for rec in self:
            rec.qty_available = rec.part_id.qty_available if rec.part_id else 0.0
