"""已取消訂單不留系統未收應收列（使用者 2026-11-06 選 B）。

訂單取消完成（狀態變成「已取消」：沒有已確認實收直接取消，或待退款結算完成）時，同一交易內刪除
系統自動產生、還沒收到錢的應收列：訂金、尾款、分期撥款、平台撥款等 `system_key` 有值的收款列，
且未確認、實收 0、沒有收款證明、沒有沖銷紀錄。已確認的實收（含已入帳的撥款列，T-96）、退款／沖銷紀錄、
人工新增的收款列一律不動。刪除前每列完整欄位寫進 OrderChange，供 `clear_cancelled_receivables --rollback` 還原；
已取消的訂單之後同步也不再重建這些列（`operations_sync.sync_order_operations`）。
"""
import datetime
from decimal import Decimal

from django.db import transaction

CLEAR_REASON = "取消完成：清除系統未收應收列"
ROLLBACK_REASON = "還原取消單的系統未收應收列"


def clearable_receivables(order):
    from sales.models import PaymentRecord

    rows = (
        PaymentRecord.objects.filter(
            order=order,
            entry_type=PaymentRecord.EntryType.RECEIPT,
            confirmed=False,
            confirmed_at__isnull=True,
            received_amount=0,
            proof="",
        )
        .exclude(system_key="")
        .order_by("pk")
    )
    return [row for row in rows if not row.reversal_entries.exists()]


def _row_values(row):
    values = {}
    for field in row._meta.concrete_fields:
        value = field.value_from_object(row)
        if isinstance(value, Decimal):
            value = str(value)
        elif isinstance(value, (datetime.date, datetime.datetime)):
            value = value.isoformat()
        elif hasattr(value, "name"):  # FieldFile
            value = value.name or ""
        values[field.attname] = value
    return values


def _row_text(row):
    return (
        f"{row.item_name or '收款'}；{row.receipt_kind_label}；應收 ${row.expected_amount or 0:,.0f}；"
        f"實收 ${row.received_amount or 0:,.0f}；未確認（收款列 #{row.pk}）"
    )


@transaction.atomic
def clear_cancelled_receivables(order, *, actor_name, reason=CLEAR_REASON):
    """刪除已取消訂單的系統未收應收列；回傳刪掉的收款列編號。不是「已取消」狀態時不做任何事。"""
    from sales.models import OrderChange, OrderEvent, SalesOrder
    from sales.services.operations_sync import refresh_payment_confirmation

    locked = SalesOrder.objects.select_for_update().get(pk=order.pk)
    if locked.status != SalesOrder.Status.CANCELLED:
        return []
    rows = clearable_receivables(locked)
    if not rows:
        return []
    changes = {
        f"刪除應收：{row.item_name or '收款'}（#{row.pk}）": {
            "before": _row_text(row), "after": "已清除", "row": _row_values(row),
        }
        for row in rows
    }
    removed = [row.pk for row in rows]
    for row in rows:
        row.delete()
    OrderChange.objects.create(order=locked, reason=reason, changes=changes, actor_name=actor_name)
    OrderEvent.objects.create(
        order=locked, event_type="cancelled_receivables_cleared", actor_name=actor_name,
        description=f"取消完成，清除 {len(rows)} 筆系統未收應收列（不影響已確認的實收與退款）",
    )
    refresh_payment_confirmation(locked.pk)
    return removed


@transaction.atomic
def restore_cleared_receivables(change, *, actor_name):
    """依清除時的 OrderChange 重建收款列（同編號）；已存在的編號略過。回傳重建的收款列編號。"""
    from sales.models import OrderChange, OrderEvent, PaymentRecord
    from sales.services.operations_sync import refresh_payment_confirmation

    fields = {field.attname: field for field in PaymentRecord._meta.concrete_fields}
    restored = []
    for entry in change.changes.values():
        values = entry.get("row") if isinstance(entry, dict) else None
        if not values or PaymentRecord.objects.filter(pk=values.get("id")).exists():
            continue
        record = PaymentRecord(**{
            name: fields[name].to_python(value) if value not in (None, "") or name == "proof" else value
            for name, value in values.items() if name in fields
        })
        record.save(force_insert=True)
        # created_at 是 auto_now_add，存檔時會被蓋成現在；改回清除前的時間。
        PaymentRecord.objects.filter(pk=record.pk).update(created_at=fields["created_at"].to_python(values["created_at"]))
        restored.append(record.pk)
    if restored:
        OrderChange.objects.create(
            order_id=change.order_id, actor_name=actor_name, reason=ROLLBACK_REASON,
            changes={f"還原應收（#{pk}）": {"before": "已清除", "after": f"依處理紀錄 #{change.pk} 重建"} for pk in restored},
        )
        OrderEvent.objects.create(
            order_id=change.order_id, event_type="cancelled_receivables_restored", actor_name=actor_name,
            description=f"還原 {len(restored)} 筆取消時清除的系統應收列（處理紀錄 #{change.pk}）",
        )
        refresh_payment_confirmation(change.order_id)
    return restored
