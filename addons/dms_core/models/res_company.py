import base64
import logging
import os

from odoo import api, models
from odoo.modules import get_module_resource

_logger = logging.getLogger(__name__)


class ResCompany(models.Model):
    """擴充 res.company，提供 DMIS 系統初始化輔助方法。"""
    _inherit = 'res.company'

    @api.model
    def _action_set_dmis_favicon(self):
        """
        將所有公司的 favicon 更新為 DMIS 自訂圖示。

        此方法透過 data/company_config.xml 的 <function> 呼叫，
        在模組安裝與升級時均會執行（noupdate="0"）。
        繞過 base.main_company 的 noupdate 限制。
        """
        favicon_path = get_module_resource(
            'dms_core', 'static/src/img', 'favicon.png'
        )
        if not favicon_path or not os.path.isfile(favicon_path):
            _logger.warning('dms_core: favicon.png 不存在，跳過 favicon 設定')
            return

        with open(favicon_path, 'rb') as f:
            favicon_b64 = base64.b64encode(f.read()).decode('utf-8')

        companies = self.search([])
        companies.write({'favicon': favicon_b64})
        # 強制刷新 filestore（--stop-after-init 模式下需要明確 commit）
        self.env.cr.commit()
        _logger.info(
            'dms_core: 已更新 %d 間公司的 favicon', len(companies)
        )
