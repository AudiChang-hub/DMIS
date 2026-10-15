"""客戶尾款的共同讀取口徑；不修改收款紀錄或歷史訂單。"""
from decimal import Decimal


def default_customer_balance(order):
    zero = Decimal("0")
    if order.payment_type == "installment":
        if order.cash_receivable_v2:
            # 分期公司只分車款（開辦費由撥款處理）；牌險、選號、其他費用、舊車稅與配件由客人付（使用者 2026-10-10）。
            customer_part = (
                plate_insurance_charged(order) + order.other_fee_total
                + (order.old_vehicle_tax or zero) + order.accessory_total
            )
            return max(customer_part - (order.deposit_amount or zero), zero)
        return max((order.actual_balance or zero) - (order.installment_amount or zero), zero)
    return order.actual_balance or zero


PLATE_INCOME_FIELDS = (
    "registration_tax_income", "compulsory_insurance_income", "plate_selection_income", "agency_fee_income",
)


def plate_insurance_charged(order):
    """向客人收的牌險＋選號（含舊有動保設定費）。

    預設就是訂單牌險＋選號；在收支頁人工調整過「領牌相關」收入（例如分期吸收規費與強制險、只收選號）時，
    改以領牌稅金＋強制險＋選號＋代辦費收入合計，應收跟著改（使用者 2026-10-14；
    2026-10-15 起牌險與選號的溢收記在代辦費收入）。
    """
    zero = Decimal("0")
    from sales.models import OrderOperationsProfile

    try:
        profile = order.operations if order.pk else None
    except OrderOperationsProfile.DoesNotExist:
        profile = None
    lien = order.lien_registration_fee or zero
    if profile is None or not set(PLATE_INCOME_FIELDS) & set(profile.manual_financial_fields or []):
        return (order.plate_insurance_fee or zero) + (order.plate_selection_fee or zero) + lien
    return sum((getattr(profile, name) or zero for name in PLATE_INCOME_FIELDS), zero) + lien


def customer_balance(order):
    # 優先採用已保存的應收，包含有原因與稽核的人工調整。
    payment = order.payment_records.filter(system_key="balance").first() if order.pk else None
    return payment.expected_amount if payment is not None else default_customer_balance(order)
