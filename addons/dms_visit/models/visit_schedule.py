import logging
from datetime import date, timedelta

from dateutil.relativedelta import relativedelta

from odoo import models, fields, api

_logger = logging.getLogger(__name__)

# 預產生未來幾個月的草稿
_GENERATE_MONTHS = 12

# 觸發重新產生的欄位
_SCHEDULE_FIELDS = frozenset({
    'active', 'purpose_id', 'visitor_id',
    'interval_months', 'schedule_type',
    'day_of_month', 'week_number', 'weekday',
})


def _nth_weekday_of_month(year, month, nth, weekday):
    """回傳指定月份第 nth 個 weekday（0=週一）的日期。"""
    first = date(year, month, 1)
    diff = (weekday - first.weekday()) % 7
    first_occ = first + timedelta(days=diff)
    target = first_occ + timedelta(weeks=nth - 1)
    if target.month != month:   # 第5週不存在時退回第4週
        target = first_occ + timedelta(weeks=nth - 2)
    return target


class DmsVisitSchedule(models.Model):
    _name = 'dms.visit.schedule'
    _description = '自動拜訪排程設定'
    _order = 'dealer_id, purpose_id, id'

    dealer_id = fields.Many2one(
        'dms.dealer', string='車行',
        required=True, ondelete='cascade', index=True,
    )
    active = fields.Boolean(string='啟用', default=True)
    purpose_id = fields.Many2one(
        'dms.visit.purpose', string='拜訪目的',
        required=True, ondelete='restrict',
    )
    visitor_id = fields.Many2one(
        'res.users', string='拜訪業務人員',
        help='留空則以系統管理員建立。',
    )
    interval_months = fields.Selection([
        ('1',  '每個月'),
        ('2',  '每兩個月'),
        ('3',  '每季（每三個月）'),
        ('6',  '每半年'),
        ('12', '每年'),
    ], string='拜訪頻率', default='1', required=True)
    schedule_type = fields.Selection([
        ('fixed_day',        '固定日期（每月幾號）'),
        ('weekday_of_month', '第 N 個星期幾'),
    ], string='日期選取方式', default='fixed_day', required=True)
    day_of_month = fields.Integer(
        string='每月幾號', default=1,
        help='1–28，日期選取方式為「固定日期」時使用（遇假日自動順延）',
    )
    week_number = fields.Selection([
        ('1', '第 1 週'), ('2', '第 2 週'), ('3', '第 3 週'),
        ('4', '第 4 週'), ('5', '第 5 週'),
    ], string='第幾週', default='1')
    weekday = fields.Selection([
        ('0', '星期一'), ('1', '星期二'), ('2', '星期三'),
        ('3', '星期四'), ('4', '星期五'), ('5', '星期六'), ('6', '星期日'),
    ], string='星期幾', default='0')

    # 人性化摘要（顯示於清單）
    schedule_summary = fields.Char(
        string='週期摘要',
        compute='_compute_schedule_summary',
        store=False,
    )
    # 下一筆預計日期
    next_date = fields.Date(
        string='下一筆排程日期',
        compute='_compute_next_date',
        store=False,
    )

    # ── computed ─────────────────────────────────────────────────
    @api.depends('interval_months', 'schedule_type', 'day_of_month', 'week_number', 'weekday')
    def _compute_schedule_summary(self):
        interval_label = dict(self._fields['interval_months'].selection)
        weekday_label  = dict(self._fields['weekday'].selection)
        week_label     = dict(self._fields['week_number'].selection)
        for rec in self:
            freq = interval_label.get(rec.interval_months, '')
            if rec.schedule_type == 'fixed_day':
                detail = '每月 %d 號' % (rec.day_of_month or 1)
            else:
                w = week_label.get(rec.week_number, '')
                d = weekday_label.get(rec.weekday, '')
                detail = '%s%s' % (w, d)
            rec.schedule_summary = '%s · %s' % (freq, detail)

    @api.depends('active', 'schedule_type', 'day_of_month', 'week_number', 'weekday', 'interval_months')
    def _compute_next_date(self):
        today = date.today()
        for rec in self:
            if not rec.active or not rec.purpose_id:
                rec.next_date = False
            else:
                try:
                    rec.next_date = rec._calc_next_date(today)
                except Exception:
                    rec.next_date = False

    # ── ORM hooks ────────────────────────────────────────────────
    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            if rec.active:
                rec._regenerate_future_visits()
        return records

    def write(self, vals):
        deactivating = 'active' in vals and not vals['active']
        result = super().write(vals)
        if deactivating:
            for rec in self:
                rec._cancel_future_visits()
        elif bool(_SCHEDULE_FIELDS & set(vals.keys())):
            for rec in self:
                if rec.active:
                    rec._regenerate_future_visits()
        return result

    def unlink(self):
        for rec in self:
            rec._cancel_future_visits()
        return super().unlink()

    # ── 核心排程邏輯 ─────────────────────────────────────────────
    def _generate_all_dates(self):
        """計算未來 horizon 內所有排程日期。"""
        self.ensure_one()
        interval = int(self.interval_months or '1')
        months = max(_GENERATE_MONTHS, interval * 2)
        today = date.today()
        horizon = today + relativedelta(months=months)

        holidays = set(self.env['dms.public.holiday'].sudo().search([
            ('date', '>=', fields.Date.to_string(today)),
            ('date', '<=', fields.Date.to_string(horizon + timedelta(days=45))),
        ]).mapped('date'))

        dates = []
        cursor = today - timedelta(days=1)
        while True:
            next_d = self._calc_next_date(cursor, holidays=holidays)
            if next_d > horizon:
                break
            dates.append(next_d)
            cursor = next_d
        return dates

    def _regenerate_future_visits(self):
        """刪除本排程未來草稿，依最新設定重新產生。"""
        self.ensure_one()
        today_dt = fields.Datetime.from_string('%s 00:00:00' % date.today())
        self.env['dms.visit'].sudo().search([
            ('schedule_id', '=', self.id),
            ('state',       '=', 'draft'),
            ('visit_date',  '>=', today_dt),
        ]).unlink()

        visitor = (
            self.visitor_id.id
            if self.visitor_id
            else self.env.ref('base.user_admin').id
        )
        vals_list = [{
            'visit_date':        fields.Datetime.from_string('%s 04:00:00' % d),
            'dealer_id':         self.dealer_id.id,
            'visitor_id':        visitor,
            'purpose_id':        self.purpose_id.id,
            'state':             'draft',
            'is_auto_generated': True,
            'schedule_id':       self.id,
        } for d in self._generate_all_dates()]

        if vals_list:
            self.env['dms.visit'].sudo().create(vals_list)
        _logger.info(
            'DMS 排程：%s / %s 重新產生 %d 筆拜訪草稿',
            self.dealer_id.name, self.purpose_id.name, len(vals_list),
        )

    def _cancel_future_visits(self):
        """停用或刪除時，取消未來所有草稿（保留歷史）。"""
        today_dt = fields.Datetime.from_string('%s 00:00:00' % date.today())
        self.env['dms.visit'].sudo().search([
            ('schedule_id', '=', self.id),
            ('state',       '=', 'draft'),
            ('visit_date',  '>=', today_dt),
        ]).write({'state': 'cancel'})

    def _topup_future_visits(self):
        """補足 horizon 內缺漏的排程拜訪（cron 每日呼叫）。"""
        self.ensure_one()
        visitor = (
            self.visitor_id.id
            if self.visitor_id
            else self.env.ref('base.user_admin').id
        )
        for d in self._generate_all_dates():
            dt_s = fields.Datetime.from_string('%s 00:00:00' % d)
            dt_e = fields.Datetime.from_string('%s 23:59:59' % d)
            exists = self.env['dms.visit'].sudo().search_count([
                ('schedule_id', '=',  self.id),
                ('visit_date',  '>=', dt_s),
                ('visit_date',  '<=', dt_e),
                ('state',       '!=', 'cancel'),
            ])
            if not exists:
                self.env['dms.visit'].sudo().create({
                    'visit_date':        fields.Datetime.from_string('%s 04:00:00' % d),
                    'dealer_id':         self.dealer_id.id,
                    'visitor_id':        visitor,
                    'purpose_id':        self.purpose_id.id,
                    'state':             'draft',
                    'is_auto_generated': True,
                    'schedule_id':       self.id,
                })

    # ── 日期計算工具 ─────────────────────────────────────────────
    def _calc_next_date(self, from_date, holidays=None):
        """回傳嚴格大於 from_date 的下一個排程日期。"""
        self.ensure_one()
        interval = int(self.interval_months or '1')
        if self.schedule_type == 'fixed_day':
            day = max(1, min(int(self.day_of_month or 1), 28))
            try:
                candidate = from_date.replace(day=day)
            except ValueError:
                candidate = (from_date.replace(day=1) + relativedelta(months=1)).replace(day=day)
            if candidate <= from_date:
                candidate = candidate + relativedelta(months=interval)
            return self._advance_to_working_day(candidate, holidays=holidays)

        week_n  = int(self.week_number or '1')
        weekday = int(self.weekday or '0')
        candidate = _nth_weekday_of_month(from_date.year, from_date.month, week_n, weekday)
        if candidate <= from_date:
            nm = from_date + relativedelta(months=interval)
            candidate = _nth_weekday_of_month(nm.year, nm.month, week_n, weekday)
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
        while d.weekday() >= 5 or d in holidays:
            d += timedelta(days=1)
        return d

    # ── 按鈕 ─────────────────────────────────────────────────────
    def action_regenerate_visits(self):
        """手動重建本排程的未來草稿。"""
        self.ensure_one()
        self._regenerate_future_visits()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': '完成',
                'message': '已重新產生「%s」未來 %d 個月的排程拜訪草稿。' % (
                    self.purpose_id.name, _GENERATE_MONTHS,
                ),
                'type': 'success', 'sticky': False,
            },
        }
