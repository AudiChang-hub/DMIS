from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

from django.utils import timezone

from reportlab.lib.colors import Color, HexColor, white
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, Table, TableStyle

from sales.services.pdf_signature import draw_signature_image, draw_signature_note
from sales.services.registration_fee import registration_rate_label
from sales.services.site_copy import print_copy
from sales.services.print_company import validate_header


FONT_CANDIDATES = [
    (
        Path(r"C:\Windows\Fonts\msjh.ttc"),
        Path(r"C:\Windows\Fonts\msjhbd.ttc"),
    ),
    (
        Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"),
        Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"),
    ),
]
FONT_REGULAR, FONT_BOLD = next(
    ((regular, bold) for regular, bold in FONT_CANDIDATES if regular.exists() and bold.exists()),
    (None, None),
)
if not FONT_REGULAR:
    raise RuntimeError("找不到可用的繁體中文字型。")

pdfmetrics.registerFont(TTFont("MSJH", str(FONT_REGULAR), subfontIndex=0))
pdfmetrics.registerFont(TTFont("MSJH-Bold", str(FONT_BOLD), subfontIndex=0))

PAGE_W, PAGE_H = A4
MARGIN_X = 12 * mm
CONTENT_W = PAGE_W - 2 * MARGIN_X
CONTENT_BOTTOM = 15 * mm  # 續頁前的內容下緣，下方留給聯別頁尾
SIGNATURE_TOP = 38 * mm  # 簽名區（含電子簽名圖）上緣，確認事項須排在此線之上
SECTION_GAP = 3 * mm
GREEN = HexColor("#174A39")
GREEN_2 = HexColor("#2D765B")
GREEN_LIGHT = HexColor("#EAF4EF")
INK = HexColor("#17221D")
MUTED = HexColor("#5E6B64")
LINE = HexColor("#CBD5CF")
RED = HexColor("#B23A30")

body_style = ParagraphStyle(
    "body",
    fontName="MSJH",
    fontSize=7.8,
    leading=10,
    textColor=INK,
)
small_style = ParagraphStyle(
    "small",
    fontName="MSJH",
    fontSize=6.8,
    leading=8.5,
    textColor=INK,
)
center_style = ParagraphStyle(
    "center",
    parent=body_style,
    alignment=TA_CENTER,
)
# 中文沒有空白，需用 CJK 斷行才會在欄寬內自動換行。
wrap_style = ParagraphStyle(
    "wrap",
    parent=body_style,
    wordWrap="CJK",
)
right_style = ParagraphStyle(
    "right",
    parent=body_style,
    alignment=TA_RIGHT,
)


def p(text, style=body_style):
    return Paragraph(str(text), style)


def payment_lines(order):
    """付款方式：多筆時每筆各占一行（例如「現金 $20,000」換行「分期 $25,000」），不在金額中間斷行。"""
    return p("<br/>".join(escape(line) for line in order.payment_split_lines))


def safe(value, default="—"):
    text = str(value or "").strip()
    return escape(text) if text else default


def draw_section_title(c, y, title):
    c.setFillColor(GREEN)
    c.roundRect(MARGIN_X, y - 4.3 * mm, 1.3 * mm, 4.3 * mm, .6 * mm, fill=1, stroke=0)
    c.setFont("MSJH-Bold", 9.2)
    c.drawString(MARGIN_X + 3.5 * mm, y - 3.4 * mm, title)
    c.setStrokeColor(LINE)
    c.setLineWidth(.5)
    c.line(MARGIN_X, y - 6 * mm, MARGIN_X + CONTENT_W, y - 6 * mm)
    return y - 7.2 * mm


def make_table(data, col_widths, row_heights=None, styles=None, repeat_rows=0):
    table = Table(data, colWidths=col_widths, rowHeights=row_heights, repeatRows=repeat_rows)
    commands = [
        ("FONTNAME", (0, 0), (-1, -1), "MSJH"),
        ("FONTSIZE", (0, 0), (-1, -1), 7.4),
        ("TEXTCOLOR", (0, 0), (-1, -1), INK),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
    ]
    if styles:
        commands.extend(styles)
    # SPAN 必須先套用，格線才不會殘留在合併儲存格內。
    commands.append(("GRID", (0, 0), (-1, -1), 0.35, LINE))
    table.setStyle(TableStyle(commands))
    return table


def draw_table(c, data, col_widths, y_top, row_heights=None, styles=None):
    table = make_table(data, col_widths, row_heights, styles)
    width, height = table.wrapOn(c, CONTENT_W, PAGE_H)
    table.drawOn(c, MARGIN_X, y_top - height)
    return y_top - height


def table_height(c, table):
    return table.wrapOn(c, CONTENT_W, PAGE_H)[1]


def fitted_row_height(row, col_widths, minimum=7 * mm):
    """文字換行後撐高該列；一行放得下的列維持固定列高。左右 padding 共 8pt、上下共 5pt，同 draw_table。"""
    needed = max(
        cell.wrap(width - 8, PAGE_H)[1]
        for cell, width in zip(row, col_widths)
        if isinstance(cell, Paragraph)
    )
    return max(minimum, needed + 5)


def money(value):
    return f"{value:,.0f}"


def draw_company_header(c, data, y):
    """固定左側寬度內換行並縮字，避免侵入中央文件標題。"""
    width = 65 * mm
    top = y
    for key, text, size, color, height in (
        ("name", data["legal_name"], 12.5, GREEN, 11 * mm),
        ("address", data["address"], 7, MUTED, 8 * mm),
        ("contact", f"電話：{data['phone']}　｜　統編：{data['tax_id']}", 7, MUTED, 6 * mm),
    ):
        while True:
            style = ParagraphStyle(f"company-{key}", fontName="MSJH-Bold" if key == "name" else "MSJH",
                                   fontSize=size, leading=size * 1.2, textColor=color, wordWrap="CJK")
            paragraph = Paragraph(escape(text), style)
            _, actual_height = paragraph.wrap(width, PAGE_H)
            if actual_height <= height or size <= 5:
                break
            size -= .5
        paragraph.drawOn(c, MARGIN_X, top - actual_height)
        top -= actual_height + 1 * mm


def page_label(page_number, total_pages):
    return f"頁次：{page_number} / {total_pages or '—'}"


def draw_continued_header(c, order, copy_label, page_number, total_pages):
    """續頁只放辨識用的精簡頁首，把版面留給明細。"""
    y = PAGE_H - 11 * mm
    c.setFillColor(GREEN)
    c.setFont("MSJH-Bold", 10)
    c.drawString(MARGIN_X, y - 5 * mm, validate_header(order.print_company_snapshot)["legal_name"])
    c.setFillColor(INK)
    c.setFont("MSJH-Bold", 13)
    c.drawCentredString(PAGE_W / 2, y - 5.3 * mm, "車 輛 訂 購 單（續）")
    c.setFont("MSJH", 7.5)
    c.drawRightString(PAGE_W - MARGIN_X, y - 3 * mm, f"訂單編號：{order.number}")
    c.drawRightString(PAGE_W - MARGIN_X, y - 7.5 * mm, f"{copy_label}　{page_label(page_number, total_pages)}")
    c.setStrokeColor(LINE)
    c.setLineWidth(.5)
    c.line(MARGIN_X, y - 10 * mm, MARGIN_X + CONTENT_W, y - 10 * mm)
    return y - 14 * mm


class CopyLayout:
    """單聯由上往下排；放不下就續頁，確認事項與簽名一定在該聯最後一頁（配件多時不再壓到簽名）。"""

    def __init__(self, c, order, copy_label, first_page, total_pages):
        self.c = c
        self.order = order
        self.copy_label = copy_label
        self.page = first_page
        self.total_pages = total_pages
        self.y = self.page_top = 0

    def footer(self):
        self.c.setFont("MSJH", 6.5)
        self.c.setFillColor(MUTED)
        self.c.drawRightString(PAGE_W - MARGIN_X, 8 * mm, self.copy_label)

    def new_page(self):
        self.footer()
        self.c.showPage()
        self.page += 1
        self.y = self.page_top = draw_continued_header(
            self.c, self.order, self.copy_label, self.page, self.total_pages
        )

    def ensure(self, height, bottom=CONTENT_BOTTOM):
        if self.y - height < bottom:
            self.new_page()

    def draw_section(self, title, table, keep_with=0, bottom=CONTENT_BOTTOM):
        """小表與標題不拆開；keep_with 是後面須同頁的高度，整段放不下就移到下一頁。"""
        self.y -= SECTION_GAP
        self.ensure(7.2 * mm + table_height(self.c, table) + keep_with, bottom)
        self.y = draw_section_title(self.c, self.y, title)
        self.draw_table(table)

    def draw_table(self, table):
        """依剩餘高度拆表格（表頭重複），續頁接著畫。"""
        while True:
            height = table_height(self.c, table)
            if self.y - height >= CONTENT_BOTTOM:
                break
            parts = table.split(CONTENT_W, self.y - CONTENT_BOTTOM)
            if len(parts) < 2:
                if self.y == self.page_top:
                    break  # 整頁放不下一列時照畫，避免無限換頁
                self.new_page()
                continue
            head, table = parts
            head.drawOn(self.c, MARGIN_X, self.y - table_height(self.c, head))
            self.new_page()
        table.drawOn(self.c, MARGIN_X, self.y - height)
        self.y -= height


def draw_order_copy(c, order, copy_label, first_page, total_pages, printed_at, signature=None):
    """畫一聯（可能多頁），回傳實際頁數。"""
    layout = CopyLayout(c, order, copy_label, first_page, total_pages)
    y = PAGE_H - 11 * mm

    # Header
    draw_company_header(c, validate_header(order.print_company_snapshot), y)

    c.setFillColor(INK)
    c.setFont("MSJH-Bold", 18)
    c.drawCentredString(PAGE_W / 2, y - 7 * mm, "車 輛 訂 購 單")
    c.setFillColor(RED)
    c.setFont("MSJH", 7)
    notice = Paragraph("本文件含個人資料<br/>請妥善保管並限業務用途使用", ParagraphStyle(
        "company-privacy-notice", fontName="MSJH", fontSize=7, leading=10, alignment=TA_CENTER, textColor=RED))
    _, notice_height = notice.wrap(65 * mm, 12 * mm)
    notice.drawOn(c, 79 * mm, y - 11 * mm - notice_height)

    meta_x = PAGE_W - MARGIN_X - 49 * mm
    c.setFillColor(INK)
    c.setFont("MSJH", 7.5)
    c.drawString(meta_x, y - 5 * mm, f"訂單日期：{order.order_date:%Y-%m-%d}")
    c.drawString(meta_x, y - 10 * mm, f"訂單編號：{order.number}")
    c.drawString(meta_x, y - 15 * mm, f"列印時間：{printed_at:%Y-%m-%d %H:%M}")
    c.drawString(meta_x, y - 20 * mm, page_label(first_page, total_pages))
    c.setStrokeColor(GREEN_2)
    c.setLineWidth(.7)
    c.roundRect(meta_x, y - 26 * mm, 49 * mm, 5 * mm, 1 * mm, fill=0, stroke=1)
    c.setFillColor(GREEN_2)
    c.setFont("MSJH-Bold", 8)
    c.drawCentredString(meta_x + 24.5 * mm, y - 24.3 * mm, copy_label)
    c.setStrokeColor(LINE)
    c.line(MARGIN_X, y - 29 * mm, MARGIN_X + CONTENT_W, y - 29 * mm)
    y = layout.page_top = y - 33 * mm

    # Customer / vehicle overview
    y = draw_section_title(c, y, "訂單與車主資料")
    info_data = [
        [
            p("<b>車主姓名</b>"),
            p(safe(order.owner_name)),
            p("<b>車輛類別</b>"),
            p(order.get_vehicle_category_display()),
            p("<b>訂單來源</b>"),
            p(safe(order.source.name if order.source_id else "馭盛")),
        ],
        [
            p("<b>行動電話</b>"),
            p(safe(order.owner_phone)),
            p("<b>付款方式</b>"),
            payment_lines(order),
            p("<b>分期資訊</b>"),
            p(
                safe(
                    "／".join(
                        item
                        for item in (
                            order.installment_company,
                            f"{order.installment_periods} 期" if order.installment_periods else "",
                            f"每期 ${money(order.installment_monthly)}" if order.installment_monthly else "",
                        )
                        if item
                    )
                )
            ),
        ],
        [
            p("<b>戶籍地址</b>"),
            p(safe(order.owner_address), small_style),
            "",
            "",
            "",
            "",
        ],
        [
            p("<b>車型／車色</b>"),
            p(
                f"{safe(order.vehicle_model.brand)} "
                f"{safe(order.vehicle_model.name)}／{safe(order.color.name)}"
            ),
            p("<b>交車方式</b>"),
            p(
                safe(
                    f"{order.get_delivery_method_display()}"
                    + (f"／{order.delivery_destination}" if order.delivery_destination else "")
                )
            ),
            p("<b>選號需求</b>"),
            p(
                safe(
                    "／".join(
                        item
                        for item in (
                            order.get_plate_choice_display(),
                            order.watched_numbers or order.plate_preference_note,
                        )
                        if item
                    )
                )
            ),
        ],
        [
            p("<b>備註</b>"),
            p(
                safe(order.note),
                small_style,
            ),
            "",
            "",
            "",
            "",
        ],
    ]
    info_widths = [19 * mm, 45 * mm, 19 * mm, 32 * mm, 19 * mm, 52 * mm]
    y = draw_table(
        c,
        info_data,
        info_widths,
        y,
        # 付款方式多筆時每筆一行，第 2 列依內容撐高。
        row_heights=[7 * mm, fitted_row_height(info_data[1], info_widths), 8 * mm, 8 * mm, 12 * mm],
        styles=[
            ("BACKGROUND", (0, 0), (0, -1), GREEN_LIGHT),
            ("BACKGROUND", (2, 0), (2, 3), GREEN_LIGHT),
            ("BACKGROUND", (4, 0), (4, 3), GREEN_LIGHT),
            ("SPAN", (1, 2), (5, 2)),
            ("BACKGROUND", (1, 2), (5, 2), white),
            ("SPAN", (1, 4), (5, 4)),
            ("BACKGROUND", (1, 4), (5, 4), white),
        ],
    )

    # Price details
    price_header = [
        p("<b>類別</b>", center_style),
        p("<b>項目</b>", center_style),
        p("<b>說明</b>", center_style),
        p("<b>數量</b>", center_style),
        p("<b>單價</b>", center_style),
        p("<b>小計</b>", center_style),
    ]
    rows = [
        [
            p("車價"),
            p(safe(order.vehicle_model)),
            p(
                "分期總額（含牌險），由融資支付"
                if order.payment_type == order.PaymentType.INSTALLMENT
                and not order.plate_insurance_fee
                else safe(order.color.name)
            ),
            p("1", center_style),
            p(money(order.vehicle_price), right_style),
            p(money(order.vehicle_price), right_style),
        ]
    ]
    # 牌險不含選號與動保設定，兩者另列於下方（使用者 2026-10-15）。
    plate_amount = order.plate_insurance_fee
    if order.registration_date:
        plate_description = safe(print_copy(c, "contract.plate_description", "領牌＋強制險"))
        rate_label = registration_rate_label(
            order.registration_rate_class,
            order.vehicle_model.displacement_cc,
        )
        if rate_label:
            plate_description += (
                f"（{safe(rate_label)}／"
                f"{order.get_compulsory_insurance_period_display()}）"
            )
        else:
            plate_description += f"（{order.get_compulsory_insurance_period_display()}）"
    else:
        plate_description = safe(print_copy(c, "contract.plate_description_pending", "領牌＋強制險，依單據收款"))
    plate_money = money(plate_amount) if plate_amount else "—"
    if order.plate_insurance_auto:
        # 留空照系統算的牌險不印金額（使用者 2026-10-20），應收與尾款也扣掉這筆、註明牌險另計。
        plate_money = "另計"
    rows.append(
        [
            p("稅金"),
            p("牌險"),
            p(plate_description),
            p("1", center_style),
            p(plate_money, right_style),
            p(plate_money, right_style),
        ]
    )
    for fee in order.other_fees.all():
        rows.append(
            [p("其他"), p(safe(fee.name)), p("其他費用"), p("1", center_style),
             p(money(fee.amount), right_style), p(money(fee.amount), right_style)]
        )
    if order.plate_selection_fee:
        rows.append(
            [
                p("其他"),
                p("選號費"),
                p("監理選號費用"),
                p("1", center_style),
                p(money(order.plate_selection_fee), right_style),
                p(money(order.plate_selection_fee), right_style),
            ]
        )
    if order.lien_registration_fee:
        rows.append(
            [
                p("其他"),
                p("動保設定費"),
                p("動產擔保設定"),
                p("1", center_style),
                p(money(order.lien_registration_fee), right_style),
                p(money(order.lien_registration_fee), right_style),
            ]
        )
    for accessory in order.accessories.all():
        rows.append(
            [
                p("配件"),
                p(safe(accessory.name)),
                p(
                    safe(
                        "、".join(
                            item
                            for item in (
                                accessory.get_line_type_display(),
                                f"工資 {money(accessory.labor_fee)} 元",
                                accessory.note,
                            )
                            if item
                        )
                    )
                ),
                p(accessory.quantity, center_style),
                p(money(accessory.amount + accessory.labor_fee), right_style),
                p(money(accessory.line_total), right_style),
            ]
        )
    if order.approved_discount_amount:
        rows.append(
            [
                p("其他"),
                # 項目欄顯示折扣原因（申請或下單時填的備註）；沒填才退回「已核准優惠」。
                p(safe(order.discount_reason, "已核准優惠"), wrap_style),
                p("依最終成交內容調整"),
                p("1", center_style),
                p(f"-{money(order.approved_discount_amount)}", right_style),
                p(f"-{money(order.approved_discount_amount)}", right_style),
            ]
        )
    if order.installment_opening_fee:
        rows.append(
            [
                p("分期"),
                p("分期開辦費"),
                p(
                    f"{order.installment_periods or '—'} 期；"
                    "須以現金或匯款支付"
                ),
                p("1", center_style),
                p(money(order.installment_opening_fee), right_style),
                p(money(order.installment_opening_fee), right_style),
            ]
        )
    price_widths = [18 * mm, 96 * mm, 14 * mm, 29 * mm, 29 * mm]
    price_data = [[cell for index, cell in enumerate(row) if index != 2] for row in [price_header] + rows]
    price_heights = [7 * mm] + [fitted_row_height(row, price_widths) for row in price_data[1:]]
    price_table = make_table(
        price_data,
        price_widths,
        row_heights=price_heights,
        styles=[
            ("BACKGROUND", (0, 0), (-1, 0), GREEN_LIGHT),
            ("TEXTCOLOR", (0, 0), (-1, 0), GREEN),
            ("FONTNAME", (0, 0), (-1, 0), "MSJH-Bold"),
            ("ROWBACKGROUNDS", (0, 1), (-1, len(rows)), [white, HexColor("#F6F9F7")]),
        ],
        # 配件多時明細跨頁，續頁重複表頭。
        repeat_rows=1,
    )
    layout.y = y - SECTION_GAP
    # 標題至少要跟表頭與第一列同頁。
    layout.ensure(7.2 * mm + price_heights[0] + price_heights[1])
    layout.y = draw_section_title(c, layout.y, "車價與費用明細")
    layout.draw_table(price_table)

    # Subsidy
    subsidy_data = [
        [
            p("<b>補助類型</b>"),
            # 補助類型：列出訂單的補助項目（訂車時選的補助方案）；沒有項目時沿用汰舊補助類型。
            p(safe("、".join(item.item_name for item in order.subsidy_items.all())
                   or (order.subsidy_type if order.is_trade_in_subsidy else "") or "無")),
            p("<b>新舊車主</b>"),
            # 沒有申請補助就沒有新舊車主，不預設為「不同人」。
            p(("同一人" if order.old_owner_same_as_owner else "不同人") if order.is_trade_in_subsidy else "—"),
        ]
    ]
    # 舊車主姓名與舊車車牌訂單階段不會填，訂購單不再列，汰舊區只剩一列（使用者 2026-10-20）；訂單欄位與內容指紋照舊。
    # 補助項目多時換行撐高該列，不再固定列高。
    subsidy_widths = [25 * mm, 68 * mm, 25 * mm, 68 * mm]
    layout.draw_section("汰舊／補助資料", make_table(
        subsidy_data,
        subsidy_widths,
        row_heights=[fitted_row_height(row, subsidy_widths) for row in subsidy_data],
        styles=[
            ("BACKGROUND", (0, 0), (0, -1), GREEN_LIGHT),
            ("BACKGROUND", (2, 0), (2, -1), GREEN_LIGHT),
        ],
    ))

    # Payment
    is_installment = order.payment_type == order.PaymentType.INSTALLMENT
    # 照系統算的牌險沒有印出金額，應收與尾款也不含它，避免相減推算出來（使用者 2026-10-20）。
    hidden_plate = (order.plate_insurance_fee or 0) if order.plate_insurance_auto else 0
    plate_note = "（牌險另計）" if hidden_plate else ""
    payment_first_row = [
        p("<b>付款方式</b>"),
        payment_lines(order),
    ]
    if is_installment:
        payment_first_row.extend(
            [
                p("<b>分期還款總額</b>"),
                p(f"${money(order.installment_monthly * order.installment_periods)}"),
                p("<b>分期外應收</b>"),
                p(f"${money(order.customer_balance_due - hidden_plate)}{plate_note}"),
            ]
        )
    else:
        payment_first_row.extend(
            [
                p("<b>應收</b>"),
                p(f"${money(order.customer_balance_due + order.deposit_amount - hidden_plate)}{plate_note}"),
                "",
                "",
            ]
        )
    payment_data = [
        payment_first_row,
        [
            p("<b>已收訂金</b>"),
            p(f"${money(order.deposit_amount)}"),
            p("<b>訂金收款日</b>"),
            p(order.deposit_date.strftime("%Y-%m-%d") if order.deposit_date and order.deposit_amount else "—"),
            p("<b>收款方式</b>"),
            p(order.get_deposit_method_display() if order.deposit_method and order.deposit_amount else "—"),
        ],
        [
            p("<b>預估尾款</b>"),
            p(f"${money(order.customer_balance_due - hidden_plate)}{plate_note}"),
            "",
            "",
            "",
            "",
        ],
    ]
    payment_styles = [
        ("BACKGROUND", (0, 0), (0, -1), GREEN_LIGHT),
        ("BACKGROUND", (2, 0), (2, 1), GREEN_LIGHT),
        ("BACKGROUND", (4, 1), (4, 1), GREEN_LIGHT),
        ("SPAN", (1, 2), (5, 2)),
        ("BACKGROUND", (0, 2), (1, 2), HexColor("#DDEFE6")),
        ("FONTNAME", (0, 2), (1, 2), "MSJH-Bold"),
    ]
    if is_installment:
        payment_styles.append(("BACKGROUND", (4, 0), (4, 0), GREEN_LIGHT))
    else:
        payment_styles.append(("SPAN", (3, 0), (5, 0)))
    payment_widths = [20 * mm, 36 * mm, 20 * mm, 36 * mm, 20 * mm, 54 * mm]
    payment_table = make_table(
        payment_data,
        payment_widths,
        row_heights=[fitted_row_height(payment_data[0], payment_widths), 7 * mm, 8 * mm],
        styles=payment_styles,
    )

    # Terms
    terms = [
        [
            p(
                escape(print_copy(c, "contract.qualification", "□ 本人（或本公司）已自行審閱並詳讀中央或地方政府公告之補助辦法，包括申請資格、過戶限制及應備文件等。")),
                small_style,
            )
        ],
        [
            p(
                escape(print_copy(c, "contract.subsidy", "□ 本人（或本公司）了解店方僅協助代辦補助申請，補助金額及核准與否以主管機關審核結果為準。")),
                small_style,
            )
        ],
        [
            p(
                escape(print_copy(c, "contract.confirmation", "□ 本人（或本公司）了解並確認本訂購單所載車型、車色、價款、配件、付款方式及其他需求均屬正確。")),
                small_style,
            )
        ],
        [
            p(
                escape(print_copy(c, "contract.registration", "□ 本人（或本公司）了解機車屬於財產登記制，經領牌不再是新車，領牌後無法辦理退換貨。")),
                small_style,
            )
        ],
    ]
    terms_table = make_table(
        terms,
        [CONTENT_W],
        row_heights=[7 * mm, 7 * mm, 7 * mm, 7 * mm],
        styles=[("BACKGROUND", (0, 0), (-1, -1), HexColor("#FBFCFB"))],
    )
    # 收款資料、確認事項與附註整段排在簽名區之上，放不下就一起移到下一頁，客人簽名的那頁一定看得到金額。
    note_height = 5 * mm
    layout.draw_section(
        "收款資料", payment_table,
        keep_with=SECTION_GAP + 7.2 * mm + table_height(c, terms_table) + note_height, bottom=SIGNATURE_TOP,
    )
    layout.draw_section("確認事項", terms_table, keep_with=note_height, bottom=SIGNATURE_TOP)

    c.setFillColor(MUTED)
    c.setFont("MSJH", 6.6)
    c.drawString(
        MARGIN_X,
        layout.y - 4 * mm,
        "本訂購單為交易內容確認文件；實際配車、領牌、交車及補助辦理進度依系統紀錄為準。",
    )

    # Signatures
    signature_y = 18 * mm
    c.setStrokeColor(INK)
    c.setFillColor(INK)
    c.setFont("MSJH-Bold", 8)
    c.drawString(MARGIN_X + 3 * mm, signature_y + 5 * mm, "承辦人員：")
    c.line(MARGIN_X + 21 * mm, signature_y + 4.5 * mm, MARGIN_X + 67 * mm, signature_y + 4.5 * mm)
    c.drawString(MARGIN_X + 90 * mm, signature_y + 5 * mm, "客戶簽名：")
    c.line(MARGIN_X + 108 * mm, signature_y + 4.5 * mm, PAGE_W - MARGIN_X, signature_y + 4.5 * mm)
    if signature:
        c.setFont("MSJH", 8)
        c.drawString(MARGIN_X + 23 * mm, signature_y + 5.3 * mm, signature.staff_name)
        draw_signature_image(
            c, signature, MARGIN_X + 109 * mm, signature_y + 5 * mm,
            PAGE_W - MARGIN_X - (MARGIN_X + 110 * mm), 12 * mm,
        )
        draw_signature_note(c, signature, "MSJH", MARGIN_X, 8 * mm)
    layout.footer()
    c.showPage()
    return layout.page - first_page + 1


def build_order_contract_pdf(order, signature=None):
    output = BytesIO()
    printed_at = timezone.localtime(signature.signed_at) if signature else timezone.localtime()
    # 先試排一次取得每聯頁數，頁次才能印總頁數；兩聯內容相同、頁數一致。
    pages_per_copy = draw_order_copy(
        canvas.Canvas(BytesIO(), pagesize=A4), order, "店家留存聯", 1, None, printed_at, signature
    )
    total_pages = pages_per_copy * 2
    c = canvas.Canvas(output, pagesize=A4)
    c.setTitle(f"{order.number} 車輛訂購單")
    c.setAuthor(validate_header(order.print_company_snapshot)["legal_name"])
    draw_order_copy(c, order, "店家留存聯", 1, total_pages, printed_at, signature)
    draw_order_copy(c, order, "客戶留存聯", pages_per_copy + 1, total_pages, printed_at, signature)
    c.save()
    return output.getvalue()
