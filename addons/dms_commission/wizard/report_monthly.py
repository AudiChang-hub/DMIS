import io
import base64
from odoo import models, fields, api
from odoo.exceptions import ValidationError


class DmsCommissionMonthlyReport(models.TransientModel):
    """月結報表 Wizard"""
    _name = 'dms.commission.monthly.report'
    _description = '月結傭金報表'

    month = fields.Char(
        string='月份', required=True,
        default=lambda self: fields.Date.today().strftime('%Y-%m'),
        help='格式：YYYY-MM，例如 2026-04')
    dealer_ids = fields.Many2many(
        'dms.dealer', string='篩選車行',
        help='留空代表所有車行')
    excel_file = fields.Binary(string='匯出檔案', readonly=True)
    excel_filename = fields.Char(string='檔名', readonly=True)

    @api.constrains('month')
    def _check_month_format(self):
        import re
        for rec in self:
            if not re.match(r'^\d{4}-\d{2}$', rec.month):
                raise ValidationError('月份格式必須為 YYYY-MM，例如 2026-04')

    def _get_records(self):
        domain = [
            ('closed_month', '=', self.month),
            ('state', '=', 'active'),
        ]
        if self.dealer_ids:
            domain.append(('dealer_id', 'in', self.dealer_ids.ids))
        return self.env['dms.commission.record'].search(domain)

    def action_preview(self):
        """在 Odoo 畫面顯示結果（開啟 commission.record 清單）"""
        records = self._get_records()
        return {
            'type': 'ir.actions.act_window',
            'name': f'月結報表 {self.month}',
            'res_model': 'dms.commission.record',
            'view_mode': 'tree,form',
            'domain': [('id', 'in', records.ids)],
            'context': {'search_default_group_dealer': 1},
            'target': 'current',
        }

    def action_export_excel(self):
        """匯出 Excel"""
        try:
            import xlsxwriter
        except ImportError:
            raise ValidationError('請先安裝 xlsxwriter：pip install xlsxwriter')

        records = self._get_records()
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        ws = workbook.add_worksheet('月結傭金')

        # 格式
        bold = workbook.add_format({'bold': True, 'bg_color': '#DCE6F1'})
        money = workbook.add_format({'num_format': '#,##0'})
        center = workbook.add_format({'align': 'center'})

        headers = ['車行', '訂單號', '車型', '能源型式', '結案日期',
                   '基礎傭金', '台數獎金', '合計傭金', '激勵品項', '核銷狀態']
        col_widths = [20, 15, 25, 10, 14, 12, 12, 12, 30, 10]
        for col, (h, w) in enumerate(zip(headers, col_widths)):
            ws.write(0, col, h, bold)
            ws.set_column(col, col, w)

        for row, rec in enumerate(records, 1):
            # 激勵品項摘要
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

            ws.write(row, 0, rec.dealer_id.name or '')
            ws.write(row, 1, rec.sale_order_id.name or '')
            tmpl = rec.product_tmpl_id
            ws.write(row, 2, f"{tmpl.family_name} {tmpl.model_name or ''}".strip() if tmpl else '')
            energy_map = {'oil': '油車', 'electric': '電車'}
            ws.write(row, 3, energy_map.get(tmpl.energy_type, '') if tmpl else '', center)
            ws.write(row, 4, str(rec.closed_date.date()) if rec.closed_date else '', center)
            ws.write(row, 5, rec.base_commission, money)
            ws.write(row, 6, rec.volume_bonus, money)
            ws.write(row, 7, rec.total_commission, money)
            ws.write(row, 8, incentive_summary)
            ws.write(row, 9, delivery_status, center)

        # 合計列
        total_row = len(records) + 1
        ws.write(total_row, 4, '合計', bold)
        ws.write_formula(total_row, 5, f'=SUM(F2:F{total_row})', money)
        ws.write_formula(total_row, 6, f'=SUM(G2:G{total_row})', money)
        ws.write_formula(total_row, 7, f'=SUM(H2:H{total_row})', money)

        workbook.close()
        output.seek(0)
        filename = f'月結傭金報表_{self.month}.xlsx'
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
