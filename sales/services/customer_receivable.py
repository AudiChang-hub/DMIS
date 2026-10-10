"""客戶尾款的共同讀取口徑；不修改收款紀錄或歷史訂單。"""
from decimal import Decimal


def default_customer_balance(order):
    zero = Decimal("0")
    if order.payment_type == "installment":
        if order.cash_receivable_v2:
            # 分期公司只分車款（開辦費由撥款處理）；牌險、其他費用（例如選號）、舊車稅與配件由客人付（使用者 2026-10-10）。
            customer_part = (
                (order.plate_insurance_fee or zero) + order.other_fee_total
                + (order.old_vehicle_tax or zero) + order.accessory_total
            )
            return max(customer_part - (order.deposit_amount or zero), zero)
        return max((order.actual_balance or zero) - (order.installment_amount or zero), zero)
    return order.actual_balance or zero


def customer_balance(order):
    # 優先採用已保存的應收，包含有原因與稽核的人工調整。
    payment = order.payment_records.filter(system_key="balance").first() if order.pk else None
    return payment.expected_amount if payment is not None else default_customer_balance(order)
