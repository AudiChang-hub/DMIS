import io
import csv
import base64
from odoo import api, models, fields
from odoo.exceptions import UserError


class DmsPartCatalogImportWizard(models.TransientModel):
    """M6-A：CSV 批次匯入精靈
    CSV 格式（UTF-8）：
    catalog_name,section_code,section_name,section_category,seq_no,part_number,part_name,uom,qty,list_price
    """
    _name = 'dms.part.catalog.import.wizard'
    _description = '零件目錄 CSV 匯入精靈'

    template_id = fields.Many2one(
        'dms.product.template',
        string='車型',
        required=True,
        help='此 CSV 所屬車型',
    )
    engine_prefix = fields.Char(string='引擎號碼前綴', help='如：DD')
    setup_date = fields.Date(string='設變日期')
    csv_file = fields.Binary(string='CSV 檔案', required=True)
    csv_filename = fields.Char(string='檔案名稱')
    import_log = fields.Text(string='匯入記錄', readonly=True)

    def action_import(self):
        self.ensure_one()
        if not self.csv_file:
            raise UserError('請上傳 CSV 檔案')

        raw = base64.b64decode(self.csv_file)
        # 支援 UTF-8 BOM
        text = raw.decode('utf-8-sig')
        reader = csv.DictReader(io.StringIO(text))

        required_cols = {'catalog_name', 'section_code', 'section_name',
                         'section_category', 'seq_no', 'part_number', 'part_name'}
        if not required_cols.issubset(set(reader.fieldnames or [])):
            missing = required_cols - set(reader.fieldnames or [])
            raise UserError(f'CSV 缺少必要欄位：{", ".join(missing)}\n'
                            f'必要欄位：catalog_name, section_code, section_name, '
                            f'section_category, seq_no, part_number, part_name')

        catalog_cache = {}
        section_cache = {}
        part_cache = {}
        created_parts = 0
        created_lines = 0
        logs = []

        for row_num, row in enumerate(reader, start=2):
            catalog_name = (row.get('catalog_name') or '').strip()
            section_code = (row.get('section_code') or '').strip().upper()
            section_name = (row.get('section_name') or '').strip()
            section_cat = (row.get('section_category') or 'engine').strip().lower()
            seq_no = int(row.get('seq_no') or 0)
            part_number = (row.get('part_number') or '').strip()
            part_name = (row.get('part_name') or '').strip()
            uom = (row.get('uom') or '個').strip()
            qty = float(row.get('qty') or 1)
            try:
                list_price = float(row.get('list_price') or 0)
            except ValueError:
                list_price = 0.0

            if not catalog_name or not section_code or not part_number:
                logs.append(f'第 {row_num} 行跳過：catalog_name/section_code/part_number 不可為空')
                continue

            # 找或建立 catalog
            if catalog_name not in catalog_cache:
                catalog = self.env['dms.part.catalog'].search(
                    [('name', '=', catalog_name), ('template_id', '=', self.template_id.id)],
                    limit=1,
                )
                if not catalog:
                    catalog = self.env['dms.part.catalog'].create({
                        'name': catalog_name,
                        'template_id': self.template_id.id,
                        'engine_prefix': self.engine_prefix or False,
                        'setup_date': self.setup_date or False,
                    })
                    logs.append(f'建立目錄：{catalog_name}')
                catalog_cache[catalog_name] = catalog
            catalog = catalog_cache[catalog_name]

            # 找或建立 section
            section_key = (catalog.id, section_code)
            if section_key not in section_cache:
                section = self.env['dms.part.catalog.section'].search(
                    [('catalog_id', '=', catalog.id), ('code', '=', section_code)],
                    limit=1,
                )
                if not section:
                    if section_cat not in ('engine', 'frame'):
                        section_cat = 'engine'
                    section = self.env['dms.part.catalog.section'].create({
                        'catalog_id': catalog.id,
                        'code': section_code,
                        'name': section_name,
                        'category': section_cat,
                    })
                    logs.append(f'建立分區：{section_code} {section_name}')
                section_cache[section_key] = section
            section = section_cache[section_key]

            # 找或建立 dms.part
            if part_number not in part_cache:
                part = self.env['dms.part'].search(
                    [('part_number', '=', part_number)], limit=1)
                if not part:
                    part = self.env['dms.part'].create({
                        'name': part_name,
                        'part_number': part_number,
                        'uom': uom,
                        'list_price': list_price,
                        'part_type': 'vehicle_part',
                    })
                    created_parts += 1
                part_cache[part_number] = part
            part = part_cache[part_number]

            # 建立 catalog line
            existing = self.env['dms.part.catalog.line'].search([
                ('section_id', '=', section.id),
                ('seq_no', '=', seq_no),
                ('part_id', '=', part.id),
            ], limit=1)
            if not existing:
                self.env['dms.part.catalog.line'].create({
                    'section_id': section.id,
                    'seq_no': seq_no,
                    'part_id': part.id,
                    'part_number': part_number,
                    'name': part_name,
                    'qty': qty,
                    'list_price': list_price,
                })
                created_lines += 1

        summary = (f'匯入完成：新建零件 {created_parts} 筆，新建目錄明細 {created_lines} 筆\n'
                   + '\n'.join(logs))
        self.import_log = summary

        return {
            'name': 'CSV 匯入精靈',
            'type': 'ir.actions.act_window',
            'res_model': 'dms.part.catalog.import.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
