import logging
from datetime import date, timedelta

from dateutil.relativedelta import relativedelta

from odoo import models, fields, api

_logger = logging.getLogger(__name__)

# 觸發重新產生排程的欄位集合
_SCHEDULE_FIELDS = frozenset({
    'auto_price_list_visit',
    'auto_visit_schedule_type',
    'auto_visit_day_of_month',
    'auto_visit_week_number',
    'auto_visit_weekday',
    'price_list_visitor_id',
})

# 預產生未來幾個月的拜訪草稿（Google 行事曆式預填）
_GENERATE_MONTHS = 12


class DealerVisit(models.Model):
    _inherit = 'dms.dealer'

    visit_ids = fields.One2many(
        'dms.visit', 'dealer_id', string='拜訪紀錄',
    )
    visit_count = fields.Integer(
        compute='_compute_visit_count',
        string='拜訪次數',
    )
    auto_price_list_visit = fields.Boolean(
        string='每月自動建立價格表拜訪',
        default=False,
        help='勾選後立即預填未來 12 個月的排程拜訪草稿；取消後自動取消尚未完成的草稿。',
    )
    price_list_visitor_id = fields.Many2one(
        'res.users',
        string='自動拜訪業務人員',
        help='排程拜訪指定的拜訪人員；留空則以系統管理員建立。',
    )

    # ── 自動拜訪週期設定 ─────────────────────────────────────────
    auto_visit_schedule_type = fields.Selection([
        ('fixed_day',        '每月固定日期'),
        ('weekday_of_month', '每月第 N 個星期幾'),
    ], string='週期類型', default='fixed_day')

    auto_visit_day_of_month = fields.Integer(
        string='每月幾號',
        default=1,
        help='1–28，週期類型為「每月固定日期」時使用（遇假日自動順延）',
    )
    auto_visit_week_number = fields.Selection([
        ('1', '第 1 週'), ('2', '第 2 週'), ('3', '第 3 週'),
        ('4', '第 4 週'), ('5', '第 5 週'),
    ], string='第幾週', default='1')
    auto_visit_weekday = fields.Selection([
        ('0', '星期一'), ('1', '星期二'), ('2', '星期三'),
        ('3', '星期四'), ('4', '星期五'), ('5', '星期六'), ('6', '星期日'),
    ], string='星期幾', default='0')

    # 顯示最近一筆未來草稿日期（只讀，不儲存，從 visit_ids 計算）
    auto_visit_next_date = fields.Date(
        string='下一筆排程拜訪',
        compute='_compute_auto_visit_next_date',
        store=False,
    )

    # ── computed ─────────────────────────────────────────────────
    @api.depends('visit_ids')
    def _compute_visit_count(self):
        for rec in self:
            rec.visit_count = len(rec.visit_ids)

    @api.depends('visit_ids.visit_date', 'visit_ids.state', 'visit_ids.is_auto_generated',
                 'auto_price_list_visit')
    def _compute_auto_visit_next_date(self):
        today_str = fields.Datetime.to_string(
            fields.Datetime.from_string('%s 00:00:00' % fields.Date.today())
        )
        for rec in self:
            if not rec.auto_price_list_visit:
                rec.auto_visit_next_date = False
                continue
            next_v = self.env['dms.visit'].search([
                ('dealer_id',       '=',  rec.id),
                ('is_auto_generated', '=', True),
                ('state',           '=',  'draft'),
                ('visit_date',      '>=', today_str),
            ], order='visit_date asc', limit=1)
            if next_v and next_v.visit_date:
                local_dt = fields.Datetime.context_timestamp(next_v, next_v.visit_date)
                rec.auto_visit_next_date = local_dt.date()
            else:
                rec.auto_visit_next_date = False

    # ── write() 覆寫：週期設定變更時自動重新產生 ─────────────────
    def write(self, vals):
        schedule_changed = bool(_SCHEDULE_FIELDS & set(vals.keys()))
        # 記錄 write 前哪些已啟用
        was_enabled = {r.id for r in self if r.auto_price_list_visit}

        result = super().write(vals)

        if schedule_changed:
            for rec in self:
                if rec.auto_price_list_visit:
                    rec._regenerate_future_visits()
                elif rec.id in was_enabled:
                    # 原本啟用，現在關閉 → 取消未來草稿
                    rec._cancel_future_auto_visits()

        return result

    # ── 核心排程邏輯 ─────────────────────────────────────────────
    def _get_price_list_purpose(self):
        return self.env['dms.visit.purpose'].search(
            ['|', ('code', '=', 'PRICE'), ('name', 'ilike', '價格表')],
            limit=1,
        )

    def _generate_all_dates(self, months=_GENERATE_MONTHS):
        """計算未來 N 個月內所有排程日期（一次載入假日，效能最佳）。"""
        self.ensure_one()
        today = date.today()
        horizon = today + relativedelta(months=months)

        # 一次載入整個 horizon 的假日（fixed_day 才需要，weekday_of_month 不用）
        holidays = set(self.env['dms.public.holiday'].sudo().search([
            ('date', '>=', fields.Date.to_string(today)),
            ('date', '<=', fields.Date.to_string(horizon + timedelta(days=45))),
        ]).mapped('date'))

        dates = []
        cursor = today - timedelta(days=1)   # 讓 today 本身也能被命中
        while True:
            next_d = self._calc_next_auto_date(cursor, holidays=holidays)
            if next_d > horizon:
                break
            dates.append(next_d)
            cursor = next_d
        return dates

    def _regenerate_future_visits(self):
        """刪除未來所有自動草稿，依最新週期設定重新產生 12 個月。"""
        self.ensure_one()
        today = date.today()
        today_dt = fields.Datetime.from_string('%s 00:00:00' % today)

        # 刪除未來的自動草稿（已完成/已取消 保留）
        self.env['dms.visit'].sudo().search([
            ('dealer_id',         '=',  self.id),
            ('is_auto_generated', '=',  True),
            ('state',             '=',  'draft'),
            ('visit_date',        '>=', today_dt),
        ]).unlink()

        purpose = self._get_price_list_purpose()
        visitor = (
            self.price_list_visitor_id.id
            if self.price_list_visitor_id
            else self.env.ref('base.user_admin').id
        )
        scheduled_dates = self._generate_all_dates()
        vals_list = [{
            'visit_date':        fields.Datetime.from_string('%s 09:00:00' % d),
            'dealer_id':         self.id,
            'visitor_id':        visitor,
            'purpose_id':        purpose.id if purpose else False,
            'state':             'draft',
            'is_auto_generated': True,
        } for d in scheduled_dates]

        if vals_list:
            self.env['dms.visit'].sudo().create(vals_list)
        _logger.info('DMS 排程：%s 重新產生 %d 筆拜訪草稿', self.name, len(vals_list))

    def _cancel_future_auto_visits(self):
        """關閉自動拜訪時，取消未來所有自動草稿（不刪除，保留歷史）。"""
        today_dt = fields.Datetime.from_string('%s 00:00:00' % date.today())
        self.env['dms.visit'].sudo().search([
            ('dealer_id',         '=',  self.id),
            ('is_auto_generated', '=',  True),
            ('state',             '=',  'draft'),
            ('visit_date',        '>=', today_dt),
        ]).write({'state': 'cancel'})

    def _topup_future_visits(self):
        """補足 horizon 內缺漏的排程拜訪（cron 每日呼叫）。"""
        self.ensure_one()
        today = date.today()
        today_dt = fields.Datetime.from_string('%s 00:00:00' % today)
        purpose = self._get_price_list_purpose()
        visitor = (
            self.price_list_visitor_id.id
            if self.price_list_visitor_id
            else self.env.ref('base.user_admin').id
        )
        for d in self._generate_all_dates():
            dt_s = fields.Datetime.from_string('%s 00:00:00' % d)
            dt_e = fields.Datetime.from_string('%s 23:59:59' % d)
            exists = self.env['dms.visit'].sudo().search_count([
                ('dealer_id',  '=',  self.id),
                ('visit_date', '>=', dt_s),
                ('visit_date', '<=', dt_e),
                ('purpose_id', '=',  purpose.id if purpose else False),
                ('state',      '!=', 'cancel'),
            ])
            if not exists:
                self.env['dms.visit'].sudo().create({
                    'visit_date':        fields.Datetime.from_string('%s 09:00:00' % d),
                    'dealer_id':         self.id,
                    'visitor_id':        visitor,
                    'purpose_id':        purpose.id if purpose else False,
                    'state':             'draft',
                    'is_auto_generated': True,
                })

    # ── 日期計算工具 ──────────────────────────────────────────────
    def _calc_next_auto_date(self, from_date, holidays=None):
        """回傳嚴格大於 from_date 的下一個排程日期。"""
        self.ensure_one()
        if self.auto_visit_schedule_type == 'fixed_day':
            day = max(1, min(int(self.auto_visit_day_of_month or 1), 28))
            try:
                candidate = from_date.replace(day=day)
            except ValueError:
                candidate = (from_date.replace(day=1) + relativedelta(months=1)).replace(day=day)
            if candidate <= from_date:
                candidate = candidate + relativedelta(months=1)
            return self._advance_to_working_day(candidate, holidays=holidays)

        # weekday_of_month（使用者指定星期幾，不做假日順延）
        week_n  = int(self.auto_visit_week_number or '1')
        weekday = int(self.auto_visit_weekday or '0')
        candidate = self._nth_weekday_of_month(from_date.year, from_date.month, week_n, weekday)
        if candidate <= from_date:
            nm = from_date + relativedelta(months=1)
            candidate = self._nth_weekday_of_month(nm.year, nm.month, week_n, weekday)
        return candidate

    def _advance_to_working_day(self, target_date, holidays=None):
        """若為週末或台灣國定假日，逐日順延至最近工作日。"""
        if holidays is None:
            window_end = target_date + timedelta(days=30)
            holidays = set(self.env['dms.public.holiday'].sudo().search([
                ('date', '>=', fields.Date.to_string(target_date)),
                ('date', '<=', fields.Date.to_string(window_end)),
            ]).mapped('date'))
        d = target_date
        while d.weekday() >= 5 or d in holidays:   # 5=Sat, 6=Sun
            d += timedelta(days=1)
        return d

    @staticmethod
    def _nth_weekday_of_month(year, month, nth, weekday):
        """回傳指定月份第 nth 個 weekday（0=週一）的日期。"""
        first = date(year, month, 1)
        diff  = (weekday - first.weekday()) % 7
        first_occ = first + timedelta(days=diff)
        target = first_occ + timedelta(weeks=nth - 1)
        if target.month != month:                   # 第5週不存在時退回第4週
            target = first_occ + timedelta(weeks=nth - 2)
        return target

    # ── 動作按鈕 ─────────────────────────────────────────────────
    def action_open_visits(self):
        self.ensure_one()
        return {
            'name': '%s — 拜訪紀錄' % self.name,
            'type': 'ir.actions.act_window',
            'res_model': 'dms.visit',
            'view_mode': 'tree,form,calendar',
            'domain': [('dealer_id', '=', self.id)],
            'context': {
                'default_dealer_id': self.id,
                'default_visitor_id': self.env.user.id,
            },
        }

    def action_regenerate_visits(self):
        """手動按鈕：重新產生未來 12 個月排程拜訪（刪舊草稿重建）。"""
        self.ensure_one()
        if not self.auto_price_list_visit:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': '未啟用',
                    'message': '請先勾選「每月自動建立價格表拜訪」。',
                    'type': 'warning', 'sticky': False,
                },
            }
        self._regenerate_future_visits()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': '完成',
                'message': '已重新產生未來 %d 個月的排程拜訪草稿。' % _GENERATE_MONTHS,
                'type': 'success', 'sticky': False,
            },
        }

    # ── Cron ─────────────────────────────────────────────────────
    @api.model
    def cron_generate_price_list_visits(self):
        """每日執行：補足所有啟用排程的車行在 horizon 內缺漏的拜訪。"""
        dealers = self.search([
            ('auto_price_list_visit', '=', True),
            ('active', '=', True),
        ])
        for dealer in dealers:
            try:
                dealer._topup_future_visits()
            except Exception as e:
                _logger.error('DMS cron topup 失敗（%s）: %s', dealer.name, e)
        _logger.info('DMS 排程 cron 完成：檢查 %d 家車行', len(dealers))



class DealerVisit(models.Model):
    _inherit = 'dms.dealer'

    visit_ids = fields.One2many(
        'dms.visit', 'dealer_id', string='拜訪紀錄',
    )
    visit_count = fields.Integer(
        compute='_compute_visit_count',
        string='拜訪次數',
    )
    auto_price_list_visit = fields.Boolean(
        string='每月自動建立價格表拜訪',
        default=False,
        help='勾選後，排程每日檢查並自動為此車行建立「價格表發放」拜訪紀錄。',
    )
    price_list_visitor_id = fields.Many2one(
        'res.users',
        string='自動拜訪業務人員',
        help='月度自動建立拜訪時所指定的拜訪人員；留空則以系統管理員建立。',
    )

    # ── 自動拜訪週期設定 ─────────────────────────────────────────
    auto_visit_schedule_type = fields.Selection([
        ('fixed_day',        '每月固定日期'),
        ('weekday_of_month', '每月第 N 個星期幾'),
    ], string='週期類型', default='fixed_day')

    auto_visit_day_of_month = fields.Integer(
        string='每月幾號',
        default=1,
        help='1–31，週期類型為「每月固定日期」時使用',
    )
    auto_visit_week_number = fields.Selection([
        ('1', '第 1 週'), ('2', '第 2 週'), ('3', '第 3 週'),
        ('4', '第 4 週'), ('5', '第 5 週'),
    ], string='第幾週', default='1')
    auto_visit_weekday = fields.Selection([
        ('0', '星期一'), ('1', '星期二'), ('2', '星期三'),
        ('3', '星期四'), ('4', '星期五'), ('5', '星期六'), ('6', '星期日'),
    ], string='星期幾', default='0')

    auto_visit_next_date = fields.Date(
        string='下次自動拜訪日期',
        compute='_compute_auto_visit_next_date',
        store=True,
        readonly=False,
        help='由系統依週期設定計算，也可手動覆蓋。',
    )

    @api.depends('visit_ids')
    def _compute_visit_count(self):
        for rec in self:
            rec.visit_count = len(rec.visit_ids)

    # ── 下次日期計算 ─────────────────────────────────────────────
    @api.depends(
        'auto_price_list_visit', 'auto_visit_schedule_type',
        'auto_visit_day_of_month', 'auto_visit_week_number',
        'auto_visit_weekday',
    )
    def _compute_auto_visit_next_date(self):
        today = date.today()
        for rec in self:
            if not rec.auto_price_list_visit:
                rec.auto_visit_next_date = False
            else:
                rec.auto_visit_next_date = rec._calc_next_auto_date(today)

    def _calc_next_auto_date(self, from_date):
        """依週期設定計算下一個拜訪日期（回傳 date，必定 > from_date）。"""
        self.ensure_one()
        if self.auto_visit_schedule_type == 'fixed_day':
            day = max(1, min(int(self.auto_visit_day_of_month or 1), 28))
            # 本月的候選日
            try:
                candidate = from_date.replace(day=day)
            except ValueError:
                candidate = (from_date.replace(day=1) + relativedelta(months=1)).replace(day=day)
            if candidate <= from_date:
                candidate = candidate + relativedelta(months=1)
            # 遇到週末或國定假日，順延至最近工作日
            return self._advance_to_working_day(candidate)

        # weekday_of_month（使用者主動選定星期幾，不做假日順延）
        week_n  = int(self.auto_visit_week_number or '1')
        weekday = int(self.auto_visit_weekday or '0')
        candidate = self._nth_weekday_of_month(from_date.year, from_date.month, week_n, weekday)
        if candidate <= from_date:
            nm = from_date + relativedelta(months=1)
            candidate = self._nth_weekday_of_month(nm.year, nm.month, week_n, weekday)
        return candidate

    def _advance_to_working_day(self, target_date):
        """若 target_date 為週末或台灣國定假日，逐日順延至最近工作日。"""
        # 一次性取出目標日期後 30 天內的假日集合，避免迴圈內重複查 DB
        window_end = target_date + timedelta(days=30)
        holidays = set(
            self.env['dms.public.holiday'].sudo().search([
                ('date', '>=', fields.Date.to_string(target_date)),
                ('date', '<=', fields.Date.to_string(window_end)),
            ]).mapped('date')
        )
        d = target_date
        while d.weekday() >= 5 or d in holidays:   # 5=Sat, 6=Sun
            d += timedelta(days=1)
        return d

    @staticmethod
    def _nth_weekday_of_month(year, month, nth, weekday):
        """回傳指定月份第 nth 個 weekday（0=週一）的日期。"""
        first = date(year, month, 1)
        diff  = (weekday - first.weekday()) % 7
        first_occ = first + timedelta(days=diff)
        target = first_occ + timedelta(weeks=nth - 1)
        if target.month != month:                   # 第5週不存在時退回第4週
            target = first_occ + timedelta(weeks=nth - 2)
        return target

    def action_open_visits(self):
        self.ensure_one()
        return {
            'name': '%s — 拜訪紀錄' % self.name,
            'type': 'ir.actions.act_window',
            'res_model': 'dms.visit',
            'view_mode': 'tree,form,calendar',
            'domain': [('dealer_id', '=', self.id)],
            'context': {
                'default_dealer_id': self.id,
                'default_visitor_id': self.env.user.id,
            },
        }

    def action_create_visit_now(self):
        """立即為此車行建立一筆價格表拜訪紀錄（草稿），並更新下次日期。"""
        self.ensure_one()
        purpose = self.env['dms.visit.purpose'].search(
            ['|', ('code', '=', 'PRICE'), ('name', 'ilike', '價格表')],
            limit=1,
        )
        today = date.today()
        dt_now = fields.Datetime.from_string('%s 09:00:00' % today)

        # 防重複：同日已有相同目的則不再建立
        exists = self.env['dms.visit'].sudo().search_count([
            ('dealer_id',  '=', self.id),
            ('visit_date', '>=', fields.Datetime.from_string('%s 00:00:00' % today)),
            ('visit_date', '<=', fields.Datetime.from_string('%s 23:59:59' % today)),
            ('purpose_id', '=', purpose.id if purpose else False),
        ])
        if not exists:
            visitor = (
                self.price_list_visitor_id.id
                if self.price_list_visitor_id
                else self.env.ref('base.user_admin').id
            )
            visit = self.env['dms.visit'].sudo().create({
                'visit_date': dt_now,
                'dealer_id':  self.id,
                'visitor_id': visitor,
                'purpose_id': purpose.id if purpose else False,
                'state':      'draft',
            })
            # 更新下次週期日期
            self.auto_visit_next_date = self._calc_next_auto_date(today)
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'dms.visit',
                'res_id': visit.id,
                'view_mode': 'form',
                'target': 'current',
            }
        # 已存在則提示
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': '已存在',
                'message': '今日已有一筆相同目的的拜訪紀錄，無需重複建立。',
                'type': 'warning',
                'sticky': False,
            },
        }

    @api.model
    def cron_generate_price_list_visits(self):
        """
        排程方法：每日執行，依 auto_visit_next_date 自動建立「價格表發放」拜訪紀錄。
        - 同車行同日期已有相同目的的拜訪則跳過（防重複）
        - 建立後更新 auto_visit_next_date 至下一個週期
        """
        today = date.today()
        purpose = self.env['dms.visit.purpose'].search(
            ['|', ('code', '=', 'PRICE'), ('name', 'ilike', '價格表')],
            limit=1,
        )

        dealers = self.search([
            ('auto_price_list_visit', '=', True),
            ('active', '=', True),
            ('auto_visit_next_date', '<=', fields.Date.to_string(today)),
        ])

        created = skipped = 0
        for dealer in dealers:
            target = dealer.auto_visit_next_date  # date 型態
            dt_start = fields.Datetime.from_string('%s 00:00:00' % target)
            dt_end   = fields.Datetime.from_string('%s 23:59:59' % target)

            existing = self.env['dms.visit'].sudo().search_count([
                ('dealer_id',  '=', dealer.id),
                ('visit_date', '>=', dt_start),
                ('visit_date', '<=', dt_end),
                ('purpose_id', '=', purpose.id if purpose else False),
            ])
            if existing:
                skipped += 1
            else:
                visitor = (
                    dealer.price_list_visitor_id.id
                    if dealer.price_list_visitor_id
                    else self.env.ref('base.user_admin').id
                )
                self.env['dms.visit'].sudo().create({
                    'visit_date': fields.Datetime.from_string('%s 09:00:00' % target),
                    'dealer_id':  dealer.id,
                    'visitor_id': visitor,
                    'purpose_id': purpose.id if purpose else False,
                    'state':      'draft',
                })
                created += 1

            # 更新下次日期（無論本次是否建立）
            dealer.auto_visit_next_date = dealer._calc_next_auto_date(today)

        _logger.info(
            'DMS 自動價格表拜訪排程：建立 %d 筆，跳過 %d 筆（%s）',
            created, skipped, today,
        )
