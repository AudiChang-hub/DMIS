import base64
import logging
import re

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# 欄位自動偵測關鍵字
_COL_KEYWORDS = {
    'seq':         ['序號', '項次', 'seq', 'item', 'no.', '件次'],
    'part_number': ['料號', '件號', 'part no', 'part number', '零件號', '零件編號', '品番'],
    'name':        ['名稱', '品名', '零件名稱', 'description', 'part name', '品名稱'],
    'qty':         ['數量', 'qty', 'quantity', '用量', '員數'],
    'price':       ['售價', '定價', '單價', 'price', '原廠售價', '參考售價'],
}


def _best_col_idx(headers, key):
    """找到最符合關鍵字的欄索引，找不到回傳 -1"""
    kws = _COL_KEYWORDS[key]
    best, best_score = -1, 0
    for i, h in enumerate(headers):
        h_lower = (h or '').strip().lower()
        score = sum(1 for kw in kws if kw.lower() in h_lower)
        if score > best_score:
            best, best_score = i, score
    return best


class DmsPartCatalogPdfWizard(models.TransientModel):
    _name = 'dms.part.catalog.pdf.wizard'
    _description = '零件目錄 PDF 批次建立精靈'

    catalog_id = fields.Many2one(
        'dms.part.catalog', string='目錄', required=True, readonly=True
    )
    pdf_file = fields.Binary(string='目錄 PDF', required=True)
    pdf_filename = fields.Char(string='PDF 檔名')

    page_mode = fields.Selection(
        [
            ('auto', '每頁含圖 + 表格（最常見）'),
            ('pair', '兩頁一組（奇數頁=圖，偶數頁=表格）'),
        ],
        string='頁面格式',
        default='auto',
        required=True,
        help='如果爆炸圖和零件表格在同一頁，選「每頁含圖+表格」；\n'
             '如果圖和表格分別在相鄰兩頁，選「兩頁一組」。',
    )
    has_header_row = fields.Boolean(
        string='第一列為欄位標題（如料號/名稱/數量）',
        default=True,
        help='勾選後系統會自動跳過第一列標題行',
    )

    col_headers_display = fields.Char(
        string='PDF 中偵測到的欄位',
        readonly=True,
        help='上傳 PDF 後自動顯示，依此調整下方欄索引',
    )
    col_seq = fields.Integer(
        string='序號欄（-1 = 無）', default=0,
        help='爆炸圖上的數字序號，-1 表示 PDF 無此欄',
    )
    col_part_number = fields.Integer(
        string='料號欄', default=1,
        help='零件料號所在欄，從 0 開始計',
    )
    col_name = fields.Integer(
        string='名稱欄', default=2,
        help='零件名稱所在欄',
    )
    col_qty = fields.Integer(
        string='用量欄（-1 = 無）', default=3,
        help='用量/數量所在欄，-1 表示無此欄（預設用量為 1）',
    )
    col_price = fields.Integer(
        string='售價欄（-1 = 無）', default=-1,
        help='公告售價所在欄，-1 表示無此欄',
    )

    section_prefix = fields.Selection(
        [
            ('E', '引擎類 (E01, E02...)'),
            ('F', '車架類 (F01, F02...)'),
            ('A', 'A01, A02...'),
            ('custom', '自訂前綴'),
        ],
        string='分區代號前綴',
        default='E',
        required=True,
    )
    section_prefix_custom = fields.Char(string='自訂前綴字元')

    state = fields.Selection(
        [('draft', '等待匯入'), ('done', '完成')], default='draft'
    )
    import_log = fields.Text(string='匯入結果', readonly=True)

    # ── onchange: 上傳後自動分析欄位 ──────────────────────────────────────

    @api.onchange('pdf_file')
    def _onchange_pdf_file(self):
        if not self.pdf_file:
            self.col_headers_display = False
            return
        try:
            import fitz  # noqa
        except ImportError:
            return {
                'warning': {
                    'title': 'PyMuPDF 未安裝',
                    'message': '請執行 docker compose build 重建映像後再試。',
                }
            }

        try:
            import fitz  # noqa - confirmed import
            pdf_bytes = base64.b64decode(self.pdf_file)
            doc = fitz.open(stream=pdf_bytes, filetype='pdf')

            headers = None
            for page_num in range(min(len(doc), 10)):
                page = doc[page_num]
                tbl_finder = page.find_tables()
                if tbl_finder.tables:
                    rows = tbl_finder.tables[0].extract()
                    if rows and rows[0] and any(c for c in rows[0] if c):
                        headers = [
                            str(c).strip() if c else f'欄{i}'
                            for i, c in enumerate(rows[0])
                        ]
                        break
            doc.close()

            if not headers:
                self.col_headers_display = '⚠ 前 10 頁未偵測到表格，請確認 PDF 格式或嘗試手動填入欄索引'
                return

            self.col_headers_display = '  |  '.join(
                f'欄{i}: {h}' for i, h in enumerate(headers)
            )

            # 自動填入欄位對應（僅在 >= 0 時更新）
            self.col_seq = _best_col_idx(headers, 'seq')
            self.col_part_number = max(_best_col_idx(headers, 'part_number'), 0)
            self.col_name = max(_best_col_idx(headers, 'name'), 0)
            self.col_qty = _best_col_idx(headers, 'qty')
            self.col_price = _best_col_idx(headers, 'price')

        except Exception as e:
            _logger.warning('PDF 欄位分析失敗: %s', e)
            self.col_headers_display = f'分析錯誤：{e}'

    # ── helper ───────────────────────────────────────────────────────────

    def _cell(self, row, idx):
        if idx < 0 or idx >= len(row):
            return ''
        v = row[idx]
        return str(v).strip() if v is not None else ''

    def _extract_section_name(self, page, table_bbox):
        """嘗試從表格上方文字找出分區名稱"""
        try:
            import fitz
            pr = page.rect
            above = fitz.Rect(pr.x0, pr.y0, pr.x1, table_bbox[1])
            text = page.get_textbox(above).strip()
            lines = [l.strip() for l in text.split('\n') if l.strip()]
            for line in reversed(lines):
                if len(line) > 1 and not re.fullmatch(r'[\d\s\.\-]+', line):
                    return line[:60]
        except Exception:
            pass
        return ''

    # ── main import ──────────────────────────────────────────────────────

    def action_import(self):
        self.ensure_one()

        if not self.pdf_file:
            raise UserError('請先上傳目錄 PDF 檔案。')
        if self.col_part_number < 0 and self.col_name < 0:
            raise UserError('「料號欄」和「名稱欄」至少需設定一個（≥ 0）。')

        try:
            import fitz
        except ImportError:
            raise UserError('PyMuPDF 未安裝，請執行 docker compose build 重建映像。')

        pdf_bytes = base64.b64decode(self.pdf_file)
        doc = fitz.open(stream=pdf_bytes, filetype='pdf')
        total = len(doc)

        prefix = (
            self.section_prefix
            if self.section_prefix != 'custom'
            else (self.section_prefix_custom or 'E')
        )
        existing_count = len(self.catalog_id.section_ids)

        sections_created = 0
        lines_created = 0
        parts_created = 0
        skipped_rows = 0

        if self.page_mode == 'pair':
            page_pairs = [(i, i + 1) for i in range(0, total - 1, 2)]
        else:
            page_pairs = [(i, i) for i in range(total)]

        for img_idx, tbl_idx in page_pairs:
            if img_idx >= total or tbl_idx >= total:
                continue

            tbl_page = doc[tbl_idx]
            tbl_finder = tbl_page.find_tables()
            if not tbl_finder.tables:
                continue

            best_table = max(tbl_finder.tables, key=lambda t: len(t.rows))
            rows = best_table.extract()
            if not rows:
                continue

            data_rows = rows[1:] if self.has_header_row else rows
            data_rows = [
                r for r in data_rows
                if any(v for v in r if v and str(v).strip())
            ]
            if not data_rows:
                continue

            # 爆炸圖：渲染圖片頁
            img_page = doc[img_idx]
            pix = img_page.get_pixmap(dpi=120)
            img_b64 = base64.b64encode(pix.tobytes('png'))

            # 分區名稱：嘗試從頁面取標題
            section_num = existing_count + sections_created + 1
            section_code = f'{prefix}{section_num:02d}'
            section_name = (
                self._extract_section_name(tbl_page, best_table.bbox)
                or f'第 {section_num:02d} 部分'
            )

            section = self.env['dms.part.catalog.section'].create({
                'catalog_id': self.catalog_id.id,
                'code': section_code,
                'name': section_name,
                'category': 'engine',
                'diagram_image': img_b64,
                'sequence': section_num * 10,
            })
            sections_created += 1

            # 建立零件明細
            for row in data_rows:
                part_number = self._cell(row, self.col_part_number)
                name = self._cell(row, self.col_name)

                if not part_number and not name:
                    skipped_rows += 1
                    continue

                # qty
                qty = 1.0
                raw_qty = self._cell(row, self.col_qty)
                if raw_qty:
                    try:
                        qty = float(re.sub(r'[^\d.]', '', raw_qty)) or 1.0
                    except Exception:
                        qty = 1.0

                # price
                price = 0.0
                raw_price = self._cell(row, self.col_price)
                if raw_price:
                    try:
                        price = float(re.sub(r'[^\d.]', '', raw_price)) or 0.0
                    except Exception:
                        price = 0.0

                # seq_no
                seq_no = 0
                raw_seq = self._cell(row, self.col_seq)
                if raw_seq:
                    try:
                        seq_no = int(re.sub(r'[^\d]', '', raw_seq)) or 0
                    except Exception:
                        seq_no = 0

                # 找或建立 dms.part
                part = False
                if part_number:
                    part = self.env['dms.part'].search(
                        [('part_number', '=', part_number)], limit=1
                    )
                if not part:
                    try:
                        part = self.env['dms.part'].create({
                            'part_number': part_number or (name[:20] if name else '?'),
                            'name': name or part_number,
                            'part_type': 'vehicle_part',
                            'list_price': price,
                        })
                        parts_created += 1
                    except Exception as e:
                        _logger.warning('建立 dms.part 失敗（料號=%s）: %s', part_number, e)
                        skipped_rows += 1
                        continue

                self.env['dms.part.catalog.line'].create({
                    'section_id': section.id,
                    'seq_no': seq_no,
                    'part_id': part.id,
                    'qty': qty,
                    'list_price': price or part.list_price,
                })
                lines_created += 1

        doc.close()

        skip_note = f'・略過空白列：{skipped_rows} 筆\n' if skipped_rows else ''
        self.import_log = (
            f'✅  匯入完成\n\n'
            f'・建立分區（爆炸圖）：{sections_created} 個\n'
            f'・建立零件明細：{lines_created} 筆\n'
            f'・新增零件主檔：{parts_created} 筆（已存在料號直接連結）\n'
            f'{skip_note}\n'
            f'請至目錄頁面確認，可修改分區名稱與零件資料。'
        )
        self.state = 'done'

        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
