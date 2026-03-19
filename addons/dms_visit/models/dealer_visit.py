import logging
from datetime import date, timedelta

from dateutil.relativedelta import relativedelta

from odoo import models, fields, api

_logger = logging.getLogger(__name__)


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
            return candidate

        # weekday_of_month
        week_n  = int(self.auto_visit_week_number or '1')
        weekday = int(self.auto_visit_weekday or '0')
        candidate = self._nth_weekday_of_month(from_date.year, from_date.month, week_n, weekday)
        if candidate <= from_date:
            nm = from_date + relativedelta(months=1)
            candidate = self._nth_weekday_of_month(nm.year, nm.month, week_n, weekday)
        return candidate

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
