"""訂單頁「訂金」步驟（使用者 2026-10-20 T-29 方案 A）。

訂金只有一個數字：訂單的訂金（`SalesOrder.deposit_amount`）就是訂金收款列的應收；
「已收妥」打開＝實收＝訂金、確認入帳，關掉＝取消已確認（2026-10-17 規則，已沖銷不可取消）。
未收妥時修改金額、日期或方式，同步寫回訂單並重算尾款；收妥後金額、日期、方式鎖定，備註仍可改。
建單填了訂金就直接收妥（`confirm_intake_deposit`）。訂金這一步不做同日同額的重複收款防呆。
"""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.utils import timezone

ZERO = Decimal("0")


def method_label(order, method):
    return dict(order.PaymentMethod.choices).get(method, "")


def method_value(order, label):
    return next((value for value, text in order.PaymentMethod.choices if text == label), "")


def _confirm(payment, amount, actor_name):
    payment.received_amount = amount
    payment.confirmed = True
    payment.confirmed_by = actor_name
    payment.confirmed_at = timezone.now()


def confirm_intake_deposit(order, actor_name):
    """建單填了訂金：實收＝訂金、日期沒填用當天、確認人記建單者，直接入帳。"""
    from sales.models import PaymentRecord
    from sales.services.operations_sync import sync_order_operations

    if not order.deposit_amount or order.deposit_amount <= 0:
        return None
    sync_order_operations(order.pk)
    payment = PaymentRecord.objects.select_for_update().get(order=order, system_key="deposit")
    if payment.confirmed:
        return payment
    payment.received_on = order.deposit_date or timezone.localdate()
    payment.payment_method = method_label(order, order.deposit_method)
    _confirm(payment, order.deposit_amount, actor_name)
    payment.save()
    sync_order_operations(order.pk)
    return payment


def _sync_order_deposit(order, *, amount, day, method, actor_name):
    """未收妥時改訂金：寫回訂單、重算尾款與收款列，留下修改紀錄。"""
    from sales.models import OrderChange
    from sales.services.financial_refresh import refresh_unlocked_financials
    from sales.services.operations_sync import sync_order_operations

    before = {"deposit_amount": order.deposit_amount, "deposit_date": order.deposit_date,
              "deposit_method": order.deposit_method}
    after = {"deposit_amount": amount, "deposit_date": day if amount else None, "deposit_method": method}
    changes = {name: {"before": str(before[name] or ""), "after": str(after[name] or "")}
               for name in before if before[name] != after[name]}
    if not changes:
        return False
    balance_was_automatic = order.actual_balance == order.calculated_balance
    previous_actual = order.actual_balance
    for name, value in after.items():
        setattr(order, name, value)
    order.revision += 1
    order.calculated_balance = order.calculate_balance()
    order.actual_balance = order.calculated_balance if balance_was_automatic else previous_actual
    order.save(update_fields=[*after, "calculated_balance", "actual_balance", "revision", "updated_at"])
    OrderChange.objects.create(order=order, actor_name=actor_name, reason="訂金步驟", changes=changes)
    refresh_unlocked_financials(order.pk)
    sync_order_operations(order.pk, update_receivables=True)
    return True


def save_deposit_step(order, payment, data, actor_name):
    """依表單內容更新訂金；回傳處理紀錄說明，沒有變更回傳空字串。"""
    from sales.services.operations_sync import sync_order_operations

    note = data.get("note") or ""
    if payment.confirmed:
        if data.get("confirmed"):
            if payment.note == note:
                return ""
            payment.note = note
            payment.save(update_fields=["note", "updated_at"])
            return "修改訂金收款備註"
        if payment.reversal_entries.exists():
            raise ValidationError("這筆訂金已沖銷，不能取消已收妥。")
        amount = payment.received_amount
        # 帳本只允許「只改勾選」的取消（2026-10-17）；取消後再把實收歸零，回到待收妥。
        payment.confirmed = False
        payment.confirmed_by = ""
        payment.confirmed_at = None
        payment.save(update_fields=["confirmed", "confirmed_by", "confirmed_at", "updated_at"])
        payment.received_amount = ZERO
        payment.note = note
        payment.save(update_fields=["received_amount", "note", "updated_at"])
        sync_order_operations(order.pk)
        return f"取消訂金已收妥（${amount:,.0f}），回到待收妥"

    amount = data.get("amount") or ZERO
    method = data.get("method") or ""
    day = data.get("received_on") or (timezone.localdate() if amount else None)
    order_changed = _sync_order_deposit(order, amount=amount, day=day, method=method, actor_name=actor_name)
    payment.refresh_from_db()
    if not payment.expected_amount_overridden:
        payment.expected_amount = amount
    payment.received_on = day
    payment.payment_method = method_label(order, method)
    payment.note = note
    payment.received_amount = ZERO
    confirming = bool(data.get("confirmed") and amount > 0)
    if confirming:
        _confirm(payment, amount, actor_name)
    payment.save()
    sync_order_operations(order.pk)
    if confirming:
        return f"訂金 ${amount:,.0f} 已收妥並入帳"
    if order_changed:
        return f"修改訂金為 ${amount:,.0f}（待收妥）"
    return "修改訂金收款資料（待收妥）"


def deposit_state(order):
    """給畫面即時更新用：收妥狀態、是否鎖定與步驟摘要。"""
    payment = next((p for p in order.payment_records.all() if p.system_key == "deposit"), None)
    confirmed = bool(payment and payment.confirmed)
    amount = (payment.received_amount if confirmed else order.deposit_amount) or ZERO
    return {
        "confirmed": confirmed,
        "locked": confirmed,
        "summary": deposit_summary(order, payment),
        "amount": str(amount),
    }


def deposit_summary(order, payment):
    if payment and payment.confirmed:
        return f"已收妥 {payment.received_amount:,.0f}"
    if not order.deposit_amount or order.deposit_amount <= 0:
        return "沒有訂金"
    return f"待收妥 {order.deposit_amount:,.0f}"
