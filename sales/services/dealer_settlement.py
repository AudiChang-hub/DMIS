"""車行結算：車行賣出的訂單，本店與車行之間要收或要付的金額。

只計算、不儲存，也不影響車行掛帳（dealer_credit）與收款帳本。
- 現金購車（含刷卡等非分期）：原現金價（不扣已核准優惠）－ 傭金 ＋ 牌險費 ＋ 配件費
- 分期購車（系統建立）：分期外應收（牌險、選號、配件等由車行付的費用，扣訂金前）－ 傭金（T-154）；
  分期總價本身固定、不扣傭金。Excel 匯入的分期單照舊：配件費 － 傭金。
正數＝向車行收；負數＝付給車行；零＝無需收付。
"""
from decimal import Decimal

ZERO = Decimal("0")


def _money(value):
    return Decimal(value or 0).quantize(Decimal("1"))


def _installment_fee_terms(order, accessories):
    """分期車行單由車行付的費用＝分期外應收（`installment_customer_part`，扣訂金前），逐項列出。

    使用者 2026-11-12（T-154）：「就算是選號費，也是要算在跟車行收款的費用裡」，跟傭金互抵。
    牌險、選號依實際向客人收的金額（收支人工調整過領牌收入時跟著改）；配件費一律列出，其餘有金額才列。
    """
    from sales.services.customer_receivable import plate_insurance_charged

    extra = _money(order.registration_extra_fee_total)
    candidates = [
        ("customer_vehicle", "分期外車款", 1, _money(order.customer_vehicle_split_amount)),
        ("plate_insurance", "牌險費", 1, _money(plate_insurance_charged(order)) - extra),
        ("plate_selection", "選號費", 1, extra),
        ("other_fees", "其他費用", 1, _money(order.other_fee_total)),
        ("old_vehicle_tax", "舊車稅", 1, _money(order.old_vehicle_tax)),
        ("accessories", "配件費", 1, accessories),
        ("installment_fee", "分期開辦費", 1, _money(order.effective_installment_fee)),
        ("discount", "已核准折扣", -1, _money(order.approved_discount_amount)),
        ("old_vehicle_valuation", "舊車估價", -1, _money(order.old_vehicle_valuation)),
    ]
    # 人工調整的領牌收入可能少於選號費，牌險那一項為負時改列減項。
    return [{"key": key, "label": label, "sign": sign if amount >= 0 else -sign, "amount": abs(amount)}
            for key, label, sign, amount in candidates if amount or key == "accessories"]


def dealer_settlement(order, profile=None):
    """回傳結算明細；非車行訂單或已取消／結案訂單回傳 None。"""
    from sales.models import OrderOperationsProfile, SalesOrder

    if order.source_type != SalesOrder.SourceType.DEALER or order.is_cancelled_sale:
        return None
    if profile is None:
        profile = OrderOperationsProfile.objects.filter(order=order).first()
    commission = _money(profile.dealer_commission_expense if profile else ZERO)
    # 傭金支出含期間結束後自動入帳的台數獎金（T-148）；這筆另外付給車行，不扣本單應收。
    from sales.services.dealer_commission import commission_volume_bonus
    volume_bonus = _money(commission_volume_bonus(order, profile)) if profile else ZERO
    accessories = _money(order.accessory_total)
    installment = order.payment_type == SalesOrder.PaymentType.INSTALLMENT
    # 系統建立的分期車行單：牌險、選號、配件等由車行付的費用與傭金互抵（T-154）；Excel 匯入單照舊。
    installment_fees = installment and order.cash_receivable_v2 and not hasattr(order, "legacy_snapshot")
    if installment_fees:
        terms = [*_installment_fee_terms(order, accessories),
                 {"key": "commission", "label": "傭金", "sign": -1, "amount": commission}]
    elif installment:
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
        if _money(order.registration_extra_fee_total):
            # 牌險不含選號（使用者 2026-10-15），有選號時另列。
            terms.insert(3, {"key": "plate_selection", "label": "選號費", "sign": 1,
                             "amount": _money(order.registration_extra_fee_total)})
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
        "installment_fees": installment_fees,
        "total": total,
        "amount": abs(total),
        "direction": direction,
        "label": label,
        # 前端即時試算：除傭金外各項合計，傭金欄位修改時以此重算。
        "base_without_commission": total + commission,
        "volume_bonus": volume_bonus,
    }
