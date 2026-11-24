"""配件金（折抵型配件，T-305 方案 A）：客人的配件金只折抵配件，最多折到配件小計 0 元，剩下的作廢。

配件金由店家吸收：不走折扣核准、不對帳、不影響淨利（配件本來就不進收支）。
明細只存主檔帶出的面額（例 −1,000），實際折抵在讀取時計算，加刪配件、改贈送、回匯都不必回頭改明細。
訂單配件合計（`SalesOrder.accessory_total`）、建單精靈試算、訂單頁、訂購單、匯出都用這裡的同一個算法。
"""
from dataclasses import dataclass, field
from decimal import Decimal
from types import SimpleNamespace

ZERO = Decimal("0")

# ---- 使用者決定的規則（2026-11-24 PM 先照建議實作；使用者改變決定時只改這三個值，
#      再同步說明頁 help/articles_manage.py「配件金」FAQ 與 BUSINESS_RULES「配件金」）----
# 每張訂單最多幾筆配件金；None＝不限筆數。每筆數量固定 1（資料庫約束）。
MAX_CREDIT_LINES_PER_ORDER = 1
# 車行來源的訂單能不能用配件金（車行單的配件費向車行收，折抵後車行結算跟著少收）。
ALLOW_DEALER_ORDERS = True
# 配件金能不能折安裝工資：True＝上限是「售價＋工資」的配件小計（與畫面「配件合計」同口徑）；
# False＝上限只算加購配件的售價。
CREDIT_COVERS_LABOR = True


@dataclass
class CreditBreakdown:
    subtotal: Decimal = ZERO        # 折抵前配件小計（非配件金的加購售價＋工資）×數量，贈送 0
    credit_face: Decimal = ZERO     # 配件金面額合計（正數）
    credit_applied: Decimal = ZERO  # 實際折抵（正數）
    applied: list = field(default_factory=list)  # 依明細順序，每筆配件金的實際折抵（正數）

    @property
    def credit_void(self):
        return self.credit_face - self.credit_applied

    @property
    def total(self):
        return self.subtotal - self.credit_applied


def _money(value):
    return value if value is not None else ZERO


def _is_gift(line):
    return getattr(line, "line_type", "") == "gift"


def breakdown(lines):
    """lines：有 is_credit、line_type、amount、labor_fee、quantity 的物件（訂單明細或 `form_lines` 的結果），依明細順序。"""
    lines = list(lines)
    result = CreditBreakdown()
    base = ZERO
    for line in lines:
        if line.is_credit or _is_gift(line):
            continue
        quantity = line.quantity or 0
        result.subtotal += (_money(line.amount) + _money(line.labor_fee)) * quantity
        base += (_money(line.amount) + (_money(line.labor_fee) if CREDIT_COVERS_LABOR else ZERO)) * quantity
    remaining = max(base, ZERO)
    for line in lines:
        if not line.is_credit:
            continue
        face = -_money(line.amount)
        use = min(face, remaining)
        remaining -= use
        result.credit_face += face
        result.credit_applied += use
        result.applied.append(use)
    return result


def display_lines(lines):
    """畫面與訂購單用：每列加上 `effective_total`（本列計入配件合計的金額）、配件金列另有 `credit_face`、`credit_void`。"""
    lines = list(lines)
    result = breakdown(lines)
    applied = iter(result.applied)
    for line in lines:
        if line.is_credit:
            use = next(applied)
            line.credit_face = -_money(line.amount)
            line.effective_total = -use
            line.credit_void = line.credit_face - use
        else:
            line.effective_total = line.line_total
    return lines


def form_lines(formset):
    """建單精靈還沒有明細物件時，從驗證後的表單資料組出明細（略過刪除、空白列）。"""
    rows = []
    for row in formset.forms:
        data = getattr(row, "cleaned_data", None) or {}
        if data.get("DELETE") or not (data.get("accessory_product") or (data.get("custom_name") or "").strip()):
            continue
        product = data.get("accessory_product")
        rows.append(SimpleNamespace(
            is_credit=bool(product is not None and product.kind == "credit"),
            line_type=data.get("line_type"), amount=data.get("amount"), labor_fee=data.get("labor_fee"),
            quantity=data.get("quantity") or 1,
        ))
    return rows


def credit_row_errors(credit_count, source_type):
    """整張訂單的配件金規則（筆數、車行單）。回傳 {第幾筆配件金（0 起）: [錯誤訊息]}，錯誤標在那一列。"""
    from sales.models import SalesOrder

    errors = {}
    if not ALLOW_DEALER_ORDERS and source_type == SalesOrder.SourceType.DEALER:
        for index in range(credit_count):
            errors.setdefault(index, []).append("車行單不能使用配件金。")
    if MAX_CREDIT_LINES_PER_ORDER is not None:
        for index in range(MAX_CREDIT_LINES_PER_ORDER, credit_count):
            errors.setdefault(index, []).append(f"每張訂單最多 {MAX_CREDIT_LINES_PER_ORDER} 筆配件金。")
    return errors
