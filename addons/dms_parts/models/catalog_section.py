from odoo import api, models, fields
import base64
import logging

_logger = logging.getLogger(__name__)


class DmsPartCatalogSection(models.Model):
    """零件目錄分區：對應爆炸圖的一個區段（E01、E02...）"""
    _name = 'dms.part.catalog.section'
    _description = '目錄分區'
    _rec_name = 'display_name'
    _order = 'catalog_id, sequence, code'

    catalog_id = fields.Many2one(
        'dms.part.catalog',
        string='所屬目錄',
        required=True,
        ondelete='cascade',
    )
    code = fields.Char(string='編號', required=True, help='如 E01、E02、F01')
    name = fields.Char(string='圖示名稱', required=True, help='如 引擎蓋、節流組、前叉組')
    display_name = fields.Char(
        string='顯示名稱',
        compute='_compute_display_name',
        store=True,
    )
    category = fields.Selection(
        [('engine', '引擎'), ('frame', '車架')],
        string='部位',
        required=True,
        default='engine',
    )
    diagram_image = fields.Binary(string='爆炸圖', attachment=True)
    diagram_filename = fields.Char(string='圖檔名稱')
    pdf_source = fields.Binary(
        string='上傳 PDF',
        attachment=True,
        help='上傳此分區的 PDF，系統將自動擷取第一頁為爆炸圖',
    )
    pdf_filename = fields.Char(string='PDF 檔名')
    sequence = fields.Integer(string='排序', default=10)
    line_ids = fields.One2many(
        'dms.part.catalog.line',
        'section_id',
        string='零件明細',
    )
    line_count = fields.Integer(
        string='零件數',
        compute='_compute_line_count',
    )

    def _compute_display_name(self):
        for rec in self:
            rec.display_name = f'{rec.code} {rec.name}' if rec.code and rec.name else (rec.code or rec.name or '')

    def _compute_line_count(self):
        for rec in self:
            rec.line_count = len(rec.line_ids)

    @api.onchange('pdf_source')
    def _onchange_pdf_source(self):
        if not self.pdf_source:
            return
        try:
            import fitz  # PyMuPDF
            pdf_bytes = base64.b64decode(self.pdf_source)
            doc = fitz.open(stream=pdf_bytes, filetype='pdf')
            page = doc[0]
            pix = page.get_pixmap(dpi=150)
            img_bytes = pix.tobytes('png')
            self.diagram_image = base64.b64encode(img_bytes)
            base_name = (self.pdf_filename or 'diagram').replace('.pdf', '').replace('.PDF', '')
            self.diagram_filename = f'{base_name}.png'
            doc.close()
        except ImportError:
            return {
                'warning': {
                    'title': 'PDF 轉換功能尚未啟用',
                    'message': (
                        '請先重建 Docker 映像以啟用 PDF 轉換：\n\n'
                        '  docker compose build\n'
                        '  docker compose up -d\n\n'
                        '或直接上傳 PNG/JPG 圖片到「爆炸圖」欄位。'
                    ),
                },
            }
        except Exception as e:
            _logger.warning('PDF 轉換失敗: %s', e)
            return {
                'warning': {
                    'title': 'PDF 轉換失敗',
                    'message': f'無法擷取 PDF 第一頁：{e}\n\n請改成直接上傳 PNG/JPG 圖片。',
                },
            }
