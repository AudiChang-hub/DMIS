"""客戶尾款的共同讀取口徑；不修改收款紀錄或歷史訂單。"""
from decimal import Decimal


def installment_customer_part(order):
    """分期單客人自付的部分（扣訂金前），即「分期外應收」。"""
    zero = Decimal("0")
    # 分期公司只分車款；牌險、選號、其他費用、舊車稅與配件由客人付（使用者 2026-10-10）。
    # 付款方式可多筆（使用者 2026-10-16）：分期以外的現金／刷卡／匯款車款也由客人付。
    # 已核准折扣與舊車估價：分期撥款不跟著折扣，從客人自付的部分扣（使用者 2026-10-17）。
    # 分期開辦費不在分期金額內，也由客人付（舊版公式「應收－分期金額」本來就含開辦費；收支的開辦費收入＝支出）：
    # 只有車價可以分期，分期外應收＝總價－車價分期金額（使用者 2026-10-20）。
    return (
        order.customer_vehicle_split_amount
        + plate_insurance_charged(order) + order.other_fee_total
        + (order.old_vehicle_tax or zero) + order.accessory_total
        + (order.effective_installment_fee or zero)
        - (order.approved_discount_amount or zero) - (order.old_vehicle_valuation or zero)
    )


def default_customer_balance(order):
    zero = Decimal("0")
    if order.payment_type == "installment":
        if order.cash_receivable_v2:
            return max(installment_customer_part(order) - (order.deposit_amount or zero), zero)
        return max((order.actual_balance or zero) - (order.installment_amount or zero), zero)
    return order.actual_balance or zero


PLATE_INCOME_FIELDS = (
    "registration_tax_income", "compulsory_insurance_income", "plate_selection_income", "agency_fee_income",
)


def plate_insurance_charged(order):
    """向客人收的牌險＋選號（含舊有動保設定費）。

    預設就是訂單牌險＋選號；在收支頁人工調整過「領牌相關」收入（例如分期吸收規費與強制險、只收選號）時，
    改以領牌稅金＋強制險＋選號＋代辦費收入合計，應收跟著改（使用者 2026-10-14；
    2026-10-15 起牌險溢收記在牌險手續費收入，欄位 agency_fee_income）。
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


def customer_receivable_total(order):
    """扣訂金前的客人應收：現金單的「應收」、分期單的「分期外應收」。

    尾款（customer_balance）＝這個金額－訂金。尾款以保存的應收為準，這裡跟著它加回訂金，兩個數字才對得起來；
    分期單訂金多於自付部分時尾款停在 0，分期外應收改回自付部分，不把多收的訂金算成應收（使用者 2026-10-20）。
    """
    zero = Decimal("0")
    deposit = order.deposit_amount or zero
    balance = customer_balance(order)
    total = balance + deposit
    if balance <= zero and order.payment_type == "installment" and order.cash_receivable_v2:
        total = min(total, max(installment_customer_part(order), zero))
    return total
