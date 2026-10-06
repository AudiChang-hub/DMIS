"""總價優惠：折數換算、下單時的總價試算與直接核定（不經待確認）。

金額收支頁的直接核定與下單時填寫的優惠共用 `approve_discount_now`，
確保核定欄位、折扣前總價與尾款重算只有一套規則。
"""
from decimal import ROUND_HALF_UP, Decimal

from django.utils import timezone

ZERO = Decimal("0")

DISCOUNT_FIELDS = (
    "approved_discount_amount", "discount_requested_amount", "discount_basis_total", "discount_reason",
    "discount_status", "discount_requested_at", "discount_requested_by", "discount_decided_at",
    "discount_decided_by", "discount_decision_note", "calculated_balance", "actual_balance",
)
INTAKE_DECISION_NOTE = "下單時填寫"
TOTAL_FIELDS = {
    "vehicle_model", "payment_type", "vehicle_price", "plate_insurance_fee", "installment_opening_fee",
    "intake_discount_mode", "intake_discount_amount", "intake_discount_rate", "intake_discount_reason",
}


def discount_from_rate(total, rate):
    """折數換算減少金額：9 為九折、9.5 為九五折；優惠後總價四捨五入到元。"""
    final = (total * rate / Decimal("10")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return total - final


def discount_amount(mode, amount, rate, total):
    """依調整方式回傳減少金額；折數須有總價才能換算，無法換算時回傳 None。"""
    if mode == "rate":
        if rate is None or total is None:
            return None
        return discount_from_rate(total, rate)
    return amount


def discount_error(amount, total):
    if amount is not None and total is not None and not (ZERO < amount <= total):
        return "優惠須大於零，且不可超過折扣前總價。"
    return ""


def approve_discount_now(order, *, amount, reason, actor_name, note):
    """直接核定總價優惠並重算尾款；呼叫端負責儲存、同步收支與寫入稽核。

    尾款原本跟著系統試算時一併更新；已人工調整的尾款保留不動。
    """
    automatic = order.actual_balance in {order.calculated_balance, order.calculate_balance()}
    now = timezone.now()
    order.approved_discount_amount = amount
    order.discount_requested_amount = amount
    order.discount_basis_total = order.pre_discount_total
    order.discount_reason = reason
    order.discount_status = type(order).DiscountStatus.APPROVED
    order.discount_requested_at = order.discount_decided_at = now
    order.discount_requested_by = order.discount_decided_by = actor_name
    order.discount_decision_note = note
    order.calculated_balance = order.calculate_balance()
    if automatic:
        order.actual_balance = order.calculated_balance
    return order


def _money(value):
    return value if value is not None else ZERO


def intake_pre_discount_total(form, formset, fee_formset):
    """以已驗證的下單內容試算折扣前總價（與 `SalesOrder.pre_discount_total` 同一組項目）。

    尚未建立訂單前無法讀取配件／費用明細，因此由明細表單的清理後資料加總；
    車價未定時回傳 None，留待送出時以實際訂單再檢查。
    """
    instance = form.instance
    if instance.vehicle_price is None:
        return None
    total = (
        _money(instance.vehicle_price) + _money(instance.plate_insurance_fee)
        + _money(instance.effective_installment_fee) + _money(instance.old_vehicle_tax)
    )
    for row in formset.forms:
        data = getattr(row, "cleaned_data", None) or {}
        if data.get("DELETE") or not (data.get("accessory_product") or (data.get("custom_name") or "").strip()):
            continue
        if data.get("line_type") == "gift":
            continue
        total += (_money(data.get("amount")) + _money(data.get("labor_fee"))) * (data.get("quantity") or 0)
    for row in fee_formset.forms:
        data = getattr(row, "cleaned_data", None) or {}
        if data.get("DELETE") or not data.get("name"):
            continue
        total += _money(data.get("amount"))
    return total


def intake_discount_requested(form):
    data = getattr(form, "cleaned_data", None) or {}
    return bool(data.get("intake_discount_amount") or data.get("intake_discount_rate"))


def intake_discount_preview(form, formset, fee_formset):
    """回傳 {before, amount, after, mode, rate}；未填優惠或無法試算時回傳 None。"""
    if not intake_discount_requested(form):
        return None
    data = form.cleaned_data
    before = intake_pre_discount_total(form, formset, fee_formset)
    amount = discount_amount(data.get("intake_discount_mode"), data.get("intake_discount_amount"),
                             data.get("intake_discount_rate"), before)
    if before is None or amount is None:
        return None
    return {"before": before, "amount": amount, "after": before - amount,
            "mode": data.get("intake_discount_mode"), "rate": data.get("intake_discount_rate")}


def validate_intake_discount(form, formset, fee_formset):
    """跨表單檢查下單優惠不可超過折扣前總價；錯誤掛在優惠欄位，精靈會回到付款步驟。

    影響總價的欄位或明細仍有錯誤時先不判斷，避免以不完整的金額誤擋。
    """
    if not intake_discount_requested(form) or TOTAL_FIELDS & set(form.errors):
        return None
    if any(formset.errors) or any(fee_formset.errors) or formset.non_form_errors() or fee_formset.non_form_errors():
        return None
    preview = intake_discount_preview(form, formset, fee_formset)
    if preview is None:
        return None
    message = discount_error(preview["amount"], preview["before"])
    if message:
        field = "intake_discount_rate" if preview["mode"] == "rate" else "intake_discount_amount"
        form.add_error(field, message)
        return None
    return preview


def apply_intake_discount(order, form, actor_name):
    """建立訂單後以實際明細重新換算並直接核定；超過總價時回傳錯誤訊息、不寫入。"""
    if not intake_discount_requested(form):
        return ""
    data = form.cleaned_data
    total = order.pre_discount_total
    amount = discount_amount(data.get("intake_discount_mode"), data.get("intake_discount_amount"),
                             data.get("intake_discount_rate"), total)
    message = discount_error(amount, total)
    if message:
        return message
    approve_discount_now(order, amount=amount, reason=data["intake_discount_reason"], actor_name=actor_name,
                         note=INTAKE_DECISION_NOTE)
    return ""


def intake_discount_detail(order, form):
    data = form.cleaned_data
    if data.get("intake_discount_mode") == "rate":
        return f"總價 {order.discount_basis_total:,.0f} 元 × {data['intake_discount_rate'].normalize():f} 折"
    return f"總價 {order.discount_basis_total:,.0f} 元減少 {order.approved_discount_amount:,.0f} 元"
