"""套表列印：取代 Excel 合併列印 Word 套表（信封、減徵貨物稅聲明書、簽收單）。

信封輸出 Word 檔：沿用使用者 Word 原稿（2026-10-14）的版面與 21×17 cm 自訂紙張，
瀏覽器無法把自訂紙張交給印表機，用 Word 列印才會和原本一樣（2026-10-17 使用者確認）。
聲明書、簽收單輸出 A4 PDF，版面座標取自 Word 套表，單位 mm、原點左上。
資料欄位與原合併欄位一一對應，見 FORM_FIELD_SOURCES。只讀訂單，不寫入任何資料。
"""
import zipfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

from django.utils import timezone
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

# 匯入即註冊黑體 MSJH（正式站為文泉驛正黑）；聲明書原稿為黑體。
from sales.services import order_contract_pdf  # noqa: F401

SANS = "MSJH"
KAI = "FormKai"
_KAI_CANDIDATES = (
    Path(r"C:\Windows\Fonts\kaiu.ttf"),
    Path("/usr/share/fonts/truetype/arphic-bkai00mp/bkai00mp.ttf"),
)
_kai_path = next((path for path in _KAI_CANDIDATES if path.exists()), None)
if _kai_path:
    pdfmetrics.registerFont(TTFont(KAI, str(_kai_path)))
else:  # 沒有標楷體時退回黑體，內容不缺字。
    KAI = SANS


@dataclass(frozen=True)
class FormSpec:
    key: str
    label: str
    paper: str
    hint: str


FORMS = (
    FormSpec("envelope", "信封", "Word 檔・21×17 cm", "依車種自動套用油車或電車版"),
    FormSpec("tax_declaration", "減徵貨物稅聲明書", "A4", "汰舊換新、新舊車主不同人時使用"),
    FormSpec("receipt", "簽收單", "A4", "送車時給客人簽收"),
)
FORM_KEYS = tuple(form.key for form in FORMS)
FORM_BY_KEY = {form.key: form for form in FORMS}

# 原 Word 合併欄位 → 系統來源（文件與測試共用，改來源時一併更新）。
FORM_FIELD_SOURCES = {
    "車行": "車行的來源代碼（沒有代碼用名稱）；本店、平台單空白",
    "車主名稱": "訂單車主姓名／公司名稱",
    "車種型號": "機種的純型號（沒有時用車型名稱）",
    "顏色": "訂單車色",
    "油：引擎號碼_電：車身號碼": "配車的引擎號碼（油車）或車身號碼（電車）；匯入舊單用歷史號碼",
    "車牌號碼": "最終車牌號碼",
    "車控帳號": "營運資料的車控帳號",
    "手機": "車主電話",
    "車控密碼": "營運資料的車控密碼（列印需本人密碼驗證並記入處理紀錄）；沒存密碼時印車主電話",
    "分期資訊": "營運資料的分期資訊；空白時由分期公司、期數、月付自動組成",
    "客服電話": "營運資料的客服電話；空白時用分期公司主檔的客服電話",
    "身分證字號": "車主證件號碼／統一編號",
    "戶籍地址": "車主戶籍／公司地址",
    "舊車車主": "舊車主姓名；同一人或沒填時用新車主",
    "舊車車主身分證": "舊車主身分證字號；同一人或沒填時用新車主",
    "舊車主聯絡地址、電話": "一律用新車主的戶籍地址與聯絡電話（使用者 2026-10-22 T-81）",
    "舊車牌照號碼": "舊車車牌",
    "舊車引擎號碼": "營運資料的舊車引擎號碼",
    "強制險年期（簽收單）": "訂單的強制險期間（一年／兩年）",
}

MAKER_NAMES = {
    "SUZUKI": "台鈴",
    "SYM": "三陽",
    "YAMAHA": "山葉",
    "KYMCO": "光陽",
    "PGO": "摩特動力",
    "AEON": "宏佳騰",
    "GOGORO": "睿能",
}
RECEIPT_INSURER = "富邦產物險"
RECEIPT_DOCUMENTS = ("行照", "新領牌照登記書", "機車出廠與貨物稅完稅照證")
NOTE_MAX_CHARS = 300
ADDRESS_MAX_CHARS = 120


def _text(value):
    return str(value or "").strip()


def _money(value):
    return f"{value:,.0f}" if value else ""


def _identifier(order):
    vehicle = order.allocated_vehicle if order.allocated_vehicle_id else None
    if vehicle:
        value = vehicle.frame_number if order.is_electric_vehicle else vehicle.engine_number
        if value:
            return value
    snapshot = getattr(order, "legacy_snapshot", None)
    return _text(getattr(snapshot, "vehicle_identifier", ""))


def _installment_lines(order, profile):
    info = _text(getattr(profile, "installment_info", ""))
    if not info and order.payment_type == order.PaymentType.INSTALLMENT:
        company = _text(order.installment_company) or _text(getattr(order.installment_company_master, "name", ""))
        if company or order.installment_periods:
            info = f"分期{company}"
            if order.installment_periods:
                info += f"  {order.installment_periods} 期"
            if order.installment_monthly:
                info += f"，每期 {_money(order.installment_monthly)}"
    phone = _text(getattr(profile, "customer_service_phone", ""))
    if not phone and order.payment_type == order.PaymentType.INSTALLMENT and order.installment_company_master_id:
        phone = _text(order.installment_company_master.customer_service_phone)
    if phone and "客服" not in phone:
        phone = f"客服電話：{phone}"
    return info, phone


def _company_name(order):
    name = _text((order.print_company_snapshot or {}).get("legal_name"))
    if name:
        return name
    from sales.models import PrintCompany
    company = PrintCompany.objects.filter(key="home").only("legal_name").first()
    return _text(getattr(company, "legal_name", ""))


def has_control_password(order):
    """電車且已存車控密碼：列印信封時要先通過本人密碼驗證。"""
    profile = getattr(order, "operations", None)
    return bool(order.is_electric_vehicle and getattr(profile, "vehicle_control_password_encrypted", ""))


def _old_owner(order, field, old_value):
    """舊車主資料：同一人或該欄沒填時，改用新車主的同一欄（使用者 2026-10-14）。"""
    if order.old_owner_same_as_owner or not _text(old_value):
        return _text(getattr(order, field))
    return _text(old_value)


def form_values(order, *, reveal_secrets=False):
    """一張訂單在套表上會用到的所有值（皆為字串）。

    reveal_secrets：呼叫端已確認本人驗證，才解密車控密碼。
    """
    profile = getattr(order, "operations", None)
    model = order.vehicle_model
    source = order.source if order.source_id else None
    dealer = ""
    if source and source.source_type == source.SourceType.DEALER:
        dealer = _text(source.code) or _text(source.name)
    installment_info, service_phone = _installment_lines(order, profile)
    brand = _text(model.brand)
    return {
        "dealer": dealer,
        "owner_name": _text(order.owner_name),
        "owner_id_number": _text(order.owner_id_number),
        "owner_phone": _text(order.owner_phone),
        "owner_address": _text(order.owner_address),
        "brand": brand,
        "maker": MAKER_NAMES.get(brand.upper(), brand),
        "model_number": _text(model.model_number) or _text(model.name),
        "color": _text(order.color.name if order.color_id else ""),
        "identifier": _identifier(order),
        "identifier_label": "車身號碼" if order.is_electric_vehicle else "引擎號碼",
        "plate": _text(order.final_plate_number),
        "vehicle_control_account": _text(getattr(profile, "vehicle_control_account", "")),
        "installment_info": installment_info,
        "customer_service_phone": service_phone,
        "vehicle_control_password": _control_password(order, profile, reveal_secrets),
        "insurance": f"{RECEIPT_INSURER} {order.compulsory_insurance_period or 1} 年",
        "old_owner_name": _old_owner(order, "owner_name", order.old_owner_name),
        "old_owner_id_number": _old_owner(order, "owner_id_number", order.old_owner_id_number),
        # 套表上的聯絡地址與電話一律印新車主的戶籍地址與聯絡電話（使用者 2026-10-22 T-81）；舊車主戶籍不再輸入。
        "old_owner_phone": _text(order.owner_phone),
        "old_owner_address": _text(order.owner_address),
        "old_plate": _text(order.trade_in_plate),
        "old_engine": _text(getattr(profile, "old_vehicle_engine_number", "")),
        "company": _company_name(order),
        "delivery_address": _text(order.delivery_destination),
    }


def _control_password(order, profile, reveal):
    """沒存密碼時沿用原套表印車主電話；有存但未驗證時不解密（呼叫端會先擋下）。"""
    encrypted = getattr(profile, "vehicle_control_password_encrypted", "")
    if not encrypted:
        return _text(order.owner_phone)
    if not reveal:
        return ""
    from sales.services.secret_fields import decrypt_secret
    return _text(decrypt_secret(encrypted))


def default_receipt_note(values):
    if values["old_plate"]:
        return f"■收舊車 {values['old_plate']}、行照、鑰匙、稅金。"
    return ""


def form_warnings(order, values):
    """每份套表缺少的重要資料；只提示，不阻擋列印（空白處可手寫）。"""
    warnings = {key: [] for key in FORM_KEYS}
    for key in FORM_KEYS:
        if not values["identifier"]:
            warnings[key].append(values["identifier_label"])
    if not values["plate"]:
        warnings["envelope"].append("車牌")
        warnings["receipt"].append("車牌")
    if order.is_electric_vehicle:
        if not values["vehicle_control_account"]:
            warnings["envelope"].append("車控帳號")
        if not has_control_password(order):
            warnings["envelope"].append("車控密碼（改印車主電話）")
    if not order.is_trade_in_subsidy and not values["old_plate"]:
        warnings["tax_declaration"].append("此單沒有汰舊資料")
    else:
        for field, label in (("old_plate", "舊車牌"), ("old_engine", "舊車引擎號碼")):
            if not values[field]:
                warnings["tax_declaration"].append(label)
    return warnings


def suggested_forms(order, values):
    """預設勾選：信封、簽收單都要；有汰舊才勾聲明書。"""
    picked = ["envelope", "receipt"]
    if order.is_trade_in_subsidy or values["old_plate"]:
        picked.insert(1, "tax_declaration")
    return picked


# ── 繪圖工具（座標 mm，y 為基線距頁頂） ──────────────────────────────


class _Page:
    def __init__(self, pdf, height, latin=None):
        self.pdf = pdf
        self.height = height
        self.latin = latin  # 英數字另用的字型（簽收單原稿英數字為 Arial）

    def _runs(self, value, font):
        if not self.latin:
            return [(value, font)]
        runs = []
        for char in value:
            run_font = self.latin if char.isascii() and char != " " else font
            if runs and runs[-1][1] == run_font:
                runs[-1] = (runs[-1][0] + char, run_font)
            else:
                runs.append((char, run_font))
        return runs

    def text(self, x, y, value, font, size, *, bold=False, align="left"):
        if not value:
            return
        pdf = self.pdf
        width = self.width(value, font, size) * mm
        left = x * mm - (width if align == "right" else width / 2 if align == "center" else 0)
        text = pdf.beginText(left, self.height - y * mm)
        if bold:  # 標楷體沒有粗體字型，與 Word 相同以描邊加粗。
            text.setTextRenderMode(2)
            pdf.setLineWidth(size * 0.035)
        for run, run_font in self._runs(value, font):
            text.setFont(run_font, size)
            text.textOut(run)
        pdf.drawText(text)
        if bold:
            pdf.setLineWidth(1)

    def width(self, value, font, size):
        return sum(pdfmetrics.stringWidth(run, run_font, size) for run, run_font in self._runs(value, font)) / mm

    def distribute(self, left, right, y, value, font, size):
        """左右分散對齊（Word 的「分散對齊」）。"""
        chars = list(value)
        if len(chars) == 1:
            self.text(left, y, value, font, size)
            return
        total = sum(self.width(char, font, size) for char in chars)
        gap = (right - left - total) / (len(chars) - 1)
        x = left
        for char in chars:
            self.text(x, y, char, font, size)
            x += self.width(char, font, size) + gap

    def underline(self, x1, x2, y):
        self.pdf.setLineWidth(0.5)
        self.pdf.line(x1 * mm, self.height - y * mm, x2 * mm, self.height - y * mm)

    def line(self, x1, y1, x2, y2, width=0.5):
        self.pdf.setLineWidth(width)
        self.pdf.line(x1 * mm, self.height - y1 * mm, x2 * mm, self.height - y2 * mm)


def wrap(value, font, size, width_mm, *, first_width_mm=None, page=None):
    """中英文混排逐字換行；英數字詞不拆開。回傳行陣列。"""
    measure = page.width if page else (lambda text, name, points: pdfmetrics.stringWidth(text, name, points) / mm)
    lines, current = [], ""
    limit = first_width_mm or width_mm
    tokens = []
    word = ""
    for char in value:
        if char.isascii() and not char.isspace():
            word += char
            continue
        if word:
            tokens.append(word)
            word = ""
        tokens.append(char)
    if word:
        tokens.append(word)
    for token in tokens:
        if token == "\n":
            lines.append(current)
            current, limit = "", width_mm
            continue
        candidate = current + token
        if current and measure(candidate, font, size) > limit:
            lines.append(current)
            current, limit = token.lstrip(), width_mm
        else:
            current = candidate
    lines.append(current)
    return lines


def _fit(value, font, size, width_mm, minimum=8, page=None):
    measure = page.width if page else (lambda text, name, points: pdfmetrics.stringWidth(text, name, points) / mm)
    while size > minimum and measure(value, font, size) > width_mm:
        size -= 0.5
    return size


ROC_DIGITS = "〇一二三四五六七八九"


def _roc_number(value):
    """月日用一般中文數字：十、十四、二十一。"""
    tens, ones = divmod(value, 10)
    if tens == 0:
        return ROC_DIGITS[ones]
    head = "" if tens == 1 else ROC_DIGITS[tens]
    return f"{head}十{ROC_DIGITS[ones] if ones else ''}"


def roc_chinese_date(day):
    year = "".join(ROC_DIGITS[int(digit)] for digit in str(day.year - 1911))
    return f"中華民國{year}年{_roc_number(day.month)}月{_roc_number(day.day)}日"


# ── 各套表 ─────────────────────────────────────────────────────────────


def _underlined(page, x, y, value, font, size, min_width):
    """「＿值＿」：值置中、底線至少 min_width mm，回傳下一個字的 x。"""
    width = max(min_width, page.width(value, font, size) + 6)
    page.text(x + width / 2, y, value, font, size, align="center")
    page.underline(x, x + width, y + 1.2)
    return x + width


def _flow(page, x, y, parts, font, size, *, left, right, leading):
    """依序繪製文字與底線欄位，超出右界自動換行。parts：("text", 字串) 或 ("field", 值, 最小寬)。"""
    for part in parts:
        if part[0] == "field":
            value, min_width = part[1], part[2]
            width = max(min_width, page.width(value, font, size) + 6)
            if x + width > right:
                x, y = left, y + leading
            x = _underlined(page, x, y, value, font, size, min_width)
            continue
        for index, line in enumerate(wrap(part[1], font, size, right - left, first_width_mm=right - x, page=page)):
            if index:
                x, y = left, y + leading
            page.text(x, y, line, font, size)
            x += page.width(line, font, size)
    return x, y


def _draw_tax_declaration(pdf, order, values, today):
    page = _Page(pdf, A4[1])
    font = SANS
    page.text(107.6, 18.3, "中古機車與新機車車籍登記之車主非同一人聲明書", font, 18, align="center")
    left, right, leading = 18.0, 188.5, 10.0
    _, y = _flow(page, left, 30.7, (
        ("text", "報廢或出口中古機車車籍登記之車主 "),
        ("field", values["old_owner_name"], 26),
        ("text", "（車牌號碼："),
        ("field", values["old_plate"], 30),
        ("text", "、引擎號碼："),
        ("field", values["old_engine"], 42),
        ("text", "）同意由購買新機車之新領牌照車籍登記之車主"),
    ), font, 14, left=left, right=right, leading=leading)
    _flow(page, left, y + leading, (
        ("field", values["owner_name"], 24),
        ("text", "（車牌號碼："),
        ("field", values["plate"], 30),
        ("text", "、引擎號碼："),
        ("field", values["identifier"], 34),
        ("text", "）具領中古機車報廢或出口換購新車減徵退還新車貨物稅稅款，所送資料無違法作假之情事，否則願繳回全額已撥付之款項，並負相關法律責任。"),
    ), font, 14, left=left, right=right, leading=leading)

    page.text(41.0, 92.7, "此致", font, 14)
    for x, label in ((17.5, "財政部"), (57.0, "國稅局"), (91.7, "分局(稽徵所、服務處)")):
        page.text(x, 102.8, label, font, 14)
    for x, label in ((17.5, "財政部關務署"), (62.0, "關"), (91.7, "分關")):
        page.text(x, 111.9, label, font, 14)

    def signer_block(top, *, title, name, id_number, guardian, address, phone):
        rows = (
            (top, f"{title}：{name}", True),
            (top + 10.9, f"身分證統一編號/營利事業或機關團體統一編號：{id_number}", False),
            (top + 22.7, "營利事業或機關團體負責人姓名：", True),
            (top + 34.5, guardian, True),
            (top + 46.4, "法定代理人身分證統一編號：", False),
        )
        for y, label, signs in rows:
            page.text(14.1, y, label, font, _fit(label, font, 14, 150))
            if signs:
                page.text(166.9, y - (0 if y == top else 1.1), "（簽章）", font, 14)
        y = top + 58.2
        page.text(14.1, y, "聯絡地址：", font, 14)
        page.text(38.7, y, address, font, _fit(address, font, 11, 80, minimum=7))
        page.text(121.6, y, "聯絡電話：", font, 14)
        page.text(153.6, y, phone, font, 12)

    signer_block(
        132.8, title="報廢或出口中古機車車籍登記之車主", name=values["old_owner_name"],
        id_number=values["old_owner_id_number"], guardian="未成年之中古機車車籍登記車主之法定代理人：",
        address=values["old_owner_address"], phone=values["old_owner_phone"],
    )
    signer_block(
        202.8, title="購買新機車之新領牌照車籍登記之車主", name=values["owner_name"],
        id_number=values["owner_id_number"], guardian="未成年購買新機車之新領牌照車籍登記車主之法定代理人：",
        address=values["owner_address"], phone=values["owner_phone"],
    )
    page.distribute(12.5, 199.2, 277.0, roc_chinese_date(today), font, 16)


def _draw_receipt(pdf, order, values, today, note, address):
    page = _Page(pdf, A4[1], latin="Helvetica")
    font = KAI
    dx = -3.0  # 原稿為 Letter，平移置中到 A4。
    for x, char in ((83.4, "簽"), (104.6, "收"), (125.8, "單")):
        page.text(x + dx, 23.9, char, font, 24, bold=True)
    year, month = today.year - 1911, today.month
    head = f"民國 {year} 年 {month:02d} 月　　日，已收到由"
    page.text(20.0 + dx, 42.6, head, font, 20)
    company = values["company"]
    company_x = 20.0 + dx + page.width(head, font, 20)
    page.text(company_x, 42.6, company, font, _fit(company, font, 20, 191 + dx - company_x, page=page), bold=True)
    page.text(20.0 + dx, 55.3, f"交付：{values['maker']}機車壹台", font, 20, bold=True)

    left, mid, right = 22.0 + dx, 57.5 + dx, 193.9 + dx
    rows = (
        ("廠牌", values["maker"], 6.5, False),
        ("機種", f"{values['brand']}機車 {values['model_number']}".strip(), 6.6, True),
        (values["identifier_label"], values["identifier"], 6.5, False),
        ("顏色", values["color"], 6.6, False),
        ("牌照號碼", values["plate"], 10.5, True),
        ("車主姓名", values["owner_name"], 6.6, False),
        ("身份證字號", values["owner_id_number"], 6.5, False),
        ("電話", values["owner_phone"], 6.6, False),
        ("機車證件", "", 19.2, False),
        ("強制險", values["insurance"], 6.5, False),
    )
    top = 65.9
    page.line(left, top, right, top)
    for label, value, height, bold in rows:
        bottom = top + height
        base = top + height / 2 + 1.5
        page.distribute(23.9 + dx, 55.7 + dx, base, label, font, 12)
        if label == "機車證件":
            for index, item in enumerate(RECEIPT_DOCUMENTS):
                y = top + 4.5 + index * 6.4
                page.pdf.circle((59.4 + dx + 1.3) * mm, page.height - (y - 1.3) * mm, 0.9 * mm, stroke=0, fill=1)
                page.text(63.2 + dx, y, item, font, 12)
        else:
            page.text(59.4 + dx, base, value, font, _fit(value, font, 12, right - mid - 4, page=page), bold=bold)
        page.line(left, bottom, right, bottom)
        top = bottom
    page.line(left, 65.9, left, top)
    page.line(mid, 65.9, mid, top)
    page.line(right, 65.9, right, top)

    text_left, text_right, leading = 20.0 + dx, 192.0 + dx, 12.7
    y = 156.4
    page.text(text_left, y, "備註：", font, 18)
    indent = text_left + page.width("備註：", font, 18)
    note_lines = []
    for paragraph in (note or "").splitlines() or [""]:
        note_lines.extend(wrap(paragraph, font, 18, text_right - indent, page=page))
    for index, line in enumerate(note_lines[:4]):
        page.text(indent, y + index * leading, line, font, 18)
    y = max(194.5, y + len(note_lines[:4]) * leading)
    label = "交車住址："
    page.text(text_left, y, label, font, 18, bold=True)
    address_x = text_left + page.width(label, font, 18)
    page.text(address_x, y, address, font, _fit(address, font, 18, text_right - address_x, minimum=11, page=page), bold=True)
    page.text(68.0 + dx, max(220.0, y + 25.5), "實收無誤", font, 20)
    page.text(117.4 + dx, max(220.0, y + 25.5), "特此證明", font, 20)
    sign_y = max(245.5, y + 51.0)
    page.text(72.8 + dx, sign_y, "收貨人簽名：", font, 20)
    page.line(115.1 + dx, sign_y + 0.8, 195.6 + dx, sign_y + 0.8, 0.8)


@dataclass
class PrintJob:
    order: object
    form: str
    note: str = ""
    address: str = ""


def build_forms_pdf(jobs, *, group_by_form=True, today=None):
    """依序輸出多張訂單的 A4 套表（聲明書、簽收單）為單一 PDF；信封另出 Word 檔。

    group_by_form：同一種套表排在一起；否則依訂單順序。
    """
    today = today or timezone.localdate()
    if group_by_form:
        jobs = sorted(jobs, key=lambda job: FORM_KEYS.index(job.form))
    output = BytesIO()
    pdf = canvas.Canvas(output, pagesize=A4)
    pdf.setTitle("套表列印")
    pdf.setCreator("DMIS")
    for job in jobs:
        values = form_values(job.order)
        if job.form == "tax_declaration":
            _draw_tax_declaration(pdf, job.order, values, today)
        elif job.form == "receipt":
            _draw_receipt(pdf, job.order, values, today, job.note, job.address)
        else:
            raise ValueError(f"PDF 不含這種套表：{job.form}")
        pdf.showPage()
    pdf.save()
    return output.getvalue()


# ── 信封 Word 檔 ───────────────────────────────────────────────────────
# oil.xml／ev.xml 是 Word 原稿內文（合併欄位換成 {{form_values 鍵}}，不含範例資料），
# 其餘檔案為原稿樣式、主題與相容性設定，表格縮排與行距才會和原稿一致。
ENVELOPE_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "form_templates" / "envelope"
ENVELOPE_FIELDS = (
    "dealer", "owner_name", "model_number", "color", "identifier", "plate",
    "vehicle_control_account", "vehicle_control_password", "installment_info", "customer_service_phone",
)
# 原稿紙張 21×17 cm 橫向（twip）；邊界左 5、右 2 cm，上／下油車 4／2 cm、電車 3.7／1.5 cm。
_ENVELOPE_MARGINS = {False: (2268, 1134), True: (2098, 851)}
_W_NS = (
    'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
)
_ENVELOPE_PARTS = {
    "[Content_Types].xml": (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
        '<Override PartName="/word/settings.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml"/>'
        '<Override PartName="/word/fontTable.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.fontTable+xml"/>'
        '<Override PartName="/word/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>'
        '</Types>'
    ),
    "_rels/.rels": (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        '</Relationships>'
    ),
    "word/_rels/document.xml.rels": (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/settings" Target="settings.xml"/>'
        '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/fontTable" Target="fontTable.xml"/>'
        '<Relationship Id="rId4" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="theme/theme1.xml"/>'
        '</Relationships>'
    ),
}
_ENVELOPE_FILES = {
    "word/styles.xml": "styles.xml",
    "word/settings.xml": "settings.xml",
    "word/fontTable.xml": "fontTable.xml",
    "word/theme/theme1.xml": "theme1.xml",
}


def _envelope_section(electric):
    top, bottom = _ENVELOPE_MARGINS[electric]
    return (
        '<w:sectPr><w:pgSz w:w="11907" w:h="9639" w:orient="landscape" w:code="9"/>'
        f'<w:pgMar w:top="{top}" w:right="1134" w:bottom="{bottom}" w:left="2835" w:header="851" w:footer="992" w:gutter="0"/>'
        '<w:cols w:space="425"/><w:docGrid w:type="lines" w:linePitch="360"/></w:sectPr>'
    )


def _envelope_body(order, values):
    body = (ENVELOPE_TEMPLATE_DIR / ("ev.xml" if order.is_electric_vehicle else "oil.xml")).read_text(encoding="utf-8").strip()
    for key in ENVELOPE_FIELDS:
        body = body.replace("{{%s}}" % key, escape(" ".join(values[key].splitlines())))
    return body


def build_envelopes_docx(orders):
    """每張訂單一頁信封（各自一節，油／電邊界不同），等同 Word 合併列印的結果。"""
    pages = [(order, form_values(order, reveal_secrets=True)) for order in orders]
    if not pages:
        raise ValueError("沒有要印的信封")
    parts = []
    for index, (order, values) in enumerate(pages):
        body = _envelope_body(order, values)
        section = _envelope_section(order.is_electric_vehicle)
        if index < len(pages) - 1:
            # 分節符號放在原稿最後一個空白段落，不多佔一行。
            cut = body.rindex("</w:pPr></w:p>")
            body = body[:cut] + section + body[cut:]
        else:
            body += section
        parts.append(body)
    document = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document {_W_NS}><w:body>'
        + "".join(parts) + "</w:body></w:document>"
    )
    output = BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as package:
        for name, content in _ENVELOPE_PARTS.items():
            package.writestr(name, content)
        package.writestr("word/document.xml", document)
        for name, source in _ENVELOPE_FILES.items():
            package.write(ENVELOPE_TEMPLATE_DIR / source, name)
    return output.getvalue()
