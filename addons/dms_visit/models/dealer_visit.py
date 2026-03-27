import logging

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
    visit_schedule_ids = fields.One2many(
        'dms.visit.schedule', 'dealer_id', string='自動拜訪排程',
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
        """每日執行：補足所有啟用排程在 horizon 內缺漏的拜訪。"""
        schedules = self.env['dms.visit.schedule'].search([
            ('active',           '=', True),
            ('dealer_id.active', '=', True),
        ])
        for schedule in schedules:
            try:
                schedule._topup_future_visits()
            except Exception as e:
                _logger.error(
                    'DMS cron topup 失敗（%s / %s）: %s',
                    schedule.dealer_id.name, schedule.purpose_id.name, e,
                )
        _logger.info('DMS 排程 cron 完成：檢查 %d 筆排程', len(schedules))
