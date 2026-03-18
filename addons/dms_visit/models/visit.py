from odoo import models, fields, api


class Visit(models.Model):
    _name = 'dms.visit'
    _description = '拜訪紀錄'
    _order = 'visit_date desc, id desc'

    name = fields.Char(
        string='拜訪名稱',
        compute='_compute_name',
        store=True,
        readonly=False,
    )
    visit_date = fields.Datetime(
        string='拜訪日期',
        required=True,
        default=fields.Datetime.now,
    )
    dealer_id = fields.Many2one(
        'dms.dealer', string='拜訪車行',
        required=True, ondelete='restrict', index=True,
    )
    # 唯讀顯示欄位，選擇車行後自動帶出
    dealer_address = fields.Text(
        related='dealer_id.address',
        string='車行地址',
        readonly=True,
    )
    dealer_phone = fields.Char(
        related='dealer_id.phone_1',
        string='車行電話',
        readonly=True,
    )
    visitor_id = fields.Many2one(
        'res.users', string='拜訪人員',
        required=True,
        default=lambda self: self.env.user,
    )
    purpose_id = fields.Many2one(
        'dms.visit.purpose', string='拜訪目的',
        ondelete='set null',
    )
    note = fields.Text(string='備註')
    item_ids = fields.One2many(
        'dms.visit.item', 'visit_id', string='送出物品',
    )
    state = fields.Selection(
        selection=[
            ('draft', '草稿'),
            ('done', '已完成'),
            ('cancel', '已取消'),
        ],
        string='狀態',
        default='draft',
        required=True,
        index=True,
    )
    company_id = fields.Many2one(
        'res.company', string='公司',
        default=lambda self: self.env.company,
    )

    # ── computed ────────────────────────────────────────────────
    @api.depends('visit_date', 'dealer_id')
    def _compute_name(self):
        for rec in self:
            date_str = ''
            if rec.visit_date:
                local_dt = fields.Datetime.context_timestamp(rec, rec.visit_date)
                date_str = local_dt.strftime('%Y-%m-%d')
            dealer_name = rec.dealer_id.name if rec.dealer_id else ''
            if date_str or dealer_name:
                rec.name = '拜訪 %s %s' % (date_str, dealer_name)
            else:
                rec.name = '拜訪紀錄'

    # ── onchange ─────────────────────────────────────────────────
    @api.onchange('visit_date')
    def _onchange_visit_date_warning(self):
        if self.visit_date and self.visit_date < fields.Datetime.now():
            return {
                'warning': {
                    'title': '日期提醒',
                    'message': '拜訪日期早於目前時間，確認為回填歷史紀錄，儲存仍可繼續。',
                }
            }

    # ── state 流轉 ────────────────────────────────────────────────
    def action_done(self):
        self.write({'state': 'done'})

    def action_cancel(self):
        self.write({'state': 'cancel'})

    def action_draft(self):
        self.write({'state': 'draft'})
