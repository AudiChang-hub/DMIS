"""贈送強制險（T-309，使用者 2026-11-24 定案）：在訂單配件用「贈送」選主檔種類「強制險」的項目。

- 牌險費留空（系統計算）：牌險費＝試算合計－強制險（不小於 0），領牌時依領牌日重算也一樣扣掉。
- 牌險費填正數：填多少收多少，系統不另外扣；填 0 本來就全部吸收，行為照舊。
- 收支：強制險支出照列、強制險收入 0、規費收入＝規費支出、牌險手續費＝牌險費－規費支出。
- 「牌險差異待確認」門檻改成「試算合計－強制險」；不標「牌險少收」（手續費不再扣強制險）。
- 不計入配件小計、不影響配件金折抵（贈送列本來就 0 元）；一張單最多一筆；只能用「贈送」選。
火險、失竊險是一般配件，用「贈送」0 元選只是紀錄，不在這裡處理。
"""
from decimal import Decimal

from django.db.models import Exists, OuterRef

ZERO = Decimal("0")
# 列表用子查詢一次取出，避免逐張查詢（with_compulsory_gift_flag）。
ANNOTATION = "compulsory_insurance_gift"


def _money(value):
    return Decimal(str(value)) if value not in (None, "") else ZERO


def compulsory_insurance_gifted(order):
    """這張單有沒有送強制險；列表有 annotate 時直接用，有 prefetch 配件時不另外查。"""
    if not getattr(order, "pk", None):
        return False
    annotated = getattr(order, ANNOTATION, None)
    if annotated is not None:
        return bool(annotated)
    cache = getattr(order, "_prefetched_objects_cache", {}).get("accessories")
    if cache is not None:
        return any(line.is_compulsory_insurance for line in cache)
    from sales.models import AccessoryLine

    return AccessoryLine.objects.filter(order_id=order.pk, is_compulsory_insurance=True).exists()


def compulsory_gift_q():
    """送強制險的訂單（給查詢條件用）。"""
    from sales.models import AccessoryLine

    return Exists(AccessoryLine.objects.filter(order=OuterRef("pk"), is_compulsory_insurance=True))


def with_compulsory_gift_flag(orders):
    return orders.annotate(**{ANNOTATION: compulsory_gift_q()})


def auto_plate_fee(calculated_total, compulsory_fee, gifted):
    """牌險費留空（系統計算）時的牌險費：試算合計；送強制險時扣掉強制險，不小於 0。"""
    total = _money(calculated_total)
    if not gifted:
        return total
    return max(total - _money(compulsory_fee), ZERO)


def auto_plate_insurance_fee(order, calculated_total=None):
    """依這張單目前存的配件判斷有沒有送強制險，算出系統計算的牌險費。"""
    total = order.registration_calculated_total if calculated_total is None else calculated_total
    return auto_plate_fee(total, order.compulsory_insurance_fee, compulsory_insurance_gifted(order))


def plate_fee_reference(order):
    """「牌險差異待確認」比較的系統金額：試算合計；送強制險時是試算合計－強制險。"""
    return auto_plate_insurance_fee(order)


def refresh_auto_plate_fee(order):
    """配件存好之後呼叫：牌險費留空的單依配件重算牌險費（加或刪贈送強制險時才會變）。

    沒有送強制險、存檔前也沒送的單不碰（行為完全不變）。回傳是否改了牌險費（呼叫端負責存檔與重算應收）。
    """
    if not order.pk or not order.plate_insurance_auto:
        return False
    order._prefetched_objects_cache = {}
    fee = auto_plate_insurance_fee(order)
    if fee == _money(order.plate_insurance_fee):
        return False
    order.plate_insurance_fee = fee
    return True


def formset_gifts_compulsory(formset):
    """建單精靈還沒有明細時，從驗證後的配件表單判斷有沒有送強制險。"""
    for row in formset.forms:
        data = getattr(row, "cleaned_data", None) or {}
        if data.get("DELETE"):
            continue
        if getattr(row.instance, "is_compulsory_insurance", False):
            return True
    return False


def intake_plate_fee(form, formset):
    """建單精靈試算總價用的牌險費：留空時依配件扣掉贈送的強制險。"""
    instance = form.instance
    if not instance.plate_insurance_auto or not formset_gifts_compulsory(formset):
        return _money(instance.plate_insurance_fee)
    return auto_plate_fee(instance.registration_calculated_total, instance.compulsory_insurance_fee, True)
