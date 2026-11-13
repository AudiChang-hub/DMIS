"""欣鈴申請退稅同意書（T-158，使用者 2026-11-13 簡報第 6 頁）。

SUZUKI 油車且有汰舊的訂單，在「列印與簽署文件」印訂購單、個資同意書時一起印（紙本簽名，不做電子簽署）。
版面依使用者提供的 Word 原稿（欣鈴申請退稅同意書(空白)_20260109.doc，A4、微軟正黑體 10pt）重畫，
座標單位 mm、原點左上、y 為基線；原稿不進 repo。只讀訂單，不寫入任何資料。
"""
from io import BytesIO

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from sales.services.form_print import SANS, _company_name, _fit, _Page, _plain_text_mode, _text

DEALER = "欣鈴車業股份有限公司"
MAKER = "台鈴工業股份有限公司"
SIZE = 10
LINE_RIGHT = 196.0

# 原稿的換行位置（justify＝左右對齊到右界；最後一行靠左）。
BODY = (
    (20.1, 40.7, True, "為配合政府公告實施之貨物稅條例第十二條之五有關中古機車報廢或出口換購新車退還減徵新車貨物稅（以下簡稱"),
    (12.9, 46.9, True, "專案退還款），經銷商將協助買受人辦理申請中古機車報廢或出口換購新車退還減徵新車貨物稅（四仟元；惟新車所繳"),
    (12.9, 52.9, True, "貨物稅未達四千元者，實際退還金額以主管機關核定為準）。所需之手續，買受人特此同意須備齊相關證明文件提供予"),
    (12.9, 59.1, True, "出賣人，由出賣人提供予經銷商，以便向主管機關申請前述專案退還款。俟主管機關核實買受人資格與全部文件無誤並"),
    (12.9, 65.1, False, "予以撥款後，再由主管機關或出賣人轉支付予買受人。"),
    (20.0, 71.3, False, "一、專案退還款之申請資格："),
    (25.0, 77.3, True, "（一）於貨物稅條例第十二條之五公告生效日（以下簡稱生效日）起五年內（以下簡稱生效期間）報廢或出口中"),
    (35.4, 83.5, False, "古機車。前述生效期間為自民國 114 年 9 月 8 日起至 119 年 12 月 31 日止。"),
    (25.0, 89.6, False, "（二）中古機車指出廠四年以上機車排氣量一百五十立方公分以下機車。"),
    (25.0, 95.7, True, "（三）中古機車報廢或出口前、後六個月購買新車並完成新領牌照登記（換購新車期間，於生效日後報廢或出口"),
    (35.5, 101.8, False, "之前六個月及生效期間屆滿前報廢或出口之後六個月期間亦適用）。"),
    (20.0, 107.9, True, "二、專案退還款之相關證明文件，條列於下表。買受人須確認證明文件無誤且皆合乎規定之日期，備齊提供予出賣"),
    (25.4, 114.0, True, "人及經銷商，所有證明文件僅用於申請專案退還款。倘該等證明文件經主管機關審核資格不符而不予核撥專案退"),
    (25.4, 120.1, False, "還款，相關責任概由買受人自行承擔。"),
)
# 證明文件表：(文件, 報廢欄有勾選框)
DOCUMENT_ROWS = (
    ("監理機關加蓋戳記之汽機車新領牌照登記書影本", True),
    ("新購機車之行車執照影本", True),
    ("新車貨物稅完稅證明文件影本（由車廠或代理商提供）", True),
    ("中古機車之行車執照影本", True),
    ("中古機車之機車各項異動登記書報廢證明影本", True),
    ("行政院環境保護署廢機動車輛回收管制聯單影本或回收證明單影本", True),
    ("中古機車之出口報單出口證明聯影本及其他出口證明影本", False),
    ("新車車主存摺影本", True),
    ("中古機車與新機車車籍登記聲明書（新舊車主同一人免附；新舊車若不同人須附）", True),
    ("新、舊車主身份證影本或其他相關證明文件", True),
)
TABLE_LEFT, TABLE_RIGHT, SCRAP_X, EXPORT_X = 23.0, 198.0, 164.1, 181.6
TABLE_TOP, ROW_HEIGHT = 120.6, 6.22


def needs_tax_consent(order):
    """只有 SUZUKI 油車且有汰舊才印（使用者 2026-11-13）；汰舊依補助項目同步的 is_trade_in_subsidy。"""
    model = order.vehicle_model if order.vehicle_model_id else None
    return bool(
        model
        and order.is_trade_in_subsidy
        and not order.is_electric_vehicle
        and _text(model.brand).upper() == "SUZUKI"
    )


def payout_account_text(order):
    """補助撥款帳戶（銀行＋帳號）；沒填時空字串，表上留白手寫。"""
    profile = getattr(order, "operations", None)
    if profile is None:
        return ""
    return " ".join(part for part in (_text(profile.bank_name), _text(profile.remittance_account)) if part)


def _justify(page, left, y, value, font, size, right=LINE_RIGHT):
    """CJK 左右對齊：多出的寬度平均分到字距（同 Word 的左右對齊）。"""
    chars = list(value)
    total = sum(page.width(char, font, size) for char in chars)
    gap = max(0.0, (right - left - total) / max(1, len(chars) - 1))
    x = left
    for char in chars:
        page.text(x, y, char, font, size)
        x += page.width(char, font, size) + gap


def _blank(page, x1, x2, y, value="", *, bold=False, size=SIZE):
    """底線欄位：值置中、過長縮字。"""
    if value:
        fitted = _fit(value, SANS, size, x2 - x1 - 1, minimum=7, page=page)
        page.text((x1 + x2) / 2, y, value, SANS, fitted, bold=bold, align="center")
        if bold:
            _plain_text_mode(page.pdf)
    page.underline(x1, x2, y + 0.9)


def draw_tax_consent(pdf, order, *, account=""):
    page = _Page(pdf, A4[1])
    font = SANS
    model = order.vehicle_model
    model_number = _text(model.model_number) or _text(model.name)

    page.text(105.0, 13.3, "申請退稅同意書", font, 14, bold=True, align="center")
    _plain_text_mode(page.pdf)
    page.text(12.9, 22.0, "立同意書人:", font, SIZE)
    _blank(page, 31.0, 84.0, 22.0, _text(order.owner_name))
    page.text(85.6, 22.0, "（以下簡稱買受人）向", font, SIZE)
    _blank(page, 119.4, LINE_RIGHT, 22.0, _company_name(order), bold=True)
    page.text(12.9, 28.2, "（以下簡稱出賣人）購買由", font, SIZE)
    _blank(page, 54.7, 124.7, 28.2, DEALER, bold=True)
    page.text(126.5, 28.2, "（以下簡稱經銷商）銷售，", font, SIZE)
    _blank(page, 166.7, LINE_RIGHT, 28.2)
    _blank(page, 12.7, 72.2, 34.2, MAKER, bold=True)
    page.text(73.0, 34.2, "製造之", font, SIZE)
    _blank(page, 82.7, 140.3, 34.2, model_number)
    page.text(141.8, 34.2, "車型機車（以下簡稱新車）乙輛。", font, SIZE)

    for left, y, justify, line in BODY:
        if justify:
            _justify(page, left, y - 0.4, line, font, SIZE, right=197.2 if left == 25.4 else LINE_RIGHT)
        else:
            page.text(left, y - 0.4, line, font, SIZE)

    rows = len(DOCUMENT_ROWS) + 1
    bottom = TABLE_TOP + rows * ROW_HEIGHT
    for index in range(rows + 1):
        y = TABLE_TOP + index * ROW_HEIGHT
        page.line(TABLE_LEFT, y, TABLE_RIGHT, y)
    for x in (TABLE_LEFT, SCRAP_X, EXPORT_X, TABLE_RIGHT):
        page.line(x, TABLE_TOP, x, bottom)
    base = TABLE_TOP + 5.4
    page.text(SCRAP_X - 0.9, base, "（請勾選）中古機車", font, SIZE, align="right")
    page.text(SCRAP_X + 3.7, base, "口報廢", font, SIZE)
    page.text(EXPORT_X + 3.7, base, "口出口", font, SIZE)
    for index, (label, scrap) in enumerate(DOCUMENT_ROWS, start=1):
        y = base + index * ROW_HEIGHT
        page.text(TABLE_LEFT + 2.4, y, label, font, _fit(label, font, SIZE, SCRAP_X - TABLE_LEFT - 3, page=page))
        if scrap:
            page.text(SCRAP_X + 3.7, y, "口", font, SIZE)
        page.text(EXPORT_X + 3.7, y, "口", font, SIZE)

    page.text(20.0, 195.0, "三、收到核撥之專案退還款後，依照買受人指定之銀行/郵局帳號，支付予買受人：", font, SIZE)
    page.text(28.0, 201.1, "銀行/郵局帳號:", font, SIZE)
    _blank(page, 50.8, 117.5, 201.1, account)
    page.text(120.4, 201.1, "(附上存摺帳號頁之影本)", font, SIZE)

    y = 213.3
    page.text(23.5, y, "本申請案不收取任何手續費，若買受人未於民國", font, SIZE)
    for x1, x2, label_x, label in ((97.4, 106.8, 107.0, "年"), (110.4, 119.9, 120.1, "月"), (123.4, 132.9, 133.5, "")):
        page.underline(x1, x2, y + 0.6)
        if label:
            page.text(label_x, y, label, font, SIZE)
    _justify(page, 133.5, y, "日前備齊及提供本同意書背面資料予出賣", font, SIZE)
    page.text(12.9, 219.4, "人及經銷商，視為買受人放棄申請前述案退還款之機會，買受人不得有任何異議。", font, SIZE)

    sign = 11
    page.text(13.0, 231.6, "買受人:", font, sign)
    page.underline(23.6, 80.3, 232.4)
    page.text(83.8, 231.6, "（簽章）", font, sign)
    page.text(109.3, 231.6, "出賣人:", font, sign)
    page.underline(119.3, 175.5, 232.4)
    page.text(180.0, 231.6, "（簽章）", font, sign)
    page.text(12.9, 243.9, "身分證字號：", font, sign)
    _blank(page, 33.5, 89.7, 243.7, _text(order.owner_id_number), size=sign)

    y = 265.6
    for x, char in ((15.2, "中"), (23.9, "華"), (32.9, "民"), (42.1, "國"), (89.9, "年"), (137.9, "月"), (186.3, "日")):
        page.text(x, y, char, font, 12)
    day = order.order_date
    if day:
        for x, value in ((67.5, day.year - 1911), (115.6, day.month), (163.6, day.day)):
            page.text(x, y, str(value), font, 12, align="center")


def build_tax_consent_pdf(order, *, account=""):
    output = BytesIO()
    pdf = canvas.Canvas(output, pagesize=A4)
    pdf.setTitle(f"{order.number} 申請退稅同意書")
    pdf.setCreator("DMIS")
    draw_tax_consent(pdf, order, account=account)
    pdf.showPage()
    pdf.save()
    return output.getvalue()


def append_tax_consent(pdf, order, *, account=""):
    """接在訂購單、個資同意書後面（pdf 為 None 時只有退稅同意書）；回傳合併後的 PDF。"""
    from pypdf import PdfReader, PdfWriter

    consent = build_tax_consent_pdf(order, account=account)
    if not pdf:
        return consent
    writer = PdfWriter(clone_from=PdfReader(BytesIO(pdf)))
    for page in PdfReader(BytesIO(consent)).pages:
        writer.add_page(page)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()
