from odoo import models, fields, api


class SaleOrder(models.Model):
    _name = 'dms.sale.order'
    _description = '銷售訂單'
    _rec_name = 'name'
    _order = 'order_date desc, name desc'

    # ── 識別 ─────────────────────────────────────────────
    name = fields.Char(
        string='訂單編號', required=True, copy=False, readonly=True, default='/')
    order_date = fields.Date(
        string='訂單日期', required=True, default=fields.Date.today)
    sale_type = fields.Selection(
        [('store', '店面'), ('dealer', '車行')],
        string='交易類型', required=True, default='store')
    state = fields.Selection(
        [('draft', '草稿'), ('confirmed', '確認'), ('cancel', '取消')],
        string='狀態', default='draft', required=True)
    active = fields.Boolean(string='啟用', default=True)

    # ── 客戶資訊 ──────────────────────────────────────────
    customer_id = fields.Many2one(
        'res.partner', string='已建檔客戶', ondelete='restrict',
        help='可選：選取已建檔客戶時自動帶入下方資料，不常化也可直接填寫')
    customer_name = fields.Char(string='客戶姓名', required=True)
    customer_phone = fields.Char(string='聯絡電話')
    id_number = fields.Char(string='身分證字號')
    birthday_roc = fields.Char(string='民國生日')
    address_registered = fields.Text(string='戶籍地址')

    # ── 車輛資訊 ──────────────────────────────────────────
    product_id = fields.Many2one(
        'dms.product', string='車款', required=True, ondelete='restrict')
    product_energy_type = fields.Selection(
        related='product_id.energy_type',
        string='能源型式', readonly=True, store=False)
    color_id = fields.Many2one(
        'dms.product.color', string='顏色',
        domain="[('product_id', '=', product_id)]",
        ondelete='restrict')
    engine_number = fields.Char(string='引擎號碼')
    frame_number = fields.Char(string='車身號碼')
    plate_number = fields.Char(string='車牌號碼')
    registration_date = fields.Date(string='領牌日期')

    # ── 金流 ──────────────────────────────────────────────
    cash_price = fields.Float(
        string='參考售價', digits=(12, 0), help='從車款售價自動帶入，可手動調整')
    amount_total = fields.Float(string='實際收款價', digits=(12, 0))
    cost = fields.Float(string='成本', digits=(12, 0))
    payment_method = fields.Selection(
        [('cash', '現金'), ('credit', '信用卡'), ('installment', '分期')],
        string='付款方式')
    finance_company = fields.Char(string='分期公司')
    installment_periods = fields.Integer(string='分期期數', default=0)
    installment_monthly = fields.Float(string='月付金', digits=(12, 0))

    # ── 車行（B2B） ───────────────────────────────────────
    dealer_id = fields.Many2one('dms.dealer', string='車行', ondelete='restrict')
    dealer_amount = fields.Float(string='車行收款', digits=(12, 0))
    commission = fields.Float(string='傭金', digits=(12, 0))

    # ── 牌險費 ────────────────────────────────────────────
    fee_vehicle_registration = fields.Float(string='代繳行照費', digits=(12, 0))
    fee_inspection = fields.Float(string='代繳檢驗費', digits=(12, 0))
    fee_plate = fields.Float(string='代繳號牌費', digits=(12, 0))
    fee_stamp = fields.Float(string='代繳刻印費', digits=(12, 0))
    fee_insurance = fields.Float(string='代繳保險費', digits=(12, 0))
    fee_guild_cert = fields.Float(string='公會證明費', digits=(12, 0))
    fee_document = fields.Float(string='文件處理費', digits=(12, 0))
    fee_other = fields.Float(string='其他', digits=(12, 0))
    fee_plate_selection = fields.Float(string='選號費', digits=(12, 0))
    fee_total = fields.Float(
        string='牌險合計', digits=(12, 0),
        compute='_compute_fee_total', store=True)

    # ── 精品明細 ──────────────────────────────────────────
    order_line_ids = fields.One2many(
        'dms.sale.order.line', 'order_id', string='精品明細')
    # ── 付款狀態 ──────────────────────────────────────────
    deposit_amount = fields.Float(string='訂金', digits=(12, 0), default=0)
    balance_amount = fields.Float(
        string='尾款', digits=(12, 0),
        compute='_compute_balance', store=True)
    is_settled = fields.Boolean(string='已結清', default=False)
    settle_date = fields.Date(string='結清日期')
    # ── 其他 ──────────────────────────────────────────────
    helmet_count = fields.Integer(string='安全帽（頂）')
    gift_voucher = fields.Float(string='禮卷/匯款', digits=(12, 0))
    gift_note = fields.Char(string='贈品說明')
    special_plan = fields.Char(string='特殊方案')
    note = fields.Text(string='備註')

    # ── 計算欄位 ──────────────────────────────────────────
    @api.depends(
        'fee_vehicle_registration', 'fee_inspection', 'fee_plate',
        'fee_stamp', 'fee_insurance', 'fee_guild_cert',
        'fee_document', 'fee_other', 'fee_plate_selection')
    def _compute_fee_total(self):
        for rec in self:
            rec.fee_total = (
                rec.fee_vehicle_registration + rec.fee_inspection +
                rec.fee_plate + rec.fee_stamp + rec.fee_insurance +
                rec.fee_guild_cert + rec.fee_document +
                rec.fee_other + rec.fee_plate_selection
            )

    @api.depends('amount_total', 'deposit_amount')
    def _compute_balance(self):
        for rec in self:
            rec.balance_amount = (rec.amount_total or 0) - (rec.deposit_amount or 0)

    # ── 序號 ──────────────────────────────────────────────
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', '/') == '/':
                vals['name'] = (
                    self.env['ir.sequence'].next_by_code('dms.sale.order') or '/')
        return super().create(vals_list)

    # ── Onchange ──────────────────────────────────────────
    @api.onchange('customer_id')
    def _onchange_customer_id(self):
        if self.customer_id:
            p = self.customer_id
            self.customer_name = p.name
            self.customer_phone = p.phone or p.mobile or ''
            self.id_number = getattr(p, 'id_number', '') or ''
            self.birthday_roc = getattr(p, 'dms_birthday_roc', '') or ''
            self.address_registered = getattr(p, 'address_registered', '') or ''

    @api.onchange('product_id')
    def _onchange_product_id(self):
        self.color_id = False  # 車款變更時清空顏色
        if not self.product_id:
            return

        # 優先讀取產品上的有效售價（effective_price = promo_price if promo_price > 0 else cash_price）
        if self.product_id.effective_price:
            self.cash_price = self.product_id.effective_price
        else:
            # Fallback：舊車款售價相容層（待 018 移除）
            price = self.env['dms.vehicle.price'].search(
                [('product_id', '=', self.product_id.id), ('active', '=', True)],
                order='valid_year_month desc', limit=1)
            if price:
                self.cash_price = price.cash_price
        # 電車：自動帶入牌險費
        if self.product_id.energy_type == 'electric':
            fee = self.env['dms.ev.fee.schedule'].search(
                [('product_id', '=', self.product_id.id), ('active', '=', True)],
                order='valid_from desc', limit=1)
            if fee:
                self.fee_vehicle_registration = fee.fee_vehicle_registration
                self.fee_inspection = fee.fee_inspection
                self.fee_plate = fee.fee_plate
                self.fee_stamp = fee.fee_stamp
                self.fee_insurance = fee.fee_insurance
                self.fee_guild_cert = fee.fee_guild_cert
                self.fee_document = fee.fee_document
                self.fee_other = fee.fee_other
        else:
            # 油車：清空牌險費供手動填入
            self.fee_vehicle_registration = 0
            self.fee_inspection = 0
            self.fee_plate = 0
            self.fee_stamp = 0
            self.fee_insurance = 0
            self.fee_guild_cert = 0
            self.fee_document = 0
            self.fee_other = 0

    @api.onchange('dealer_id', 'product_id', 'installment_periods')
    def _onchange_commission(self):
        if not self.dealer_id:
            return
        periods = self.installment_periods or 0
        base_domain = [
            ('dealer_id', '=', self.dealer_id.id),
            ('installment_periods', '=', periods),
            ('active', '=', True),
        ]
        # 精確匹配 dealer + product + periods
        rule = self.env['dms.commission.rule'].search(
            base_domain + [('product_id', '=', self.product_id.id if self.product_id else False)],
            limit=1)
        # Fallback：product 留空的通用規則
        if not rule:
            rule = self.env['dms.commission.rule'].search(
                base_domain + [('product_id', '=', False)], limit=1)
        if rule:
            self.commission = rule.commission_amount

    # ── 狀態動作 ──────────────────────────────────────────
    def button_confirm(self):
        self.write({'state': 'confirmed'})

    def button_reset(self):
        self.write({'state': 'draft'})

    def button_cancel(self):
        self.write({'state': 'cancel'})
