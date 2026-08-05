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
right_style = ParagraphStyle(
    "right",
    parent=body_style,
    alignment=TA_RIGHT,
)


def p(text, style=body_style):
    return Paragraph(str(text), style)


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


def draw_table(c, data, col_widths, y_top, row_heights=None, styles=None):
    table = Table(data, colWidths=col_widths, rowHeights=row_heights)
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
    width, height = table.wrapOn(c, CONTENT_W, PAGE_H)
    table.drawOn(c, MARGIN_X, y_top - height)
    return y_top - height


def money(value):
    return f"{value:,.0f}"


def draw_order_page(c, order, copy_label, page_number, printed_at):
    y = PAGE_H - 11 * mm

    # Header
    c.setFillColor(GREEN)
    c.setFont("MSJH-Bold", 12.5)
    c.drawString(MARGIN_X, y - 5 * mm, "馭盛國際有限公司")
    c.setFillColor(MUTED)
    c.setFont("MSJH", 6.5)
    c.drawString(MARGIN_X, y - 10 * mm, "新北市汐止區康寧街470號、472號")
    c.drawString(MARGIN_X, y - 14 * mm, "電話：(02)2695-1112　｜　統編：83739807")

    c.setFillColor(INK)
    c.setFont("MSJH-Bold", 18)
    c.drawCentredString(PAGE_W / 2, y - 7 * mm, "車 輛 訂 購 單")
    c.setFillColor(RED)
    c.setFont("MSJH", 7)
    c.drawCentredString(PAGE_W / 2, y - 14 * mm, "本文件含個人資料，請妥善保管並限業務用途使用")

    meta_x = PAGE_W - MARGIN_X - 49 * mm
    c.setFillColor(INK)
    c.setFont("MSJH", 7.5)
    c.drawString(meta_x, y - 5 * mm, f"訂單日期：{order.order_date:%Y-%m-%d}")
    c.drawString(meta_x, y - 10 * mm, f"訂單編號：{order.number}")
    c.drawString(meta_x, y - 15 * mm, f"列印時間：{printed_at:%Y-%m-%d %H:%M}")
    c.drawString(meta_x, y - 20 * mm, f"頁次：{page_number} / 2")
    c.setStrokeColor(GREEN_2)
    c.setLineWidth(.7)
    c.roundRect(meta_x, y - 26 * mm, 49 * mm, 5 * mm, 1 * mm, fill=0, stroke=1)
    c.setFillColor(GREEN_2)
    c.setFont("MSJH-Bold", 8)
    c.drawCentredString(meta_x + 24.5 * mm, y - 24.3 * mm, copy_label)
    c.setStrokeColor(LINE)
    c.line(MARGIN_X, y - 29 * mm, MARGIN_X + CONTENT_W, y - 29 * mm)
    y -= 33 * mm

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
            p(order.get_payment_type_display()),
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
    y = draw_table(
        c,
        info_data,
        [19 * mm, 45 * mm, 19 * mm, 32 * mm, 19 * mm, 52 * mm],
        y,
        row_heights=[7 * mm, 7 * mm, 8 * mm, 8 * mm, 12 * mm],
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
    y -= 3 * mm
    y = draw_section_title(c, y, "車價與費用明細")
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
    separated_other_fees = order.plate_selection_fee + order.lien_registration_fee
    plate_amount = max(order.plate_insurance_fee - separated_other_fees, 0)
    if order.registration_date:
        plate_description = "領牌＋強制險"
        if order.registration_rate_class:
            plate_description += (
                f"（{safe(order.registration_rate_class)}／"
                f"{order.get_compulsory_insurance_period_display()}）"
            )
    else:
        plate_description = "領牌＋強制險，依單據收款"
    plate_money = money(plate_amount) if plate_amount else "—"
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
    y = draw_table(
        c,
        [price_header] + rows,
        [18 * mm, 40 * mm, 56 * mm, 14 * mm, 29 * mm, 29 * mm],
        y,
        row_heights=[7 * mm] + [7 * mm] * len(rows),
        styles=[
            ("BACKGROUND", (0, 0), (-1, 0), GREEN_LIGHT),
            ("TEXTCOLOR", (0, 0), (-1, 0), GREEN),
            ("FONTNAME", (0, 0), (-1, 0), "MSJH-Bold"),
            ("ROWBACKGROUNDS", (0, 1), (-1, len(rows)), [white, HexColor("#F6F9F7")]),
        ],
    )

    # Subsidy
    y -= 3 * mm
    y = draw_section_title(c, y, "汰舊／補助資料")
    subsidy_data = [
        [
            p("<b>補助類型</b>"),
            p(safe(order.subsidy_type if order.is_trade_in_subsidy else "無")),
            p("<b>新舊車主</b>"),
            p("同一人" if order.old_owner_same_as_owner else "不同人"),
        ]
    ]
    if not order.old_owner_same_as_owner:
        subsidy_data.append(
            [
                p("<b>舊車主姓名</b>"),
                p(safe(order.old_owner_name)),
                p("<b>舊車車牌</b>"),
                p(safe(order.trade_in_plate)),
            ]
        )
    y = draw_table(
        c,
        subsidy_data,
        [25 * mm, 68 * mm, 25 * mm, 68 * mm],
        y,
        row_heights=[7 * mm] * len(subsidy_data),
        styles=[
            ("BACKGROUND", (0, 0), (0, -1), GREEN_LIGHT),
            ("BACKGROUND", (2, 0), (2, -1), GREEN_LIGHT),
        ],
    )

    # Payment
    y -= 3 * mm
    y = draw_section_title(c, y, "收款資料")
    is_installment = order.payment_type == order.PaymentType.INSTALLMENT
    payment_first_row = [
        p("<b>主要付款</b>"),
        p(order.get_payment_type_display()),
    ]
    if is_installment:
        payment_first_row.extend(
            [
                p("<b>分期總額</b>"),
                p(f"${money(order.installment_amount or order.vehicle_price)}"),
                p("<b>應收</b>"),
                p(f"${money(order.actual_balance + order.deposit_amount)}"),
            ]
        )
    else:
        payment_first_row.extend(
            [
                p("<b>應收</b>"),
                p(f"${money(order.actual_balance + order.deposit_amount)}"),
                "",
                "",
            ]
        )
    payment_data = [
        payment_first_row,
        [
            p("<b>已收訂金</b>"),
            p(f"${money(order.deposit_amount)}"),
            p("<b>收款日期</b>"),
            p(order.deposit_date.strftime("%Y-%m-%d") if order.deposit_date else "—"),
            p("<b>收款方式</b>"),
            p(order.get_deposit_method_display() if order.deposit_method else "—"),
        ],
        [
            p("<b>預估尾款</b>"),
            p(f"${money(order.actual_balance)}"),
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
    y = draw_table(
        c,
        payment_data,
        [20 * mm, 36 * mm, 20 * mm, 36 * mm, 20 * mm, 54 * mm],
        y,
        row_heights=[7 * mm, 7 * mm, 8 * mm],
        styles=payment_styles,
    )

    # Terms
    y -= 3 * mm
    y = draw_section_title(c, y, "確認事項")
    terms = [
        [
            p(
                "□ 本人（或本公司）已自行審閱並詳讀中央或地方政府公告之補助辦法，"
                "包括申請資格、過戶限制及應備文件等。",
                small_style,
            )
        ],
        [
            p(
                "□ 本人（或本公司）了解店方僅協助代辦補助申請，補助金額及核准與否"
                "以主管機關審核結果為準。",
                small_style,
            )
        ],
        [
            p(
                "□ 本人（或本公司）了解並確認本訂購單所載車型、車色、價款、配件、"
                "付款方式及其他需求均屬正確。",
                small_style,
            )
        ],
        [
            p(
                "□ 本人（或本公司）了解機車屬於財產登記制，經領牌不再是新車，"
                "領牌後無法辦理退換貨。",
                small_style,
            )
        ],
    ]
    y = draw_table(
        c,
        terms,
        [CONTENT_W],
        y,
        row_heights=[7 * mm, 7 * mm, 7 * mm, 7 * mm],
        styles=[("BACKGROUND", (0, 0), (-1, -1), HexColor("#FBFCFB"))],
    )

    c.setFillColor(MUTED)
    c.setFont("MSJH", 6.6)
    c.drawString(
        MARGIN_X,
        y - 4 * mm,
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
    c.setFont("MSJH", 6.5)
    c.setFillColor(MUTED)
    c.drawRightString(PAGE_W - MARGIN_X, 8 * mm, copy_label)

    c.showPage()


def build_order_contract_pdf(order):
    output = BytesIO()
    printed_at = timezone.localtime()
    c = canvas.Canvas(output, pagesize=A4)
    c.setTitle(f"{order.number} 車輛訂購單")
    c.setAuthor("馭盛國際有限公司")
    draw_order_page(c, order, "店家留存聯", 1, printed_at)
    draw_order_page(c, order, "客戶留存聯", 2, printed_at)
    c.save()
    return output.getvalue()
