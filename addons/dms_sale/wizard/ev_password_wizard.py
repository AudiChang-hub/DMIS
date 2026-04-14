from odoo import models, fields, api
from odoo.exceptions import UserError


class DmsEvPasswordWizard(models.TransientModel):
    _name = 'dms.ev.password.wizard'
    _description = '電車帳密解鎖驗證'

    order_id = fields.Many2one('dms.sale.order', string='銷售訂單', required=True)
    unlock_password = fields.Char(string='解鎖密碼', required=True)

    def action_verify(self):
        """驗證解鎖密碼，通過後顯示電車帳密。
        密碼由管理員在「設定 > 技術 > 系統參數」設定 key：dms_sale.ev_reveal_password
        """
        self.ensure_one()
        config_pwd = self.env['ir.config_parameter'].sudo().get_param(
            'dms_sale.ev_reveal_password', default=''
        )
        if not config_pwd:
            raise UserError(
                '尚未設定解鎖密碼。\n'
                '請由管理員至「設定 > 技術 > 系統參數」新增：\n'
                'Key: dms_sale.ev_reveal_password\n'
                'Value: <自訂密碼>'
            )
        if self.unlock_password != config_pwd:
            raise UserError('密碼不正確，無法顯示電車帳密。')
        self.order_id.show_ev_passwords = True
        return {'type': 'ir.actions.act_window_close'}
