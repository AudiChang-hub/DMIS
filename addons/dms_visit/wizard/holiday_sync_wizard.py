import logging
import json
from datetime import date

import urllib.request
import urllib.error

from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# 資料來源：ruyut/TaiwanCalendar（整合自行政院人事行政總處公告）
# https://github.com/ruyut/TaiwanCalendar
_API_URL_TMPL = (
    'https://raw.githubusercontent.com/ruyut/TaiwanCalendar/master/data/{year}.json'
)

# 支援年份範圍（資料庫從 2017 年開始）
_YEAR_MIN = 2017
_YEAR_MAX = 2030


class HolidaySyncWizard(models.TransientModel):
    _name = 'dms.holiday.sync.wizard'
    _description = '台灣假日同步精靈'

    year = fields.Integer(
        string='同步年份',
        default=lambda self: date.today().year + 1,
        required=True,
    )
    result_message = fields.Text(string='同步結果', readonly=True)
    state = fields.Selection(
        [('input', '待同步'), ('done', '完成')],
        default='input',
        readonly=True,
    )

    def action_sync(self):
        self.ensure_one()
        year = self.year
        if year < _YEAR_MIN or year > _YEAR_MAX:
            raise UserError('目前支援的同步年份範圍為 %d–%d。' % (_YEAR_MIN, _YEAR_MAX))

        # ── 下載 TaiwanCalendar JSON ─────────────────────────────
        url = _API_URL_TMPL.format(year=year)
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'DMIS/1.0'})
            with urllib.request.urlopen(req, timeout=15) as resp:
                records = json.loads(resp.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise UserError(
                    '%d 年的假日資料尚未公告，請稍後再試或手動輸入。' % year
                ) from e
            raise UserError(
                '無法連線至資料來源，請確認伺服器網路連線。\n錯誤：%s' % e
            ) from e
        except urllib.error.URLError as e:
            raise UserError(
                '無法連線至資料來源，請確認伺服器網路連線。\n錯誤：%s' % e
            ) from e
        except Exception as e:
            raise UserError('讀取假日資料失敗：%s' % e) from e

        if not isinstance(records, list) or not records:
            raise UserError('%d 年的假日資料為空，請確認資料來源是否正常。' % year)

        # ── 整理資料，只取 isHoliday=True 的紀錄 ───────────────
        # 格式：[{"date": "20250101", "isHoliday": true, "description": "開國紀念日"}, ...]
        holiday_map = {}   # 'YYYY-MM-DD' -> name
        for row in records:
            if not row.get('isHoliday'):
                continue
            date_str = str(row.get('date', '')).strip()  # e.g. '20260101'
            if len(date_str) != 8 or not date_str.isdigit():
                continue
            name = str(row.get('description', '')).strip() or '例假日'
            formatted = '%s-%s-%s' % (date_str[:4], date_str[4:6], date_str[6:])
            holiday_map[formatted] = name

        if not holiday_map:
            raise UserError('%d 年的放假日資料為空，請確認資料來源是否正常。' % year)

        # ── 寫入 DB（upsert：存在則更新名稱，不存在則新增）────
        Holiday = self.env['dms.public.holiday'].sudo()
        existing = {
            r.date: r
            for r in Holiday.search([
                ('date', '>=', '%d-01-01' % year),
                ('date', '<=', '%d-12-31' % year),
            ])
        }

        created = updated = 0
        for date_str, name in holiday_map.items():
            d = fields.Date.from_string(date_str)
            if d in existing:
                if existing[d].name != name:
                    existing[d].write({'name': name})
                    updated += 1
            else:
                Holiday.create({'date': d, 'name': name})
                created += 1

        msg = '%d 年假日同步完成：新增 %d 筆、更新 %d 筆（共 %d 筆放假日）。' % (
            year, created, updated, len(holiday_map),
        )
        _logger.info('DMS 假日同步：%s', msg)

        self.write({'result_message': msg, 'state': 'done'})
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_close(self):
        return {'type': 'ir.actions.act_window_close'}
