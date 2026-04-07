from odoo import models, fields, api
from odoo.exceptions import UserError
import datetime


class DmsSaleOrderExt(models.Model):
    """繼承 dms.sale.order，加入結案機制與傭金計算"""
    _inherit = 'dms.sale.order'

    is_closed = fields.Boolean(string='已結案', default=False, index=True)
    closed_date = fields.Datetime(string='結案時間', readonly=True)
    closed_month = fields.Char(
        string='結案月份', compute='_compute_closed_month', store=True)
    commission_record_id = fields.Many2one(
        'dms.commission.record', string='傭金記錄',
        compute='_compute_commission_record', store=False)

    @api.depends('closed_date')
    def _compute_closed_month(self):
        for rec in self:
            if rec.closed_date:
                rec.closed_month = rec.closed_date.strftime('%Y-%m')
            else:
                rec.closed_month = False

    def _compute_commission_record(self):
        CommRec = self.env['dms.commission.record']
        for rec in self:
            rec.commission_record_id = CommRec.search(
                [('sale_order_id', '=', rec.id)], limit=1)

    # ── 結案按鈕 ──────────────────────────────────────────

    def action_close_order(self):
        """結案：計算傭金、產生激勵記錄、重算台數獎金"""
        for order in self:
            if order.is_closed:
                raise UserError('此訂單已結案，請先撤銷結案再操作')
            order.write({
                'is_closed': True,
                'closed_date': fields.Datetime.now(),
            })
            order._create_or_update_commission_record()
            order._generate_incentive_deliveries()
            order._recompute_volume_bonus()

    def action_reopen_order(self):
        """撤銷結案：作廢傭金記錄與 pending 激勵、重算台數獎金"""
        for order in self:
            if not order.is_closed:
                raise UserError('此訂單尚未結案')
            # 作廢傭金記錄
            CommRec = self.env['dms.commission.record']
            rec = CommRec.search([('sale_order_id', '=', order.id)], limit=1)
            if rec:
                rec.state = 'voided'
            # 作廢 pending 激勵（已 delivered 的保留）
            self.env['dms.incentive.delivery'].search([
                ('sale_order_id', '=', order.id),
                ('state', '=', 'pending'),
            ]).write({'state': 'voided'})
            # 取得重算參數（結案前先記，撤銷後再重算）
            dealer_id = order.dealer_id.id
            closed_month = order.closed_month
            order.write({
                'is_closed': False,
                'closed_date': False,
            })
            # 重算（此訂單已不再是 active，所以只重算剩餘）
            if dealer_id and closed_month:
                self._recompute_volume_bonus_for(dealer_id, closed_month)

    # ── 傭金計算 ──────────────────────────────────────────

    def _get_product_template(self):
        """取得訂單對應的產品模板"""
        self.ensure_one()
        if not self.product_id:
            return self.env['dms.product.template']
        return self.product_id.template_id

    def _find_dealer_contract(self, tmpl):
        """查找適用此訂單的車行傭金合約（dealer + brand 優先；無 brand 的合約次之）"""
        self.ensure_one()
        if not self.dealer_id:
            return False
        brand_id = tmpl.brand_id.id if tmpl and tmpl.brand_id else False
        close_date = self.closed_date.date() if self.closed_date else fields.Date.today()
        contracts = self.env['dms.commission.dealer.contract'].search([
            ('dealer_id', '=', self.dealer_id.id),
            ('active', '=', True),
        ])
        # 優先找 dealer + brand 完全匹配的合約
        if brand_id:
            specific = contracts.filtered(
                lambda c: c.brand_id.id == brand_id and c.is_applicable_for(close_date))
            if specific:
                return specific[0]
        # fallback：dealer 且 brand_id 為空（全品牌合約）
        general = contracts.filtered(
            lambda c: not c.brand_id and c.is_applicable_for(close_date))
        return general[0] if general else False

    def _calc_base_commission(self, tmpl):
        """計算傭金：有合約走合約，否則走三層疊加規則"""
        self.ensure_one()
        if not tmpl:
            return 0.0

        # 優先：車行傭金合約
        contract = self._find_dealer_contract(tmpl)
        if contract:
            return contract.cash_commission

        # Fallback：三層疊加規則
        # 第一層：基礎傭金規則
        base_rule = self.env['dms.commission.product.rule'].search(
            [('product_tmpl_id', '=', tmpl.id)], limit=1)
        amount = base_rule.base_amount if base_rule else 0.0

        # 第二層：車種覆蓋規則（dealer_ids 包含當前車行，或 dealer_ids 為空）
        vehicle_domain = [('product_tmpl_id', '=', tmpl.id)]
        if self.dealer_id:
            vehicle_overrides = self.env['dms.commission.vehicle.rule'].search(vehicle_domain)
            vehicle_override = vehicle_overrides.filtered(
                lambda r: not r.dealer_ids or self.dealer_id in r.dealer_ids
            )[:1]
        else:
            vehicle_override = self.env['dms.commission.vehicle.rule'].search(
                vehicle_domain + [('dealer_ids', '=', False)], limit=1)
        if vehicle_override:
            amount = vehicle_override.compute_amount(amount)

        # 第三層：車行覆蓋規則（不限車型，固定加碼）
        if self.dealer_id:
            all_dealer_rules = self.env['dms.commission.dealer.rule'].search([])
            applicable_dealer_rules = all_dealer_rules.filtered(
                lambda r: not r.dealer_ids or self.dealer_id in r.dealer_ids
            )
            amount += sum(applicable_dealer_rules.mapped('addon_amount'))

        return amount

    def _create_or_update_commission_record(self):
        """結案時建立或更新傭金記錄"""
        self.ensure_one()
        tmpl = self._get_product_template()
        base_comm = self._calc_base_commission(tmpl)
        CommRec = self.env['dms.commission.record']
        existing = CommRec.search([('sale_order_id', '=', self.id)], limit=1)
        vals = {
            'sale_order_id': self.id,
            'dealer_id': self.dealer_id.id if self.dealer_id else False,
            'product_tmpl_id': tmpl.id if tmpl else False,
            'closed_date': self.closed_date,
            'base_commission': base_comm,
            'volume_bonus': 0.0,
            'state': 'active',
        }
        if existing:
            existing.write(vals)
        else:
            CommRec.create(vals)

    def _generate_incentive_deliveries(self):
        """依激勵規則或合約明細產生 pending 的 delivery 記錄"""
        self.ensure_one()
        tmpl = self._get_product_template()
        tmpl_id = tmpl.id if tmpl else False
        dealer_id = self.dealer_id.id if self.dealer_id else False
        close_date = self.closed_date.date() if self.closed_date else fields.Date.today()

        # 若有合約，只從合約實物明細產生（不走 incentive_rule 的 per_unit）
        contract = self._find_dealer_contract(tmpl)
        if contract and contract.incentive_line_ids:
            for line in contract.incentive_line_ids:
                existing = self.env['dms.incentive.delivery'].search([
                    ('sale_order_id', '=', self.id),
                    ('incentive_type_id', '=', line.incentive_type_id.id),
                    ('contract_line_id', '=', line.id),
                ])
                if not existing:
                    self.env['dms.incentive.delivery'].create({
                        'sale_order_id': self.id,
                        'dealer_id': dealer_id,
                        'incentive_type_id': line.incentive_type_id.id,
                        'contract_line_id': line.id,
                        'qty': line.quantity,
                        'state': 'pending',
                    })
            # 仍執行 volume-trigger 的激勵規則（台數激勵不被合約覆蓋）
            rules = self.env['dms.incentive.rule'].search([('active', '=', True)])
            for rule in rules:
                if rule.trigger != 'volume':
                    continue
                if not rule.is_applicable_for(dealer_id, tmpl_id, close_date):
                    continue
                month = self.closed_month
                count = self._count_closed_orders_this_month(dealer_id, month)
                if count >= rule.min_qty:
                    existing = self.env['dms.incentive.delivery'].search([
                        ('sale_order_id', '=', self.id),
                        ('incentive_rule_id', '=', rule.id),
                    ])
                    if not existing:
                        self._create_incentive_delivery(rule)
            return

        # 無合約：走原本的 incentive_rule 邏輯
        rules = self.env['dms.incentive.rule'].search([('active', '=', True)])
        for rule in rules:
            if not rule.is_applicable_for(dealer_id, tmpl_id, close_date):
                continue
            if rule.trigger == 'per_unit':
                self._create_incentive_delivery(rule)
            elif rule.trigger == 'volume':
                month = self.closed_month
                count = self._count_closed_orders_this_month(dealer_id, month)
                if count >= rule.min_qty:
                    existing = self.env['dms.incentive.delivery'].search([
                        ('sale_order_id', '=', self.id),
                        ('incentive_rule_id', '=', rule.id),
                    ])
                    if not existing:
                        self._create_incentive_delivery(rule)

    def _create_incentive_delivery(self, rule):
        self.ensure_one()
        self.env['dms.incentive.delivery'].create({
            'sale_order_id': self.id,
            'dealer_id': self.dealer_id.id if self.dealer_id else False,
            'incentive_rule_id': rule.id,
            'incentive_type_id': rule.incentive_type_id.id,
            'qty': rule.qty_per_trigger,
            'state': 'pending',
        })

    # ── 台數獎金重算（方案 X）────────────────────────────

    def _count_closed_orders_this_month(self, dealer_id, closed_month):
        """計算指定車行本月 active commission record 數"""
        return self.env['dms.commission.record'].search_count([
            ('dealer_id', '=', dealer_id),
            ('closed_month', '=', closed_month),
            ('state', '=', 'active'),
        ])

    def _recompute_volume_bonus(self):
        """重算：自身所在車行+月份"""
        self.ensure_one()
        dealer_id = self.dealer_id.id if self.dealer_id else False
        closed_month = self.closed_month
        if dealer_id and closed_month:
            self._recompute_volume_bonus_for(dealer_id, closed_month)

    @api.model
    def _recompute_volume_bonus_for(self, dealer_id, closed_month):
        """重算指定車行+月份所有 active commission record 的 volume_bonus"""
        records = self.env['dms.commission.record'].search([
            ('dealer_id', '=', dealer_id),
            ('closed_month', '=', closed_month),
            ('state', '=', 'active'),
        ])
        total_count = len(records)

        # 找所有適用此車行的台數獎金規則（依 closed_month 判斷日期）
        # closed_month 格式 YYYY-MM，取第一天作為比較日期
        try:
            ref_date = datetime.date(
                int(closed_month[:4]), int(closed_month[5:7]), 1)
        except (ValueError, TypeError, IndexError):
            return

        volume_rules = self.env['dms.commission.volume.rule'].search([
            ('active', '=', True),
        ])

        # 分類：特定規則（dealer_ids 包含此車行）vs 通用規則（dealer_ids 空）
        specific_rules = volume_rules.filtered(
            lambda r: dealer_id in r.dealer_ids.ids and r.is_applicable_for(dealer_id, ref_date))
        general_rules = volume_rules.filtered(
            lambda r: not r.dealer_ids and r.is_applicable_for(dealer_id, ref_date))
        # 有特定規則就只用特定，否則用通用
        applicable_rules = specific_rules if specific_rules else general_rules

        for rec in records:
            bonus = 0.0
            best_bonus = 0.0
            for vrule in applicable_rules:
                # 品牌維度篩選：規則有限定品牌時，只計算該品牌的台數
                if vrule.brand_id:
                    brand_records = records.filtered(
                        lambda r: r.product_tmpl_id and
                        r.product_tmpl_id.brand_id == vrule.brand_id
                    )
                    count = len(brand_records)
                    # 此筆記錄的品牌不符，跳過
                    if rec.product_tmpl_id and rec.product_tmpl_id.brand_id != vrule.brand_id:
                        continue
                elif vrule.energy_type:
                    count = sum(
                        1 for r in records
                        if r.product_tmpl_id and
                        r.product_tmpl_id.energy_type == vrule.energy_type
                    )
                    if rec.product_tmpl_id and rec.product_tmpl_id.energy_type != vrule.energy_type:
                        continue
                else:
                    count = total_count
                # 限定車種篩選
                if vrule.product_tmpl_ids and rec.product_tmpl_id:
                    if rec.product_tmpl_id not in vrule.product_tmpl_ids:
                        continue
                # 達標才考慮，取最高 bonus_per_unit（不疊加）
                if count >= vrule.min_qty and vrule.bonus_per_unit > best_bonus:
                    best_bonus = vrule.bonus_per_unit
            bonus = best_bonus
            if rec.volume_bonus != bonus:
                rec.volume_bonus = bonus
