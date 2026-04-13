import base64
import logging
import re

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# 有框線表格 PDF 的欄位自動偵測關鍵字
_COL_KEYWORDS = {
    'seq':         ['序號', '項次', 'seq', 'item', 'no.', '件次', 'ref'],
    'part_number': ['料號', '件號', 'part no', 'part number', '零件號', '零件編號', '品番'],
    'name':        ['名稱', '品名', '零件名稱', 'description', 'part name', '品名稱'],
    'qty':         ['數量', 'qty', 'quantity', '用量', '員數'],
    'price':       ['售價', '定價', '單價', 'price', '原廠售價', '參考售價'],
}

# PowerPoint 文字格式 PDF 的欄位 X 座標分界（依台鈴原廠目錄格式分析）
# 頁面寬 720pt，欄位分界：
#   REF NO  < 354   PART NO  354-454   DESCRIPTION  455-540   PART NAME  541-656
#   Q'TY    657-676   REMARKS  ≥677
_WORDS_COL_BOUNDS = {
    'x_ref_max': 354,
    'x_part_max': 455,
    'x_desc_max': 541,
    'x_name_max': 657,
    'x_qty_max': 677,
}

# 跳過標題欄的特徵詞（不建立為零件）
_HEADER_SKIP_WORDS = {
    'PART NO.', 'PART NO', 'PARTS NO', '零件號碼', '料號',
    'REF NO.', 'REF NO', 'REF.', '索引', '索 引',
    'DESCRIPTION', 'PART NAME', '零件名稱', '名稱',
    "Q'TY", 'Q\'TY', 'QTY', '數量', 'REMARKS', '附註',
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

    parse_mode = fields.Selection(
        [
            ('words', '文字座標格式（PowerPoint / 無框線）'),
            ('table', '表格框線格式'),
        ],
        string='解析模式',
        default='words',
        readonly=True,
        help='上傳 PDF 後由系統自動偵測',
    )

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
        string='PDF 中偵測到的欄位 / 格式說明',
        readonly=True,
        help='上傳 PDF 後自動顯示',
    )
    col_seq = fields.Integer(string='序號欄（-1 = 無）', default=0)
    col_part_number = fields.Integer(string='料號欄', default=1)
    col_name = fields.Integer(string='名稱欄', default=2)
    col_qty = fields.Integer(string='用量欄（-1 = 無）', default=3)
    col_price = fields.Integer(string='售價欄（-1 = 無）', default=-1)

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
    preview_html = fields.Html(
        string='偵測頁面預覽',
        readonly=True,
        sanitize=False,
        help='上傳 PDF 後自動顯示偵測到的分區頁縮圖與解析摘要',
    )

    # ── onchange: 上傳後自動分析格式 ─────────────────────────────────────

    @api.onchange('pdf_file')
    def _onchange_pdf_file(self):
        if not self.pdf_file:
            self.col_headers_display = False
            self.preview_html = False
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
            pdf_bytes = base64.b64decode(self.pdf_file)
            doc = fitz.open(stream=pdf_bytes, filetype='pdf')

            # 先嘗試偵測格式
            mode, info = self._detect_pdf_format(doc)
            self.parse_mode = mode

            if mode == 'words':
                self.col_headers_display = info
                self.preview_html = self._build_preview_html(doc)
                doc.close()
            else:
                doc.close()
                self.preview_html = False
                # 表格格式：找欄位標題
                doc2 = fitz.open(stream=pdf_bytes, filetype='pdf')
                headers = None
                for page_num in range(min(len(doc2), 15)):
                    page = doc2[page_num]
                    tbl_finder = page.find_tables()
                    if tbl_finder.tables:
                        rows = tbl_finder.tables[0].extract()
                        if rows and rows[0] and any(c for c in rows[0] if c):
                            headers = [
                                str(c).strip() if c else f'欄{i}'
                                for i, c in enumerate(rows[0])
                            ]
                            break
                doc2.close()
                if headers:
                    self.col_headers_display = '  |  '.join(
                        f'欄{i}: {h}' for i, h in enumerate(headers)
                    )
                    self.col_seq = _best_col_idx(headers, 'seq')
                    self.col_part_number = max(_best_col_idx(headers, 'part_number'), 0)
                    self.col_name = max(_best_col_idx(headers, 'name'), 0)
                    self.col_qty = _best_col_idx(headers, 'qty')
                    self.col_price = _best_col_idx(headers, 'price')
                else:
                    self.col_headers_display = '⚠ 未偵測到表格欄位，請手動填入欄索引'

        except Exception as e:
            _logger.warning('PDF 格式分析失敗: %s', e)
            self.col_headers_display = f'分析錯誤：{e}'
            self.preview_html = False

    # ── 預覽 HTML 生成 ────────────────────────────────────────────────────

    def _build_preview_html(self, doc):
        """生成分區頁縮圖預覽 HTML（words 模式用）"""
        try:
            import fitz
        except ImportError:
            return ''

        thumb_matrix = fitz.Matrix(0.25, 0.25)  # 720pt × 0.25 = 180px 寬
        cards = []

        for page_num in range(len(doc)):
            page = doc[page_num]
            imgs = page.get_images()
            if not imgs or len(imgs) > 5:
                continue

            section_info, data_rows = self._parse_parts_page_words(page)
            if not section_info or not section_info.get('seq'):
                continue

            # 渲染低解析度縮圖
            try:
                pix = page.get_pixmap(matrix=thumb_matrix)
                thumb_b64 = base64.b64encode(pix.tobytes('png')).decode('ascii')
            except Exception:
                thumb_b64 = ''

            seq = section_info.get('seq', 0)
            name_en = section_info.get('name_en', '')
            name_zh = section_info.get('name_zh', '')
            row_count = len(data_rows)

            # 前 4 筆零件摘要
            sample_html = ''
            for r in data_rows[:4]:
                pn = r.get('part_number') or '—'
                nm = r.get('name_zh') or r.get('name_en') or ''
                qty = r.get('qty') or ''
                qty_str = f' ×{qty}' if qty else ''
                line = f'{pn}  {nm}{qty_str}'
                sample_html += (
                    f'<div style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;'
                    f'color:#444;margin:1px 0;" title="{pn} | {nm}">{line}</div>'
                )
            if row_count > 4:
                sample_html += (
                    f'<div style="color:#999;font-style:italic;">'
                    f'...還有 {row_count - 4} 筆</div>'
                )

            img_tag = (
                f'<img src="data:image/png;base64,{thumb_b64}"'
                f' style="width:100%;display:block;border-bottom:1px solid #ddd;"'
                f' title="p{page_num + 1}: {seq:02d}. {name_en}"/>'
                if thumb_b64 else
                f'<div style="height:60px;background:#eee;text-align:center;line-height:60px;'
                f'color:#aaa;">無法渲染</div>'
            )

            cards.append(
                f'<div style="display:inline-block;vertical-align:top;width:205px;margin:5px;'
                f'border:1px solid #ccc;border-radius:6px;overflow:hidden;background:#fff;'
                f'box-shadow:1px 2px 4px rgba(0,0,0,0.08);">'
                f'{img_tag}'
                f'<div style="padding:7px;font-size:11px;font-family:monospace;">'
                f'<div style="font-weight:bold;color:#1a5c30;margin-bottom:2px;">'
                f'p{page_num + 1} → {seq:02d}. {name_en}</div>'
                f'<div style="color:#666;margin-bottom:4px;">{name_zh} ({row_count} 筆零件)</div>'
                f'{sample_html}'
                f'</div></div>'
            )

        if not cards:
            return ''

        total = len(cards)
        return (
            f'<div style="font-family:sans-serif;font-size:12px;">'
            f'<div style="margin-bottom:6px;color:#555;">'
            f'共偵測到 <b>{total}</b> 個分區頁（捲動查看全部）</div>'
            f'<div style="white-space:normal;">{" ".join(cards)}</div>'
            f'</div>'
        )

    # ── 格式偵測 ──────────────────────────────────────────────────────────

    def _detect_pdf_format(self, doc):
        """
        偵測 PDF 為「文字座標格式（PowerPoint）」還是「表格框線格式」。
        回傳 (mode, info_string)：mode='words' 或 'table'
        """
        parts_pages = 0
        min_page = 9999
        max_page = 0
        for page_num in range(len(doc)):
            page = doc[page_num]
            imgs = page.get_images()
            # 允許 1-5 張圖（主圖 + 小圖示裝飾），排除目錄索引頁（8+ 張縮圖）
            if not imgs or len(imgs) > 5:
                continue
            text = page.get_text("text").strip()
            # 必須同時有 "NN." 格式的分區號碼 + 零件清單欄位標題 PART NO.
            if (re.search(r'^\d{1,2}\.\s', text, re.MULTILINE)
                    and 'PART NO.' in text):
                parts_pages += 1
                p1 = page_num + 1  # 1-based
                if p1 < min_page:
                    min_page = p1
                if p1 > max_page:
                    max_page = p1

        if parts_pages >= 3:
            return ('words',
                    f'✅ 偵測到 {parts_pages} 個零件分區頁'
                    f'（第 {min_page}～{max_page} 頁，PowerPoint 文字格式），'
                    f'系統將自動解析欄位位置，可直接點「開始匯入」')

        # 否則嘗試表格格式
        return ('table', '')

    # ── 文字座標格式解析 ──────────────────────────────────────────────────

    def _parse_parts_page_words(self, page):
        """
        解析 PowerPoint 匯出的零件頁（沒有框線，文字以座標排列）。
        回傳 (section_info_dict, [row_dict]) 或 (None, [])。
        section_info = {'seq': int, 'name_en': str, 'name_zh': str}
        row_dict = {'seq': str, 'part_number': str, 'name_en': str, 'name_zh': str,
                    'qty': str, 'remarks': str}
        """
        text = page.get_text("text").strip()
        # 必須同時有 "NN." 格式分區號碼 + PART NO. 欄位標題（排除目錄索引頁）
        if not (re.search(r'^\d{1,2}\.\s', text, re.MULTILINE) and 'PART NO.' in text):
            return None, []

        # 解析分區標頭：依 Y 軸排序找第一個符合 "NN. SECTION NAME" 的 block
        blocks = page.get_text("blocks")
        section_info = {'seq': 0, 'name_en': '', 'name_zh': ''}
        # 按 Y 座標排序，取頁面頂部的 block（排除出現在底部的頁碼）
        top_blocks = sorted(blocks, key=lambda b: b[1])[:5]
        for blk in top_blocks:
            hdr = blk[4].replace('\n', ' ').strip()
            m = re.match(r'^(\d{1,2})\.\s+(.*)', hdr)
            if m:
                section_info['seq'] = int(m.group(1))
                rest = m.group(2).strip()
                zh_pos = re.search(r'[\u4e00-\u9fff]', rest)
                if zh_pos:
                    section_info['name_en'] = rest[:zh_pos.start()].strip()
                    section_info['name_zh'] = rest[zh_pos.start():].strip()
                else:
                    section_info['name_en'] = rest

        # 取得所有詞彙及其座標
        words = page.get_text("words")
        if not words:
            return section_info, []

        # 從標頭行自動校準欄位 X 分界
        bounds = dict(_WORDS_COL_BOUNDS)
        for w in words:
            wtext = w[4].strip()
            wx = w[0]
            # 以 DESCRIPTION 與 Q'TY 的 X 座標更新分界
            if wtext.upper() == 'DESCRIPTION':
                bounds['x_part_max'] = wx - 2
                bounds['x_desc_max'] = wx + 90
            elif wtext.upper() in ("Q'TY", "Q´TY", "Q`TY", 'QTY'):
                bounds['x_name_max'] = wx - 2
                bounds['x_qty_max'] = wx + 22

        # 找標頭行 Y（含 DESCRIPTION 或 PART NAME 的那行）
        header_y = None
        for w in words:
            if w[4].upper() in ('DESCRIPTION', "Q'TY", 'QTY', 'REMARKS'):
                header_y = w[1]
                break
        data_y_min = (header_y or 65) + 6

        # 收集資料行的詞彙（Y 在資料區以下）
        data_words = [w for w in words if w[1] >= data_y_min]

        # 依 Y 分組（容差：將 Y 四捨五入至最近 6 的倍數）
        row_groups = {}
        for w in data_words:
            y_key = round(w[1] / 6) * 6
            row_groups.setdefault(y_key, []).append(w)

        result = []
        for y_key in sorted(row_groups):
            row_words = sorted(row_groups[y_key], key=lambda w: w[0])
            cols = {k: [] for k in ('seq', 'part_no', 'name_en', 'name_zh', 'qty', 'rem')}
            for w in row_words:
                x, wt = w[0], w[4]
                if x < bounds['x_ref_max']:
                    cols['seq'].append(wt)
                elif x < bounds['x_part_max']:
                    cols['part_no'].append(wt)
                elif x < bounds['x_desc_max']:
                    cols['name_en'].append(wt)
                elif x < bounds['x_name_max']:
                    cols['name_zh'].append(wt)
                elif x < bounds['x_qty_max']:
                    cols['qty'].append(wt)
                else:
                    cols['rem'].append(wt)

            part_number = ' '.join(cols['part_no']).strip()
            name_en = ' '.join(cols['name_en']).strip()
            name_zh = ' '.join(cols['name_zh']).strip()

            # 跳過空列與標題列
            if not part_number and not name_zh and not name_en:
                continue
            if part_number.upper().rstrip('.') in {w.rstrip('.') for w in _HEADER_SKIP_WORDS}:
                continue
            if name_zh in {'零件名稱', '零件名稱(中)', 'PART NAME'}:
                continue

            result.append({
                'seq':         ' '.join(cols['seq']),
                'part_number': part_number,
                'name_en':     name_en,
                'name_zh':     name_zh or name_en,
                'qty':         ' '.join(cols['qty']),
                'remarks':     ' '.join(cols['rem']),
            })

        return section_info, result

    # ── helper ───────────────────────────────────────────────────────────

    def _cell(self, row, idx):
        if idx < 0 or idx >= len(row):
            return ''
        v = row[idx]
        return str(v).strip() if v is not None else ''

    def _extract_section_name(self, page, table_bbox):
        """嘗試從表格上方文字找出分區名稱（表格格式用）"""
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

        try:
            import fitz
        except ImportError:
            raise UserError('PyMuPDF 未安裝，請執行 docker compose build 重建映像。')

        pdf_bytes = base64.b64decode(self.pdf_file)
        doc = fitz.open(stream=pdf_bytes, filetype='pdf')

        # words mode 直接使用 PDF 分區序號作為編號（不加前綴）
        # table mode 使用使用者選擇的前綴
        if self.parse_mode == 'words':
            prefix = ''
        else:
            prefix = (
                self.section_prefix
                if self.section_prefix != 'custom'
                else (self.section_prefix_custom or 'A')
            )

        sections_created = 0
        lines_created = 0
        parts_created = 0
        skipped_rows = 0

        if self.parse_mode == 'words':
            sections_created, lines_created, parts_created, skipped_rows = \
                self._import_words_mode(doc, prefix)
        else:
            if self.col_part_number < 0 and self.col_name < 0:
                raise UserError('「料號欄」和「名稱欄」至少需設定一個（≥ 0）。')
            sections_created, lines_created, parts_created, skipped_rows = \
                self._import_table_mode(doc, prefix)

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

    # ── 文字格式匯入 ──────────────────────────────────────────────────────

    def _import_words_mode(self, doc, prefix):
        """處理 PowerPoint 文字格式 PDF，逐頁解析零件清單"""
        sections_created = lines_created = parts_created = skipped_rows = 0

        for page_num in range(len(doc)):
            page = doc[page_num]

            # 允許 1-4 張圖（某些頁含裝飾小圖），排除索引頁（8+ 縮圖）
            imgs = page.get_images()
            if not imgs or len(imgs) > 5:
                continue

            section_info, data_rows = self._parse_parts_page_words(page)
            if not section_info or not data_rows:
                continue

            # 取最大的嵌入圖片作為爆炸圖（原始畫質，不重新渲染整頁）
            try:
                best_img = max(
                    imgs,
                    key=lambda i: doc.extract_image(i[0])['width'] * doc.extract_image(i[0])['height']
                )
                xref = best_img[0]
                img_dict = doc.extract_image(xref)
                img_b64 = base64.b64encode(img_dict['image'])
            except Exception:
                import fitz
                pix = page.get_pixmap(dpi=120)
                img_b64 = base64.b64encode(pix.tobytes('png'))

            seq_num = section_info['seq']
            section_code = f'{prefix}{seq_num:02d}'
            section_name = section_info['name_zh'] or section_info['name_en'] or f'第{seq_num:02d}部分'
            # 簡單依序號決定部位分類
            category = 'engine' if seq_num <= 16 else 'frame'

            section = self.env['dms.part.catalog.section'].create({
                'catalog_id': self.catalog_id.id,
                'code': section_code,
                'name': section_name,
                'category': category,
                'diagram_image': img_b64,
                'sequence': seq_num * 10,
            })
            sections_created += 1

            for row in data_rows:
                part_number = row['part_number']
                name = row['name_zh'] or row['name_en']

                if not part_number and not name:
                    skipped_rows += 1
                    continue

                # qty
                qty = 1.0
                if row['qty']:
                    try:
                        qty = float(re.sub(r'[^\d.]', '', row['qty'])) or 1.0
                    except Exception:
                        qty = 1.0

                # seq_no
                seq_no = 0
                if row['seq']:
                    try:
                        seq_no = int(re.sub(r'[^\d]', '', row['seq'])) or 0
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
                            'part_number': part_number or name[:20],
                            'name': name or part_number,
                            'part_type': 'vehicle_part',
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
                })
                lines_created += 1

        return sections_created, lines_created, parts_created, skipped_rows

    # ── 表格框線格式匯入（原有邏輯） ──────────────────────────────────────

    def _import_table_mode(self, doc, prefix):
        """處理有框線表格的 PDF"""
        sections_created = lines_created = parts_created = skipped_rows = 0
        total = len(doc)
        existing_count = len(self.catalog_id.section_ids)

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
            data_rows = [r for r in data_rows if any(v for v in r if v and str(v).strip())]
            if not data_rows:
                continue

            img_page = doc[img_idx]
            pix = img_page.get_pixmap(dpi=120)
            img_b64 = base64.b64encode(pix.tobytes('png'))

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

            for row in data_rows:
                part_number = self._cell(row, self.col_part_number)
                name = self._cell(row, self.col_name)
                if not part_number and not name:
                    skipped_rows += 1
                    continue

                qty = 1.0
                raw_qty = self._cell(row, self.col_qty)
                if raw_qty:
                    try:
                        qty = float(re.sub(r'[^\d.]', '', raw_qty)) or 1.0
                    except Exception:
                        qty = 1.0

                price = 0.0
                raw_price = self._cell(row, self.col_price)
                if raw_price:
                    try:
                        price = float(re.sub(r'[^\d.]', '', raw_price)) or 0.0
                    except Exception:
                        price = 0.0

                seq_no = 0
                raw_seq = self._cell(row, self.col_seq)
                if raw_seq:
                    try:
                        seq_no = int(re.sub(r'[^\d]', '', raw_seq)) or 0
                    except Exception:
                        seq_no = 0

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

        return sections_created, lines_created, parts_created, skipped_rows
