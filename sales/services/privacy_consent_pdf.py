from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph

# 載入訂購合約模組時會一併註冊 MSJH 與 MSJH-Bold 字型。
from .order_contract_pdf import FONT_BOLD, FONT_REGULAR  # noqa: F401


PAGE_W, PAGE_H = A4
MARGIN_X = 22 * mm
CONTENT_W = PAGE_W - 2 * MARGIN_X
INK = HexColor("#17221D")
MUTED = HexColor("#5E6B64")
LINE = HexColor("#CBD5CF")
GREEN = HexColor("#174A39")

title_style = ParagraphStyle(
    "privacy-title",
    fontName="MSJH-Bold",
    fontSize=18,
    leading=24,
    alignment=TA_CENTER,
    textColor=INK,
)
body_style = ParagraphStyle(
    "privacy-body",
    fontName="MSJH",
    fontSize=9.2,
    leading=15,
    textColor=INK,
)
greeting_style = ParagraphStyle(
    "privacy-greeting",
    parent=body_style,
    fontName="MSJH-Bold",
    fontSize=10.2,
)
small_style = ParagraphStyle(
    "privacy-small",
    parent=body_style,
    fontSize=8,
    leading=12,
    textColor=MUTED,
)


def _draw_paragraph(c, text, style, y, spacing=4 * mm):
    paragraph = Paragraph(text, style)
    width, height = paragraph.wrap(CONTENT_W, PAGE_H)
    paragraph.drawOn(c, MARGIN_X, y - height)
    return y - height - spacing


def roc_date(value):
    return f"中華民國 {value.year - 1911} 年 {value.month:02d} 月 {value.day:02d} 日"


def build_privacy_consent_pdf(order):
    output = BytesIO()
    c = canvas.Canvas(output, pagesize=A4)
    c.setTitle(f"{order.number} 個人資料使用同意書")
    c.setAuthor("馭盛國際有限公司")

    y = PAGE_H - 18 * mm
    y = _draw_paragraph(c, "個人資料使用同意書", title_style, y, 8 * mm)
    c.setStrokeColor(GREEN)
    c.setLineWidth(1)
    c.line(MARGIN_X, y + 3 * mm, PAGE_W - MARGIN_X, y + 3 * mm)

    y = _draw_paragraph(
        c,
        f"親愛的車主 {escape(order.owner_name)} 您好：",
        greeting_style,
        y,
        7 * mm,
    )
    plate_number = (
        escape(order.final_plate_number)
        if order.final_plate_number
        else "________________"
    )
    y = _draw_paragraph(
        c,
        "因應個人資料保護法之實施，為維護您的權益、及台鈴工業股份有限公司"
        "提供貴車主服務之必需，<br/>就車主所提供車號："
        f"<u>{plate_number}</u> 所屬車主或使用人之個人資料，車主瞭解並同意如下：",
        body_style,
        y,
        5 * mm,
    )

    clauses = [
        "1. 車主之個人資料係由台鈴工業股份有限公司（以下稱本公司）所蒐集。"
        "基於履行本契約、維修保養服務、事故處理、拖吊服務、保險及保險理賠、"
        "客戶關懷服務及行銷等目的，本公司得於中華民國境內，蒐集、處理及利用"
        "車主所提供之個人資料。蒐集個人資料類別包括：姓名、性別、身份證字號、"
        "出生日期、出生地、婚姻狀況、戶籍住址、聯絡地址、住家電話、行動電話、"
        "E-mail等識別個人者及其他為履行上述蒐集之目的所必要之相關個人資料。",
        "2. 車主同意基於上述目的之必要，台鈴工業股份有限公司得委託其關係企業、"
        "台鈴授權之經銷商，就個人資料蒐集、處理或是予以利用。個人資料之利用方式"
        "包括自動化機器或其他非自動化之利用方式。",
        "3. 車主瞭解在符合個人資料保護相關法令規定下，其得向本公司請求閱覽、"
        "補充、更正、停止蒐集、處理或利用，或抹除其個人資料，或請求提供該等資料之複製本。",
        "4. 車主瞭解如其不願提供上開個人資料，或要求本公司停止處理、利用或抹除其"
        "個人資料，可能導致上述部分或全部之目的無法完成，而對車主之權益有所影響。",
        "5. 本同意書如有未盡事宜，本公司將依個人資料保護法或其他相關法令之規定辦理。",
    ]
    for clause in clauses:
        y = _draw_paragraph(c, clause, body_style, y, 3.5 * mm)

    y -= 2 * mm
    c.setFillColor(INK)
    c.setFont("MSJH-Bold", 9.5)
    c.drawRightString(PAGE_W - MARGIN_X, y, "台鈴工業股份有限公司　敬啟")
    y -= 7 * mm
    c.setFont("MSJH", 9.5)
    c.drawRightString(PAGE_W - MARGIN_X, y, "經銷商：馭盛國際有限公司")

    signature_y = 35 * mm
    c.setStrokeColor(INK)
    c.setFillColor(INK)
    c.setFont("MSJH-Bold", 10)
    c.drawString(MARGIN_X, signature_y + 16 * mm, "車主簽名：")
    c.line(MARGIN_X + 24 * mm, signature_y + 15.5 * mm, PAGE_W - MARGIN_X, signature_y + 15.5 * mm)
    c.setFont("MSJH", 9.5)
    c.drawCentredString(PAGE_W / 2, signature_y, roc_date(order.order_date))

    c.setStrokeColor(LINE)
    c.line(MARGIN_X, 16 * mm, PAGE_W - MARGIN_X, 16 * mm)
    c.setFillColor(MUTED)
    c.setFont("MSJH", 7)
    c.drawString(MARGIN_X, 11 * mm, f"訂單編號：{order.number}")
    c.drawRightString(PAGE_W - MARGIN_X, 11 * mm, "本文件含個人資料，請妥善保管")

    c.showPage()
    c.save()
    return output.getvalue()
