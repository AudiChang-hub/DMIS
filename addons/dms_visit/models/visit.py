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
    dealer_address_map_url = fields.Char(
        related='dealer_id.address_map_url',
        string='車行地址（地圖）',
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
    is_auto_generated = fields.Boolean(
        string='排程自動建立',
        default=False,
        readonly=True,
        help='由自動週期排程建立，取消勾選「自動建立」時將自動取消未來草稿。',
    )
    schedule_id = fields.Many2one(
        'dms.visit.schedule',
        string='來源排程',
        ondelete='set null',
        index=True,
        readonly=True,
        help='產生此拜訪的排程設定；手動建立的拜訪此欄為空。',
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

    def action_open_bulk_create_wizard(self):
        self.ensure_one()
        action = self.env.ref('dms_visit.action_dms_visit_bulk_create_wizard').read()[0]
        action['context'] = {
            'default_visit_date': self.visit_date or fields.Datetime.now(),
            'default_visitor_id': self.visitor_id.id or self.env.user.id,
            'default_purpose_id': self.purpose_id.id or False,
            'default_note': self.note or False,
        }
        return action
