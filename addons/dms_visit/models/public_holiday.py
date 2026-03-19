from odoo import models, fields


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
