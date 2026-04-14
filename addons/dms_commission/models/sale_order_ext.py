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
        """結案：計算傭金、產生激勵記錄、重算台數獎金與台數實物獎勵"""
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
            order._recompute_volume_gifts()

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
                self._recompute_volume_gifts_for(dealer_id, closed_month)

    # ── 傭金計算 ──────────────────────────────────────────

    def _get_product_template(self):
        """取得訂單對應的產品模板"""
        self.ensure_one()
        if not self.product_id:
            return self.env['dms.product.template']
        return self.product_id.template_id

    def _calc_base_commission(self, tmpl):
        """計算三層疊加傭金：基礎 + 車種覆蓋 + 車行覆蓋"""
        self.ensure_one()
        if not tmpl:
            return 0.0

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

        # 第三層：車行覆蓋規則（固定加碼，可限定品牌＋能源型式）
        if self.dealer_id:
            all_dealer_rules = self.env['dms.commission.dealer.rule'].search([])
            applicable_dealer_rules = all_dealer_rules.filtered(
                lambda r: (not r.dealer_ids or self.dealer_id in r.dealer_ids)
                and r.is_applicable_for(tmpl)
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
        """依激勵規則（及車行規則實物明細）產生 pending 的 delivery 記錄"""
        self.ensure_one()
        tmpl = self._get_product_template()
        tmpl_id = tmpl.id if tmpl else False
        dealer_id = self.dealer_id.id if self.dealer_id else False
        close_date = self.closed_date.date() if self.closed_date else fields.Date.today()

        # 從車行覆蓋規則的實物激勵明細產生（per_unit 性質，每台觸發）
        if self.dealer_id and tmpl:
            all_dealer_rules = self.env['dms.commission.dealer.rule'].search([])
            applicable_dealer_rules = all_dealer_rules.filtered(
                lambda r: (not r.dealer_ids or self.dealer_id in r.dealer_ids)
                and r.is_applicable_for(tmpl)
            )
            for drule in applicable_dealer_rules:
                for line in drule.incentive_line_ids:
                    existing = self.env['dms.incentive.delivery'].search([
                        ('sale_order_id', '=', self.id),
                        ('dealer_rule_line_id', '=', line.id),
                    ])
                    if not existing:
                        self.env['dms.incentive.delivery'].create({
                            'sale_order_id': self.id,
                            'dealer_id': dealer_id,
                            'part_id': line.part_id.id,
                            'dealer_rule_line_id': line.id,
                            'qty': line.quantity,
                            'state': 'pending',
                        })

        # 激勵規則（incentive.rule）：per_unit 型跳過（已由 dealer rule 明細覆蓋），volume 照跑
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

    def _recompute_volume_gifts(self):
        """重算台數實物獎勵：自身所在車行+月份"""
        self.ensure_one()
        dealer_id = self.dealer_id.id if self.dealer_id else False
        closed_month = self.closed_month
        if dealer_id and closed_month:
            self._recompute_volume_gifts_for(dealer_id, closed_month)

    @api.model
    def _recompute_volume_bonus_for(self, dealer_id, closed_month):
        """重算指定車行+月份所有 active commission record 的 volume_bonus"""
        records = self.env['dms.commission.record'].search([
            ('dealer_id', '=', dealer_id),
            ('closed_month', '=', closed_month),
            ('state', '=', 'active'),
        ])

        try:
            ref_date = datetime.date(
                int(closed_month[:4]), int(closed_month[5:7]), 1)
        except (ValueError, TypeError, IndexError):
            return

        all_volume_rules = self.env['dms.commission.volume.rule'].search([
            ('active', '=', True),
        ])
        all_gift_rules = self.env['dms.commission.volume.gift'].search([
            ('active', '=', True),
        ])

        # 特殊規則：dealer_ids 含此車行（volume.rule + volume.gift 跨類型合併判斷）
        specific_vrules = all_volume_rules.filtered(
            lambda r: dealer_id in r.dealer_ids.ids and r.is_applicable_for(dealer_id, ref_date))
        specific_gifts = all_gift_rules.filtered(
            lambda r: dealer_id in r.dealer_ids.ids and r.is_applicable_for(dealer_id, ref_date))

        use_specific = bool(specific_vrules or specific_gifts)

        # 只取 volume.rule 部分的適用規則
        applicable_vrules = specific_vrules if use_specific else all_volume_rules.filtered(
            lambda r: not r.dealer_ids and r.is_applicable_for(dealer_id, ref_date))

        for rec in records:
            best_bonus = 0.0
            for vrule in applicable_vrules:
                d_from, d_to = vrule.get_period_range(closed_month)
                # 計算此規則期間內此車行的台數（依 brand/energy 篩選）
                domain = [
                    ('dealer_id', '=', dealer_id),
                    ('state', '=', 'active'),
                    ('closed_date', '>=', datetime.datetime.combine(d_from, datetime.time.min)),
                    ('closed_date', '<=', datetime.datetime.combine(d_to, datetime.time.max)),
                ]
                period_records = self.env['dms.commission.record'].search(domain)

                if vrule.brand_id:
                    period_records = period_records.filtered(
                        lambda r: r.product_tmpl_id and r.product_tmpl_id.brand_id == vrule.brand_id)
                    if rec.product_tmpl_id and rec.product_tmpl_id.brand_id != vrule.brand_id:
                        continue
                elif vrule.energy_type:
                    period_records = period_records.filtered(
                        lambda r: r.product_tmpl_id and r.product_tmpl_id.energy_type == vrule.energy_type)
                    if rec.product_tmpl_id and rec.product_tmpl_id.energy_type != vrule.energy_type:
                        continue

                if vrule.product_tmpl_ids and rec.product_tmpl_id:
                    if rec.product_tmpl_id not in vrule.product_tmpl_ids:
                        continue

                count = len(period_records)
                # 依 mode 計算每台應得獎金（bonus_per_unit 是每台，所以預覽此筆是否達標即可）
                if vrule.mode == 'retroactive':
                    unit_bonus = vrule.bonus_per_unit if count >= vrule.min_qty else 0.0
                else:  # after_threshold
                    # 此筆是第幾台？算 rank
                    sorted_recs = period_records.sorted('closed_date')
                    ranks = {r.id: idx + 1 for idx, r in enumerate(sorted_recs)}
                    rank = ranks.get(rec.id, 0)
                    unit_bonus = vrule.bonus_per_unit if rank > vrule.min_qty else 0.0

                if unit_bonus > best_bonus:
                    best_bonus = unit_bonus

            if rec.volume_bonus != best_bonus:
                rec.volume_bonus = best_bonus

    @api.model
    def _recompute_volume_gifts_for(self, dealer_id, closed_month):
        """重算指定車行+月份所有台數實物獎勵（差額法）"""
        try:
            ref_date = datetime.date(
                int(closed_month[:4]), int(closed_month[5:7]), 1)
        except (ValueError, TypeError, IndexError):
            return

        all_volume_rules = self.env['dms.commission.volume.rule'].search([
            ('active', '=', True),
        ])
        all_gift_rules = self.env['dms.commission.volume.gift'].search([
            ('active', '=', True),
        ])

        # 跨類型排除判斷
        specific_vrules = all_volume_rules.filtered(
            lambda r: dealer_id in r.dealer_ids.ids and r.is_applicable_for(dealer_id, ref_date))
        specific_gifts = all_gift_rules.filtered(
            lambda r: dealer_id in r.dealer_ids.ids and r.is_applicable_for(dealer_id, ref_date))

        use_specific = bool(specific_vrules or specific_gifts)
        applicable_gifts = specific_gifts if use_specific else all_gift_rules.filtered(
            lambda r: not r.dealer_ids and r.is_applicable_for(dealer_id, ref_date))

        for gift_rule in applicable_gifts:
            d_from, d_to = gift_rule.get_period_range(closed_month)
            domain = [
                ('dealer_id', '=', dealer_id),
                ('state', '=', 'active'),
                ('closed_date', '>=', datetime.datetime.combine(d_from, datetime.time.min)),
                ('closed_date', '<=', datetime.datetime.combine(d_to, datetime.time.max)),
            ]
            period_records = self.env['dms.commission.record'].search(domain)

            # 品牌/能源篩選
            if gift_rule.brand_id:
                period_records = period_records.filtered(
                    lambda r: r.product_tmpl_id and r.product_tmpl_id.brand_id == gift_rule.brand_id)
            elif gift_rule.energy_type:
                period_records = period_records.filtered(
                    lambda r: r.product_tmpl_id and r.product_tmpl_id.energy_type == gift_rule.energy_type)

            count = len(period_records)
            expected_qty = gift_rule.compute_expected_qty(count)

            # 計算已記錄的非 voided delivery 總量
            existing_deliveries = self.env['dms.incentive.delivery'].search([
                ('volume_gift_rule_id', '=', gift_rule.id),
                ('dealer_id', '=', dealer_id),
                ('closed_month', '=', closed_month),
                ('state', '!=', 'voided'),
            ])
            already_given = sum(existing_deliveries.mapped('qty'))
            delta = expected_qty - already_given

            if delta > 0:
                # 找一筆本期有效訂單作為 delivery 的 sale_order_id（最新一筆）
                latest_order = self.env['dms.sale.order'].search([
                    ('dealer_id', '=', dealer_id),
                    ('is_closed', '=', True),
                    ('closed_month', '=', closed_month),
                ], order='closed_date desc', limit=1)
                if latest_order:
                    self.env['dms.incentive.delivery'].create({
                        'sale_order_id': latest_order.id,
                        'dealer_id': dealer_id,
                        'volume_gift_rule_id': gift_rule.id,
                        'part_id': gift_rule.part_id.id,
                        'qty': delta,
                        'state': 'pending',
                    })
            elif delta < 0:
                # void 最新幾筆 pending delivery 直到補足差額
                to_void = existing_deliveries.filtered(
                    lambda d: d.state == 'pending').sorted('id', reverse=True)
                remaining = -delta
                for dv in to_void:
                    if remaining <= 0:
                        break
                    if dv.qty <= remaining:
                        remaining -= dv.qty
                        dv.state = 'voided'
                    else:
                        dv.qty -= remaining
                        remaining = 0
