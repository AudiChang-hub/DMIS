"""套表列印預覽（使用者 2026-11-06 T-118）：列印前先看帶入資料後的樣子。只讀，不寫任何資料。

A4（聲明書、簽收單）：用 `form_print.build_forms_pdf` 產生和「產生 A4 PDF」同一份 PDF，再逐頁轉成圖片，
內容與列印輸出一致。
信封：Word 檔要由 Word 排版，伺服器沒有 Word。這裡取 `build_envelopes_docx` 同一段文件內容
（同一個 `_envelope_body`），依 Word 的排版規則（紙張、邊界、表格縮排、隔行對齊）畫成同尺寸的頁面；
位置以 Word 2016 實際輸出校準，誤差在 0.1 mm 內，字形依伺服器的楷書字型。
電車信封已存的車控密碼不在預覽解密（解密會留處理紀錄），改顯示「下載時帶入」。
"""
import base64
import math
from dataclasses import dataclass, field
from io import BytesIO

from defusedxml import ElementTree
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas

from sales.services import form_print

MAX_PAGES = 24  # 每一區（A4、信封）最多預覽的頁數；列印仍包含全部。
RENDER_SCALE = 2  # 每 pt 2 px：A4 與信封寬都是 21 cm，1191 px 寬，高解析螢幕也清楚。
PASSWORD_PLACEHOLDER = "（下載 Word 檔時帶入）"

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
TWIP_MM = 25.4 / 1440
# 原稿 docGrid type="lines" linePitch="360"：每行高度取 18 pt 的整數倍（Word「文件格線」）。
GRID_PT = 18
# 標楷體（kaiu.ttf，unitsPerEm 1024）上升 820、下降 204：Word 把這段字身放在格線行的正中間。
KAI_ASCENT = 820 / 1024
KAI_DESCENT = 204 / 1024
# Word 中文字型的單行高度約為字級 1.3 倍，超過 18 pt 就佔兩格（12 pt 一格、14 pt 起兩格；以 Word 輸出校準）。
LINE_FACTOR = 1.3
DEFAULT_SIZE_PT = 12  # styles.xml docDefaults sz=24（半點）
PAGE_W_TW, PAGE_H_TW = 11907, 9639  # 21×17 cm 橫向
MARGIN_LEFT_TW, MARGIN_RIGHT_TW = 2835, 1134
CELL_MARGIN_TW = 108  # Table Normal 左右儲存格邊界
PLACEHOLDER_GREY = (0.55, 0.57, 0.6)


@dataclass
class _Run:
    text: str
    size: float


@dataclass
class _Line:
    runs: list = field(default_factory=list)
    size: float = DEFAULT_SIZE_PT

    @property
    def height(self):
        return max(1, math.ceil(round(self.size * LINE_FACTOR / GRID_PT, 4))) * GRID_PT

    @property
    def baseline(self):
        return (self.height - self.size * (KAI_ASCENT + KAI_DESCENT)) / 2 + self.size * KAI_ASCENT


def _half_points(element, default):
    size = element.find(f"{_W}rPr/{_W}sz") if element is not None else None
    if size is None:
        return default
    return int(size.get(f"{_W}val")) / 2


def _twips(element, path, attr="w", default=0):
    node = element.find(path)
    if node is None:
        return default
    return int(node.get(f"{_W}{attr}", default))


def _layout_paragraph(paragraph, width_pt):
    """一個段落拆成數行（依可用寬度斷行）；空段落以段落標記的字級佔一行。"""
    ppr = paragraph.find(f"{_W}pPr")
    mark_size = _half_points(ppr, DEFAULT_SIZE_PT)
    right_indent = _twips(ppr, f"{_W}ind", "right") * TWIP_MM * mm if ppr is not None else 0
    available = max(width_pt - right_indent, 1)
    lines = [_Line(size=mark_size)]
    used = 0.0
    for run in paragraph.findall(f"{_W}r"):
        size = _half_points(run, DEFAULT_SIZE_PT)
        text = "".join(node.text or "" for node in run.findall(f"{_W}t"))
        if not text:
            continue
        current = ""
        for char in text:
            advance = pdfmetrics.stringWidth(char, form_print.KAI, size)
            if used + advance > available and (current or lines[-1].runs):
                if current:
                    _append(lines[-1], current, size)
                lines.append(_Line(size=size))
                current, used = "", 0.0
            current += char
            used += advance
        if current:
            _append(lines[-1], current, size)
    return lines


def _append(line, text, size):
    """行高取該行最大字級；空段落才用段落標記的字級。"""
    line.size = max(line.size, size) if line.runs else size
    line.runs.append(_Run(text, size))


def envelope_layout(body_xml):
    """依 Word 規則排出一頁信封的每一行：回傳 [(x_mm, 基線_mm, [(文字, 字級 pt)])]（距紙張左上）。"""
    root = ElementTree.fromstring(f"<w:body {form_print._W_NS}>{body_xml}</w:body>")
    sections = root.findall(f".//{_W}sectPr")
    top_tw = _twips(sections[-1], f"{_W}pgMar", "top") if sections else 2268
    left_mm = MARGIN_LEFT_TW * TWIP_MM
    text_width_pt = (PAGE_W_TW - MARGIN_LEFT_TW - MARGIN_RIGHT_TW) * TWIP_MM * mm
    y = top_tw * TWIP_MM * mm  # pt，自紙張頂端
    placed = []

    def place(lines, x_mm, top_pt):
        cursor = top_pt
        for line in lines:
            if line.runs:
                placed.append((x_mm, (cursor + line.baseline) / mm, [(run.text, run.size) for run in line.runs]))
            cursor += line.height
        return cursor - top_pt

    for block in root:
        if block.tag == f"{_W}p":
            y += place(_layout_paragraph(block, text_width_pt), left_mm, y)
        elif block.tag == f"{_W}tbl":
            # Word 以 tblInd 對齊第一格的文字起點；gridBefore 的列再右移 wBefore。
            indent_mm = _twips(block, f"{_W}tblPr/{_W}tblInd") * TWIP_MM
            for row in block.findall(f"{_W}tr"):
                before_tw = _twips(row, f"{_W}trPr/{_W}wBefore")
                x_mm = left_mm + indent_mm + before_tw * TWIP_MM
                row_height = _twips(row, f"{_W}trPr/{_W}trHeight", "val") * TWIP_MM * mm
                used = 0.0
                for cell in row.findall(f"{_W}tc"):
                    cell_tw = _twips(cell, f"{_W}tcPr/{_W}tcW")
                    width_pt = (cell_tw - 2 * CELL_MARGIN_TW) * TWIP_MM * mm
                    cursor = y
                    for paragraph in cell.findall(f"{_W}p"):
                        cursor += place(_layout_paragraph(paragraph, width_pt), x_mm, cursor)
                    used = max(used, cursor - y)
                    x_mm += cell_tw * TWIP_MM
                y += max(row_height, used)
    return placed


def _envelope_values(order):
    values = form_print.form_values(order)
    if form_print.has_control_password(order):
        values["vehicle_control_password"] = PASSWORD_PLACEHOLDER
    return values


def build_envelope_preview_pdf(orders):
    """信封預覽：每張訂單一頁 21×17 cm，內容取自下載 Word 檔用的同一段文件。"""
    output = BytesIO()
    pdf = canvas.Canvas(output, pagesize=(PAGE_W_TW * TWIP_MM * mm, PAGE_H_TW * TWIP_MM * mm))
    pdf.setTitle("信封預覽")
    height = PAGE_H_TW * TWIP_MM * mm
    for order in orders:
        body = form_print._envelope_body(order, _envelope_values(order))
        top, bottom = form_print._ENVELOPE_MARGINS[order.is_electric_vehicle]
        body += f'<w:sectPr><w:pgMar w:top="{top}" w:bottom="{bottom}"/></w:sectPr>'
        for x_mm, baseline_mm, runs in envelope_layout(body):
            x = x_mm * mm
            for text, size in runs:
                grey = text == PASSWORD_PLACEHOLDER
                pdf.setFillColorRGB(*(PLACEHOLDER_GREY if grey else (0, 0, 0)))
                pdf.setFont(form_print.KAI, size)
                pdf.drawString(x, height - baseline_mm * mm, text)
                x += pdfmetrics.stringWidth(text, form_print.KAI, size)
        pdf.showPage()
    pdf.save()
    return output.getvalue()


def render_pages(pdf_bytes, limit=MAX_PAGES):
    """PDF 逐頁轉成 WebP data URI；回傳 [{src, width, height}]。"""
    import pypdfium2 as pdfium

    pages = []
    document = pdfium.PdfDocument(pdf_bytes)
    try:
        for index in range(min(len(document), limit)):
            page = document[index]
            image = page.render(scale=RENDER_SCALE).to_pil().convert("RGB")
            page.close()
            buffer = BytesIO()
            image.save(buffer, format="WEBP", quality=80, method=4)
            pages.append({
                "src": "data:image/webp;base64," + base64.b64encode(buffer.getvalue()).decode("ascii"),
                "width": image.width,
                "height": image.height,
            })
    finally:
        document.close()
    return pages


def _caption(order, values, label):
    return {"number": order.number, "name": values["owner_name"] or "（未填車主）", "label": label}


def build_preview(jobs, *, group_by_form=True):
    """jobs：form_print.PrintJob（含信封）。依實際輸出的順序回傳 A4 與信封兩區的頁面。"""
    a4_jobs = form_print.ordered_jobs([job for job in jobs if job.form != "envelope"], group_by_form=group_by_form)
    envelope_orders = [job.order for job in jobs if job.form == "envelope"]
    sections = []
    if a4_jobs:
        pages = render_pages(form_print.build_forms_pdf(a4_jobs, group_by_form=group_by_form))
        for page, job in zip(pages, a4_jobs):
            page.update(_caption(job.order, form_print.form_values(job.order), form_print.FORM_BY_KEY[job.form].label))
            page["paper"] = "A4"
        sections.append({"key": "a4", "title": "A4 PDF", "unit": "頁", "total": len(a4_jobs), "pages": pages})
    if envelope_orders:
        pages = render_pages(build_envelope_preview_pdf(envelope_orders[:MAX_PAGES]))
        for page, order in zip(pages, envelope_orders):
            values = form_print.form_values(order)
            page.update(_caption(order, values, f"信封・{'電車' if order.is_electric_vehicle else '油車'}"))
            page["paper"] = "21 × 17 cm"
            page["masked"] = form_print.has_control_password(order)
        sections.append({"key": "envelope", "title": "信封 Word 檔", "unit": "張", "total": len(envelope_orders), "pages": pages})
    for section in sections:
        section["hidden"] = section["total"] - len(section["pages"])
    return sections
