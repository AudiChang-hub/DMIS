"""領牌後棄單：訂單例外結案，車輛以已領牌車釋回庫存重新定價。"""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone


def exception_close_blockers(order, ledger=None):
    from sales.models import SalesOrder
    from .payment_ledger import ledger_totals

    if order.status in {SalesOrder.Status.CANCELLED, SalesOrder.Status.CANCEL_REFUND_PENDING, SalesOrder.Status.EXCEPTION_CLOSED}:
        return ["此訂單已取消或已結案。"]
    blockers = []
    if not order.is_registration_complete:
        blockers.append("尚未完成領牌；未領牌的訂單請使用一般取消流程。")
    if order.is_delivered:
        blockers.append("車輛已交付，不能以棄單結案。")
    if not order.allocated_vehicle_id:
        blockers.append("訂單沒有配車，無法釋回車輛。")
    if order.dealer_volume_bonus_allocations.exists():
        blockers.append("已結算台數獎金，請先更正結算後再結案。")
    ledger = ledger or ledger_totals(order)
    if ledger["lender"]["net"] > 0:
        blockers.append("分期公司已撥款，不能退車。")
    if ledger["customer"]["unconfirmed"] or ledger["lender"]["unconfirmed"]:
        blockers.append("尚有已登記但未確認的實收金額，請先確認或清除。")
    return blockers


@transaction.atomic
def close_after_registration(order_id, *, actor_name, reason, forfeited_amount, forfeit_reason,
                             resale_price, completed_on, method="", reference="", proof=None):
    """應退＝客戶已確認淨實收－沒收；車輛不回新車庫存，改為已領牌車待再售。"""
    from sales.models import OrderChange, OrderEvent, SalesOrder, VehicleInventory, VehicleInventoryHistory
    from .payment_ledger import create_refund_entry, ledger_totals

    order = SalesOrder.objects.select_for_update().get(pk=order_id)
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError("請填寫結案原因。")
    ledger = ledger_totals(order)
    blockers = exception_close_blockers(order, ledger)
    if blockers:
        raise ValidationError(blockers[0])
    received = ledger["customer"]["net"]
    forfeited = Decimal(forfeited_amount or 0)
    if forfeited < 0 or forfeited > received:
        raise ValidationError(f"沒收金額須介於 0 至已收 {received:,.0f} 元之間。")
    forfeit_reason = (forfeit_reason or "").strip()
    if forfeited and not forfeit_reason:
        raise ValidationError("有沒收金額時，請填寫沒收原因。")
    if resale_price is None or Decimal(resale_price) <= 0:
        raise ValidationError("請填寫領牌車再售價。")
    order.ensure_transition(SalesOrder.Status.EXCEPTION_CLOSED)
    refund = received - forfeited
    method_label = dict(SalesOrder.PaymentMethod.choices).get(method, method or "")
    if refund > 0 and not method:
        raise ValidationError("有應退金額時，請選擇退款方式。")

    vehicle = VehicleInventory.objects.select_for_update().get(pk=order.allocated_vehicle_id)
    before_status = vehicle.status
    vehicle.status = VehicleInventory.Status.AVAILABLE
    vehicle.registered_plate_number = order.final_plate_number
    vehicle.registered_on = order.registration_date
    vehicle.resale_price = Decimal(resale_price)
    vehicle.save(update_fields=["status", "registered_plate_number", "registered_on", "resale_price", "updated_at"])
    VehicleInventoryHistory.objects.create(
        vehicle=vehicle, event_type=VehicleInventoryHistory.EventType.UPDATED, actor_name=actor_name,
        reason=f"訂單 {order.number} 領牌後棄單，釋回為已領牌車：{reason}",
        changes={
            "庫存狀態": {"before": before_status, "after": vehicle.status},
            "已領牌車牌": {"before": "", "after": vehicle.registered_plate_number},
            "領牌車再售價": {"before": "", "after": f"{vehicle.resale_price:,.0f}"},
        },
        status_snapshot=vehicle.status, location_store_snapshot=vehicle.location_store,
        location_label_snapshot=vehicle.actual_location_label,
        condition_note_snapshot=vehicle.condition_note, condition_resolution_snapshot=vehicle.condition_resolution,
    )

    if refund > 0:
        create_refund_entry(
            order, kind="customer", amount=refund, actor_name=actor_name,
            reason=f"領牌後棄單退款（已收 {received:,.0f}、沒收 {forfeited:,.0f}）",
            method_label=method_label, refunded_on=completed_on, reference=reference, item_name="棄單退款",
        )
    now = timezone.now()
    order.allocated_vehicle = None
    order.exception_vehicle = vehicle
    order.exception_reason = reason[:250]
    order.exception_closed_at = now
    order.exception_closed_by = actor_name
    order.refund_amount = refund
    order.forfeited_amount = forfeited
    order.forfeit_reason = forfeit_reason[:250]
    order.refund_completed_on = completed_on
    order.refund_method = method if refund > 0 else ""
    order.refund_reference = reference if refund > 0 else ""
    if proof is not None:
        order.refund_proof = proof
    order.status = SalesOrder.Status.EXCEPTION_CLOSED
    order.save(update_fields=[
        "allocated_vehicle", "exception_vehicle", "exception_reason", "exception_closed_at", "exception_closed_by",
        "refund_amount", "forfeited_amount", "forfeit_reason", "refund_completed_on", "refund_method",
        "refund_reference", "refund_proof", "status", "updated_at",
    ])
    summary = f"已收 {received:,.0f}、沒收 {forfeited:,.0f}、退款 {refund:,.0f}"
    OrderChange.objects.create(
        order=order, reason=reason, actor_name=actor_name,
        changes={"訂單狀態": {"before": "已領牌待交車", "after": "例外結案"}, "結算": {"before": "", "after": summary}},
    )
    OrderEvent.objects.create(
        order=order, event_type="exception_closed", actor_name=actor_name,
        description=(
            f"領牌後棄單例外結案：{reason}；{summary}；車輛 {vehicle.identifier}"
            f"（{vehicle.registered_plate_number}）以已領牌車釋回，再售價 {vehicle.resale_price:,.0f} 元"
        ),
    )
    from .notifications import notify
    notify("exception_closed", order, f"訂單 {order.number} 領牌後棄單已例外結案", f"{reason}；{summary}。")
    return order
