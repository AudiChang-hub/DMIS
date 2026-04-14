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
    customer_name = fields.Char(string='客戶姓名', required=True)
    customer_phone = fields.Char(string='聯絡電話')
    id_number = fields.Char(string='身分證字號')
    birthday_ad = fields.Date(string='西元生日')
    birthday_roc = fields.Char(
        string='民國生日',
        compute='_compute_birthday_roc',
        store=False,
    )
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
    finance_company = fields.Selection(
        [('和潤', '和潤'), ('遠信', '遠信'), ('仲信', '仲信'), ('other', '其他')],
        string='分期公司')
    finance_company_other = fields.Char(string='其他分期公司')
    installment_plan_id = fields.Many2one(
        'dms.product.installment.line',
        string='分期方案',
        ondelete='set null')
    installment_periods = fields.Integer(string='分期期數', default=0)
    installment_monthly = fields.Float(string='月付金', digits=(12, 0))
    installment_setup_fee = fields.Float(string='設定費', digits=(12, 0), default=0)
    installment_open_fee = fields.Float(string='開辦費', digits=(12, 0), default=0)

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

    # ── 收益統計：支出 ───────────────────────────────────
    out_credit_card_fee = fields.Float(string='信用卡手續費支出', digits=(12, 0), default=0)
    out_installment_fee = fields.Float(string='分期手續費支出', digits=(12, 0), default=0)
    out_plate_tax = fields.Float(string='領牌稅金支出', digits=(12, 0), default=0)
    out_compulsory_ins = fields.Float(string='強制險支出', digits=(12, 0), default=0)
    out_plate_select = fields.Float(string='選號支出', digits=(12, 0), default=0)
    out_used_car = fields.Float(string='中古車支出', digits=(12, 0), default=0)
    out_gift_shipping = fields.Float(string='贈品、運費支出', digits=(12, 0), default=0)
    out_dealer_commission = fields.Float(string='車行傭金支出', digits=(12, 0), default=0)
    out_friendly_dealer_bonus = fields.Float(string='友善車行獎金支出', digits=(12, 0), default=0)
    out_first_sale_bonus = fields.Float(string='首賣獎金支出', digits=(12, 0), default=0)
    out_unit_bonus = fields.Float(string='台數獎金支出', digits=(12, 0), default=0)

    # ── 收益統計：收入 ───────────────────────────────────
    in_plate_tax = fields.Float(string='領牌稅金收入', digits=(12, 0), default=0)
    in_compulsory_ins = fields.Float(string='強制險收入', digits=(12, 0), default=0)
    in_agency_fee = fields.Float(string='代辦費收入', digits=(12, 0), default=0)
    in_scrap_agency = fields.Float(string='報廢代辦收入', digits=(12, 0), default=0)
    in_plate_select = fields.Float(string='選號收入', digits=(12, 0), default=0)
    in_used_car = fields.Float(string='中古車收入', digits=(12, 0), default=0)
    in_scrap_car = fields.Float(string='報廢車收入', digits=(12, 0), default=0)
    in_card_installment_fee = fields.Float(string='刷卡、分期手續費收入', digits=(12, 0), default=0)
    in_yamaha_bonus = fields.Float(string='山葉獎金收入', digits=(12, 0), default=0)
    in_friendly_dealer_bonus = fields.Float(string='友善車行獎金收入', digits=(12, 0), default=0)
    in_other = fields.Float(string='其他收入', digits=(12, 0), default=0)
    in_actual_sales_bonus = fields.Float(string='實銷獎勵金', digits=(12, 0), default=0)
    in_promo_subsidy = fields.Float(string='促銷補助金', digits=(12, 0), default=0)
    in_installment_subsidy = fields.Float(string='分期補貼息', digits=(12, 0), default=0)
    in_compulsory_ins_commission = fields.Float(string='強制險傭金', digits=(12, 0), default=0)
    in_credit_card_commission = fields.Float(string='信用卡傭金', digits=(12, 0), default=0)
    net_profit = fields.Float(
        string='單筆淨利', digits=(12, 0),
        compute='_compute_net_profit', store=True)

    # ── 計算欄位 ──────────────────────────────────────────
    @api.depends('birthday_ad')
    def _compute_birthday_roc(self):
        for rec in self:
            if rec.birthday_ad:
                roc_year = rec.birthday_ad.year - 1911
                rec.birthday_roc = (
                    f"民國{roc_year}年"
                    f"{rec.birthday_ad.month:02d}月"
                    f"{rec.birthday_ad.day:02d}日"
                )
            else:
                rec.birthday_roc = False

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

    @api.depends('amount_total', 'deposit_amount', 'payment_method',
                 'installment_setup_fee', 'installment_open_fee', 'fee_total')
    def _compute_balance(self):
        for rec in self:
            if rec.payment_method == 'installment':
                rec.balance_amount = (
                    (rec.installment_setup_fee or 0) +
                    (rec.installment_open_fee or 0) +
                    (rec.fee_total or 0) -
                    (rec.deposit_amount or 0)
                )
            else:
                rec.balance_amount = (rec.amount_total or 0) - (rec.deposit_amount or 0)

    _PROFIT_INCOME_FIELDS = (
        'amount_total',
        'in_plate_tax', 'in_compulsory_ins', 'in_agency_fee', 'in_scrap_agency',
        'in_plate_select', 'in_used_car', 'in_scrap_car', 'in_card_installment_fee',
        'in_yamaha_bonus', 'in_friendly_dealer_bonus', 'in_other',
        'in_actual_sales_bonus', 'in_promo_subsidy', 'in_installment_subsidy',
        'in_compulsory_ins_commission', 'in_credit_card_commission',
    )
    _PROFIT_EXPENSE_FIELDS = (
        'cost',
        'out_credit_card_fee', 'out_installment_fee', 'out_plate_tax',
        'out_compulsory_ins', 'out_plate_select', 'out_used_car',
        'out_gift_shipping', 'out_dealer_commission', 'out_friendly_dealer_bonus',
        'out_first_sale_bonus', 'out_unit_bonus',
    )

    @api.depends(*_PROFIT_INCOME_FIELDS, *_PROFIT_EXPENSE_FIELDS)
    def _compute_net_profit(self):
        for rec in self:
            income = sum(getattr(rec, f) or 0 for f in self._PROFIT_INCOME_FIELDS)
            expense = sum(getattr(rec, f) or 0 for f in self._PROFIT_EXPENSE_FIELDS)
            rec.net_profit = income - expense

    # ── 序號 ──────────────────────────────────────────────
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', '/') == '/':
                vals['name'] = (
                    self.env['ir.sequence'].next_by_code('dms.sale.order') or '/')
        return super().create(vals_list)

    # ── Onchange ──────────────────────────────────────────
    @api.onchange('installment_plan_id')
    def _onchange_installment_plan_id(self):
        plan = self.installment_plan_id
        if plan:
            self.installment_periods = plan.periods
            self.installment_monthly = plan.monthly_payment
            self.installment_setup_fee = plan.setup_fee
            self.installment_open_fee = plan.opening_fee

    @api.onchange('product_id')
    def _onchange_product_id(self):
        self.color_id = False  # 車款變更時清空顏色
        self.installment_plan_id = False  # 車款變更時清空分期方案
        plan_domain = [('product_id', '=', self.product_id.id)] if self.product_id else [('id', '=', False)]
        if not self.product_id:
            return {'domain': {'installment_plan_id': plan_domain}}

        # 優先讀取 dms.price.line（新價格結構）
        price_line = self.env['dms.price.line'].get_effective_line(
            self.product_id,
            query_date=self.order_date or fields.Date.context_today(self),
        )
        if price_line:
            self.cash_price = price_line.cash_price
        elif self.product_id.effective_price:
            # 次優先：讀取產品上的有效售價（直接欄位：promo_price 或 cash_price）
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
        return {'domain': {'installment_plan_id': plan_domain}}

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
