"""歷史匯入單的交車狀態：Excel 有車牌＝已完成，沒有車牌＝待交車。

匯入時沒有車牌的列建立為「待交車」；之後補上車牌（admin 在訂單頁補登，或重新匯入時用 Excel 更新車牌）
即轉為「已完成」。歷史匯入單沒有庫存與配車，因此跳過一般交車流程的「需先配車」檢查；只限有匯入快照的訂單。
"""
from datetime import datetime, time

from django.db import transaction
from django.utils import timezone

from sales.models import OrderChange, OrderEvent, SalesOrder

EVENT_COMPLETED = "historical_delivery_completed"
EVENT_REOPENED = "historical_delivery_reopened"


def is_imported(order):
    return hasattr(order, "legacy_snapshot")


def can_complete(order):
    return is_imported(order) and order.status == SalesOrder.Status.DELIVERY_PENDING


def _noon(day):
    return timezone.make_aware(datetime.combine(day, time(hour=12)))


@transaction.atomic
def complete_imported_order(order_id, *, plate, delivered_on, actor, reason):
    """補登車牌並完成交車；沒有領牌日期時以交車日期補上。"""
    order = SalesOrder.objects.select_for_update(of=("self",)).get(pk=order_id)
    plate = (plate or "").strip().upper()
    reason = (reason or "").strip()
    if not is_imported(order):
        raise ValueError("只有 Excel 匯入的歷史訂單可以用這個方式完成交車。")
    if order.status != SalesOrder.Status.DELIVERY_PENDING:
        raise ValueError("這張訂單不是待交車狀態。")
    if not plate:
        raise ValueError("請填寫車牌號碼。")
    if not delivered_on:
        raise ValueError("請選擇交車日期。")
    if len(reason) < 2:
        raise ValueError("請填寫原因。")
    before = {
        "狀態": order.get_status_display(), "最終車牌號碼": order.final_plate_number,
        "實際領牌日期": str(order.registration_date or ""), "交車時間": "",
    }
    moment = _noon(delivered_on)
    registration_date = order.registration_date or delivered_on
    SalesOrder.objects.filter(pk=order.pk).update(
        status=SalesOrder.Status.COMPLETED, final_plate_number=plate,
        registration_date=registration_date,
        registration_completed_at=order.registration_completed_at or _noon(registration_date),
        registration_completed_by=order.registration_completed_by or actor,
        delivered_at=moment, delivered_by=actor, revision=order.revision + 1,
    )
    order.refresh_from_db()
    after = {
        "狀態": order.get_status_display(), "最終車牌號碼": order.final_plate_number,
        "實際領牌日期": str(order.registration_date or ""), "交車時間": f"{delivered_on:%Y/%m/%d}",
    }
    changes = {label: {"before": before[label], "after": after[label]} for label in before if before[label] != after[label]}
    OrderChange.objects.create(order=order, reason=f"歷史匯入單補登車牌並完成交車；{reason}", changes=changes, actor_name=actor)
    OrderEvent.objects.create(order=order, event_type=EVENT_COMPLETED, actor_name=actor,
                              description=f"補登車牌 {plate}，{delivered_on:%Y/%m/%d} 完成交車（歷史匯入單，無配車）；{reason}")
    from sales.services.order_search import rebuild_order_search_index
    rebuild_order_search_index(order.pk)
    return order


@transaction.atomic
def reopen_imported_order(order_id, *, actor, reason):
    """已完成但其實沒有車牌的歷史匯入單改回待交車（保留預計領牌日期與收支）。"""
    order = SalesOrder.objects.select_for_update(of=("self",)).get(pk=order_id)
    if not is_imported(order):
        raise ValueError("只有 Excel 匯入的歷史訂單可以改回待交車。")
    if order.status != SalesOrder.Status.COMPLETED:
        raise ValueError("這張訂單不是已完成狀態。")
    if order.final_plate_number:
        raise ValueError("已有車牌的歷史匯入單視為已完成，不能改回待交車。")
    before = {"狀態": order.get_status_display(), "交車人員": order.delivered_by,
              "交車時間": f"{timezone.localtime(order.delivered_at):%Y/%m/%d %H:%M}" if order.delivered_at else ""}
    SalesOrder.objects.filter(pk=order.pk).update(
        status=SalesOrder.Status.DELIVERY_PENDING, delivered_at=None, delivered_by="",
        registration_completed_at=None, registration_completed_by="", revision=order.revision + 1,
    )
    order.refresh_from_db()
    changes = {label: {"before": value, "after": ""} for label, value in before.items()}
    changes["狀態"]["after"] = order.get_status_display()
    OrderChange.objects.create(order=order, reason=f"歷史匯入單沒有車牌，改回待交車；{reason}", changes=changes, actor_name=actor)
    OrderEvent.objects.create(order=order, event_type=EVENT_REOPENED, actor_name=actor,
                              description=f"沒有車牌，改回待交車（預計領牌日期與收支保留）；{reason}")
    return order
