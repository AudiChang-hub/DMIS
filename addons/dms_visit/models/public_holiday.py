import json
import logging
import urllib.request
import urllib.error
from datetime import date

from odoo import models, fields, api

_logger = logging.getLogger(__name__)

# 資料來源：ruyut/TaiwanCalendar（整合自行政院人事行政總處公告）
# https://github.com/ruyut/TaiwanCalendar
_GOV_API_URL_TMPL = (
    'https://raw.githubusercontent.com/ruyut/TaiwanCalendar/master/data/{year}.json'
)


class PublicHoliday(models.Model):
    _name = 'dms.public.holiday'
    _description = '中華民國國定假日'
    _order = 'date'

    date = fields.Date(string='日期', required=True)
    name = fields.Char(string='假日名稱', required=True)
    note = fields.Char(string='備註')

    _sql_constraints = [
        ('date_uniq', 'unique(date)', '同一日期已存在假日或補假紀錄'),
    ]

    @api.model
    def cron_check_holiday_update(self):
        """
        每日排程：檢查政府資料開放平台是否已有尚未同步至本地的年份資料。
        若有，寫入 ir.config_parameter 並發送 bus 即時通知給管理員。
        """
        ICP = self.env['ir.config_parameter'].sudo()
        today = date.today()
        # 檢查未來兩年
        years_to_check = [today.year, today.year + 1]
        pending = []

        for year in years_to_check:
            # 本地已有該年資料則跳過
            local_count = self.sudo().search_count([
                ('date', '>=', '%d-01-01' % year),
                ('date', '<=', '%d-12-31' % year),
            ])
            if local_count > 0:
                continue

            # 查詢 GitHub 是否已有該年 JSON 資料
            url = _GOV_API_URL_TMPL.format(year=year)
            try:
                req = urllib.request.Request(url, headers={'User-Agent': 'DMIS/1.0'})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    records = json.loads(resp.read().decode('utf-8'))
                # 只要有任何放假日，就認定資料已公告
                has_holiday = any(r.get('isHoliday') for r in records)
                if has_holiday:
                    pending.append(str(year))
                    _logger.info('DMS 假日檢查：GitHub 已有 %d 年資料，本地尚未同步。', year)
            except urllib.error.HTTPError as e:
                if e.code != 404:
                    _logger.warning('DMS 假日檢查：無法查詢 %d 年資料 - HTTP %s', year, e.code)
                # 404 表示該年份資料尚未公告，靜默略過
            except Exception as e:
                _logger.warning('DMS 假日檢查：無法查詢 %d 年資料 - %s', year, e)

        # 更新 config param
        old_pending = ICP.get_param('dms_visit.holiday_pending_years', '')
        new_pending = ','.join(pending)
        ICP.set_param('dms_visit.holiday_pending_years', new_pending)

        # 若有新的待同步年份且之前沒有，發送 bus 即時通知
        if pending and old_pending != new_pending:
            years_str = '、'.join(pending)
            self._notify_admins_holiday_update(years_str)

        _logger.info('DMS 假日排程檢查完成：待同步年份 = %s', new_pending or '（無）')

    def _notify_admins_holiday_update(self, years_str):
        """對 dms_visit_admin 群組的已登入使用者發送即時通知。"""
        try:
            admin_group = self.env.ref('dms_visit.group_dms_visit_admin')
            for user in admin_group.users:
                if user.partner_id:
                    self.env['bus.bus']._sendone(
                        user.partner_id,
                        'simple_notification',
                        {
                            'title': '台灣假日資料待更新',
                            'message': (
                                '政府已公告 %s 年的假日資料，'
                                '請至「台灣假日設定」→「同步政府假日資料」進行同步。'
                            ) % years_str,
                            'sticky': True,
                            'type': 'warning',
                        },
                    )
        except Exception as e:
            _logger.warning('DMS 假日通知發送失敗：%s', e)

    @api.model
    def action_check_holiday_update(self):
        """
        手動觸發：檢查政府是否有新假日資料。
        - 若有待同步年份 → 直接開啟同步精靈
        - 若資料已是最新 → 顯示 toast 通知
        """
        ICP = self.env['ir.config_parameter'].sudo()
        pending = ICP.get_param('dms_visit.holiday_pending_years', '')

        # 先做一次即時檢查（快速版，只查年份是否存在）
        if not pending:
            today = date.today()
            for year in [today.year, today.year + 1]:
                local_count = self.sudo().search_count([
                    ('date', '>=', '%d-01-01' % year),
                    ('date', '<=', '%d-12-31' % year),
                ])
                if local_count == 0:
                    try:
                        url = _GOV_API_BASE + (
                            '&filters[%%E8%%A5%%BF%%E5%%85%%83%%E6%%97%%A5%%E6%%9C%%9F]=%d' % year
                        )
                        req = urllib.request.Request(url, headers={'User-Agent': 'DMIS/1.0'})
                        with urllib.request.urlopen(req, timeout=8) as resp:
                            data = json.loads(resp.read().decode('utf-8'))
                        if int((data.get('result') or {}).get('total', 0)) > 0:
                            pending = str(year)
                            ICP.set_param('dms_visit.holiday_pending_years', pending)
                            break
                    except Exception:
                        pass

        if pending:
            years_str = pending.strip(',')
            # 開啟同步精靈，並預填訊息
            wizard = self.env['dms.holiday.sync.wizard'].create({
                'year': int(years_str.split(',')[0]),
            })
            return {
                'type': 'ir.actions.act_window',
                'name': '同步台灣假日（發現 %s 年有新資料）' % years_str,
                'res_model': 'dms.holiday.sync.wizard',
                'res_id': wizard.id,
                'view_mode': 'form',
                'target': 'new',
            }

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': '假日資料已是最新',
                'message': '目前本系統的台灣假日資料已是最新，無需同步。',
                'type': 'success',
                'sticky': False,
            },
        }

