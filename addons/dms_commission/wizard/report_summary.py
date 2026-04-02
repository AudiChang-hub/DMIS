import io
import base64
from odoo import models, fields, api
from odoo.exceptions import ValidationError


class DmsCommissionSummaryReport(models.TransientModel):
    """總報表 Wizard（跨月份日期區間）"""
    _name = 'dms.commission.summary.report'
    _description = '傭金總報表'

    date_from = fields.Date(string='起始日期', required=True)
    date_to = fields.Date(string='結束日期', required=True)
    dealer_ids = fields.Many2many(
        'dms.dealer', string='篩選車行',
        help='留空代表所有車行')
    excel_file = fields.Binary(string='匯出檔案', readonly=True)
    excel_filename = fields.Char(string='檔名', readonly=True)

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for rec in self:
            if rec.date_from and rec.date_to and rec.date_from > rec.date_to:
                raise ValidationError('起始日期不可晚於結束日期')

    def _get_records(self):
        # 改用 closed_date 做日期比較
        date_from_str = str(self.date_from) + ' 00:00:00'
        date_to_str = str(self.date_to) + ' 23:59:59'
        domain = [
            ('closed_date', '>=', date_from_str),
            ('closed_date', '<=', date_to_str),
            ('state', '=', 'active'),
        ]
        if self.dealer_ids:
            domain.append(('dealer_id', 'in', self.dealer_ids.ids))
        return self.env['dms.commission.record'].search(
            domain, order='closed_month, dealer_id')

    def action_preview(self):
        records = self._get_records()
        return {
            'type': 'ir.actions.act_window',
            'name': f'傭金總報表 {self.date_from} ~ {self.date_to}',
            'res_model': 'dms.commission.record',
            'view_mode': 'tree,form',
            'domain': [('id', 'in', records.ids)],
            'target': 'current',
        }

    def action_export_excel(self):
        """匯出 Excel（同月結報表，加月份欄位）"""
        try:
            import xlsxwriter
        except ImportError:
            raise ValidationError('請先安裝 xlsxwriter：pip install xlsxwriter')

        records = self._get_records()
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        ws = workbook.add_worksheet('傭金總報表')

        bold = workbook.add_format({'bold': True, 'bg_color': '#DCE6F1'})
        money = workbook.add_format({'num_format': '#,##0'})
        center = workbook.add_format({'align': 'center'})

        headers = ['月份', '車行', '訂單號', '車型', '能源型式', '結案日期',
                   '基礎傭金', '台數獎金', '合計傭金', '激勵品項', '核銷狀態']
        col_widths = [10, 20, 15, 25, 10, 14, 12, 12, 12, 30, 10]
        for col, (h, w) in enumerate(zip(headers, col_widths)):
            ws.write(0, col, h, bold)
            ws.set_column(col, col, w)

        for row, rec in enumerate(records, 1):
            deliveries = self.env['dms.incentive.delivery'].search([
                ('sale_order_id', '=', rec.sale_order_id.id),
                ('state', '!=', 'voided'),
            ])
            incentive_summary = ', '.join(
                f"{d.incentive_type_id.name}×{d.qty}" for d in deliveries
            ) if deliveries else ''
            pending_count = sum(1 for d in deliveries if d.state == 'pending')
            delivered_count = sum(1 for d in deliveries if d.state == 'delivered')
            delivery_status = f'待給 {pending_count} / 已給 {delivered_count}' if deliveries else ''

            tmpl = rec.product_tmpl_id
            energy_map = {'oil': '油車', 'electric': '電車'}
            ws.write(row, 0, rec.closed_month or '', center)
            ws.write(row, 1, rec.dealer_id.name or '')
            ws.write(row, 2, rec.sale_order_id.name or '')
            ws.write(row, 3, f"{tmpl.family_name} {tmpl.model_name or ''}".strip() if tmpl else '')
            ws.write(row, 4, energy_map.get(tmpl.energy_type, '') if tmpl else '', center)
            ws.write(row, 5, str(rec.closed_date.date()) if rec.closed_date else '', center)
            ws.write(row, 6, rec.base_commission, money)
            ws.write(row, 7, rec.volume_bonus, money)
            ws.write(row, 8, rec.total_commission, money)
            ws.write(row, 9, incentive_summary)
            ws.write(row, 10, delivery_status, center)

        total_row = len(records) + 1
        ws.write(total_row, 5, '合計', bold)
        ws.write_formula(total_row, 6, f'=SUM(G2:G{total_row})', money)
        ws.write_formula(total_row, 7, f'=SUM(H2:H{total_row})', money)
        ws.write_formula(total_row, 8, f'=SUM(I2:I{total_row})', money)

        workbook.close()
        output.seek(0)
        filename = f'傭金總報表_{self.date_from}_{self.date_to}.xlsx'
        self.write({
            'excel_file': base64.b64encode(output.read()),
            'excel_filename': filename,
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
