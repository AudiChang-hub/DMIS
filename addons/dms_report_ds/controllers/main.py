from odoo import http
from odoo.http import request


class MetabaseController(http.Controller):

    @http.route('/dms_report_ds/metabase_config', type='json', auth='user')
    def metabase_config(self):
        base_url = (
            request.env['ir.config_parameter']
            .sudo()
            .get_param('dms_report_ds.metabase_url', '')
        )
        return {'base_url': base_url}
