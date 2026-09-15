"""訂單回收區：不實體刪除、不變更帳務與車輛狀態。"""
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from sales.access.services import AccessPolicy
from sales.models import OrderEvent, SalesOrder


def require_access(user, action="operate"):
    if not AccessPolicy(user).screen("order_delete", action):
        raise PermissionDenied("沒有刪除與還原訂單權限，請洽 admin 授權。")


def deletion_blockers(order):
    blockers = []
    if order.allocated_vehicle_id:
        blockers.append("仍綁定庫存車輛，請先完成取消／解除配車流程。")
    if order.registration_completed_at or order.registration_date or order.final_plate_number:
        blockers.append("已有領牌資料，請先確認並更正領牌紀錄；刪除不會撤銷領牌。")
    if order.delivered_at or order.status in {SalesOrder.Status.COMPLETED, SalesOrder.Status.DELIVERED_DOCS_PENDING}:
        blockers.append("已交付或完成的交易不可直接刪除，須先處理交付與帳務更正。")
    if order.status == SalesOrder.Status.CANCEL_REFUND_PENDING:
        blockers.append("仍有退款待辦，請先完成退款。")
    received = sum((p.received_amount or Decimal("0") for p in order.payment_records.all()), Decimal("0"))
    money = max(received, order.deposit_amount or Decimal("0"))
    if money and not (order.status == SalesOrder.Status.CANCELLED and order.refund_completed_on and order.refund_amount >= money):
        blockers.append("有實收或訂金紀錄，請先完成取消及全額退款，不可用刪除代替沖銷。")
    if order.dealer_volume_bonus_allocations.exists():
        blockers.append("已有台數獎金結算，請先處理結算更正。")
    return blockers


@transaction.atomic
def change_deletion(*, user, order_id, restore, reason, expected_updated_at, editing_session=""):
    require_access(user)
    order = SalesOrder.all_objects.select_for_update().get(pk=order_id)
    if bool(order.deleted_at) != restore:
        raise ValidationError("此訂單已被刪除或還原，請重新整理，不需重複操作。")
    if expected_updated_at != order.updated_at.isoformat():
        raise ValidationError("訂單已被更新，請重新載入並確認最新內容。")
    reason = (reason or "").strip()
    if not reason or len(reason) > 500:
        raise ValidationError("請填寫原因，最多 500 字。")
    now = timezone.now()
    if order.editing_session and order.editing_session != editing_session and order.editing_at and order.editing_at >= now - timedelta(seconds=90):
        raise ValidationError("目前有其他人正在編輯此訂單，請稍後再操作。")
    if not restore:
        blockers = deletion_blockers(order)
        if blockers:
            raise ValidationError(blockers)
    # 白名單更新不觸發儲存整單、財務重算或歷史快照覆寫。
    SalesOrder.all_objects.filter(pk=order.pk).update(
        deleted_at=None if restore else now,
        deleted_by="" if restore else user.get_username(),
        deletion_reason="" if restore else reason,
        revision=order.revision + 1, updated_at=now,
        editing_session="", editing_at=None, editing_by="",
    )
    OrderEvent.objects.create(order=order, event_type="restored" if restore else "soft_deleted",
        actor_name=user.get_username(), description=f"{'還原訂單' if restore else '刪除訂單（可還原）'}：{reason}")
    return order
