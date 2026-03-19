from odoo import http
from odoo.http import request


class HolidayNoticeController(http.Controller):

    @http.route('/dms/holiday_sync_notice', type='http', auth='user')
    def holiday_sync_notice(self, **kwargs):
        """
        供假日清單的 <banner route> 呼叫。
        當有待同步年份時回傳橙色提醒橫幅，否則回傳空字串。
        """
        pending = request.env['ir.config_parameter'].sudo().get_param(
            'dms_visit.holiday_pending_years', ''
        )
        if not pending:
            return ''
        years = pending.strip(',')
        html = (
            '<div class="alert alert-warning o_holiday_sync_banner" '
            'style="margin:0 0 8px 0; padding:8px 12px; display:flex; '
            'align-items:center; gap:12px;">'
            '<i class="fa fa-calendar-times-o" style="font-size:16px;"></i>'
            '<span style="flex:1;">'
            '<strong>⚠ 政府已公告 %s 年的假日資料，尚未同步至本系統。</strong>'
            '&nbsp;請從上方「動作」選單點選「同步政府假日資料」進行更新。'
            '</span>'
            '</div>'
        ) % years
        return html
