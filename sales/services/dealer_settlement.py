"""車行結算：合作車行賣出的訂單，本店與車行之間要收或要付的金額。

只計算、不儲存，也不影響車行掛帳（dealer_credit）與收款帳本。
- 現金購車（含刷卡等非分期）：原現金價（不扣已核准優惠）－ 傭金 ＋ 牌險費 ＋ 配件費
- 分期購車：配件費 － 傭金
正數＝向車行收；負數＝付給車行；零＝無需收付。
"""
from decimal import Decimal

ZERO = Decimal("0")


def _money(value):
    return Decimal(value or 0).quantize(Decimal("1"))


def dealer_settlement(order, profile=None):
    """回傳結算明細；非合作車行訂單或已取消／結案訂單回傳 None。"""
    from sales.models import OrderOperationsProfile, SalesOrder

    if order.source_type != SalesOrder.SourceType.DEALER or order.is_cancelled_sale:
        return None
    if profile is None:
        profile = OrderOperationsProfile.objects.filter(order=order).first()
    commission = _money(profile.dealer_commission_expense if profile else ZERO)
    accessories = _money(order.accessory_total)
    installment = order.payment_type == SalesOrder.PaymentType.INSTALLMENT
    if installment:
        terms = [
            {"key": "accessories", "label": "配件費", "sign": 1, "amount": accessories},
            {"key": "commission", "label": "傭金", "sign": -1, "amount": commission},
        ]
    else:
        terms = [
            {"key": "vehicle_price", "label": "原現金價", "sign": 1, "amount": _money(order.vehicle_price)},
            {"key": "commission", "label": "傭金", "sign": -1, "amount": commission},
            {"key": "plate_insurance", "label": "牌險費", "sign": 1, "amount": _money(order.plate_insurance_fee)},
            {"key": "accessories", "label": "配件費", "sign": 1, "amount": accessories},
        ]
    total = sum((term["sign"] * term["amount"] for term in terms), ZERO)
    if total > 0:
        direction, label = "collect", "向車行收"
    elif total < 0:
        direction, label = "pay", "付給車行"
    else:
        direction, label = "none", "無需收付"
    return {
        "dealer": order.source,
        "installment": installment,
        # 刷卡等非分期付款一律依現金價結算。
        "mode_label": "分期購車" if installment else f"{order.get_payment_type_display()}購車",
        "terms": terms,
        "total": total,
        "amount": abs(total),
        "direction": direction,
        "label": label,
        # 前端即時試算：除傭金外各項合計，傭金欄位修改時以此重算。
        "base_without_commission": total + commission,
    }
