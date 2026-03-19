import logging
import json
from datetime import date

import urllib.request
import urllib.error

from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# 政府資料開放平台：中華民國政府行政機關辦公日曆表
# https://data.gov.tw/dataset/14718
_API_URL = (
    'https://data.gov.tw/api/v2/rest/datastore/382000000A-000077-001'
    '?filters[%E6%98%AF%E5%90%A6%E6%94%BE%E5%81%87%E6%97%A5]=2'  # 是否放假日=2 表示放假
    '&limit=500'
    '&fields=%E8%A5%BF%E5%85%83%E6%97%A5%E6%9C%9F,%E5%81%87%E6%9C%9F%E5%90%8D%E7%A8%B1'
)

# 欄位名稱（API 回傳的中文 key）
_COL_DATE = '西元日期'
_COL_NAME = '假期名稱'
# 是否放假欄位值：'2' 代表放假
_COL_IS_HOLIDAY = '是否放假日'


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
        if year < 2017 or year > 2030:
            raise UserError('目前支援的同步年份範圍為 2017–2030。')

        # ── 呼叫政府開放資料 API ────────────────────────────────
        url = _API_URL + '&filters[%E8%A5%BF%E5%85%83%E6%97%A5%E6%9C%9F]=' + str(year)
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'DMIS/1.0'})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode('utf-8'))
        except urllib.error.URLError as e:
            raise UserError(
                '無法連線至政府開放資料平台，請確認伺服器網路連線。\n錯誤：%s' % e
            ) from e
        except Exception as e:
            raise UserError('讀取假日資料失敗：%s' % e) from e

        records = (data.get('result') or {}).get('records') or []
        if not records:
            raise UserError(
                '政府開放資料平台未回傳 %d 年的假日資料，'
                '可能尚未公告，請稍後再試或手動輸入。' % year
            )

        # ── 整理資料，只取「放假日=2」的紀錄 ──────────────────
        holiday_map = {}   # date_str -> name
        for row in records:
            if str(row.get(_COL_IS_HOLIDAY, '')).strip() != '2':
                continue
            date_str = str(row.get(_COL_DATE, '')).strip()  # e.g. '20260101'
            name = str(row.get(_COL_NAME, '')).strip() or '國定假日'
            if len(date_str) != 8 or not date_str.isdigit():
                continue
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
