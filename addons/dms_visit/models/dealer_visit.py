import logging
from datetime import date

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
        help='勾選後，排程每月自動為此車行建立一筆「價格表發放」拜訪紀錄。',
    )
    price_list_visitor_id = fields.Many2one(
        'res.users',
        string='自動拜訪業務人員',
        help='月度自動建立拜訪時所指定的拜訪人員；留空則以系統管理員建立。',
    )

    @api.depends('visit_ids')
    def _compute_visit_count(self):
        for rec in self:
            rec.visit_count = len(rec.visit_ids)

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
        排程方法：每月執行一次，為啟用自動拜訪的車行建立「價格表發放」拜訪紀錄。
        同一車行、同一月份僅建立一筆，已存在則跳過。
        """
        today = date.today()
        # 當月第一天 00:00:00 UTC 作為拜訪日期
        month_start = fields.Datetime.from_string(
            '%04d-%02d-01 00:00:00' % (today.year, today.month)
        )

        # 找「價格表」拜訪目的（code='PRICE' 或名稱含「價格表」）
        purpose = self.env['dms.visit.purpose'].search(
            ['|', ('code', '=', 'PRICE'), ('name', 'ilike', '價格表')],
            limit=1,
        )

        # 找所有需要自動拜訪的啟用車行
        dealers = self.search([
            ('auto_price_list_visit', '=', True),
            ('active', '=', True),
        ])

        created = 0
        skipped = 0
        for dealer in dealers:
            # 去重：同車行同月份已有相同目的的拜訪
            existing = self.env['dms.visit'].sudo().search_count([
                ('dealer_id', '=', dealer.id),
                ('visit_date', '>=', month_start),
                ('visit_date', '<', fields.Datetime.from_string(
                    '%04d-%02d-01 00:00:00' % (
                        (today.year + 1) if today.month == 12 else today.year,
                        1 if today.month == 12 else today.month + 1,
                    )
                )),
                ('purpose_id', '=', purpose.id if purpose else False),
            ])
            if existing:
                skipped += 1
                continue

            visitor_id = (
                dealer.price_list_visitor_id.id
                if dealer.price_list_visitor_id
                else self.env.ref('base.user_admin').id
            )
            self.env['dms.visit'].sudo().create({
                'visit_date': month_start,
                'dealer_id': dealer.id,
                'visitor_id': visitor_id,
                'purpose_id': purpose.id if purpose else False,
                'state': 'done',
            })
            created += 1

        _logger.info(
            'DMS 月度價格表拜訪排程：建立 %d 筆，跳過 %d 筆（%04d-%02d）',
            created, skipped, today.year, today.month,
        )
