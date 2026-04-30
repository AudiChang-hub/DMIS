# -*- coding: utf-8 -*-
"""系統版本資訊頁面 Controller。

以 QWeb 模板渲染，避免 form view 的 "New" 草稿標記。
"""
from odoo import http
from odoo.http import request


class DmsSystemAboutController(http.Controller):

    @http.route('/dms/system/about', type='http', auth='user', website=False)
    def system_about_page(self, **kw):
        About = request.env['dms.system.about'].sudo()
        version_html = About._build_version_html()
        # 從 model 模組取出 _CHANGELOG_HTML
        from odoo.addons.dms_core.models import system_about as sa_module
        changelog_html = sa_module._CHANGELOG_HTML
        values = {
            'version_html': version_html,
            'changelog_html': changelog_html,
        }
        return request.render('dms_core.system_about_page', values)
