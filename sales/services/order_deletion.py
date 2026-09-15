"""刪除申請、admin 審核與可稽核的關聯作廢。"""
import json
import hashlib
from django.core import signing
from django.core.serializers.json import DjangoJSONEncoder
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from sales.access.services import AccessPolicy, is_root
from sales.models import (OrderEvent, SalesOrder, DealerVolumeBonusAllocation,
    DealerVolumeBonusSettlement, DealerVolumeBonusRule, DealerVolumeBonusAdjustment,
    VehicleInventory, VehicleInventoryHistory)


def impact_fingerprint(order):
    data = {"order": list(SalesOrder.all_objects.filter(pk=order.pk).values()),
            "payments": list(order.payment_records.order_by("pk").values()),
            "operations": list(SalesOrder.all_objects.filter(pk=order.pk).values("operations__updated_at")),
            "allocations": list(DealerVolumeBonusAllocation.all_objects.filter(order=order).order_by("pk").values()),
            "settlements": list(DealerVolumeBonusSettlement.objects.filter(allocations__order=order).order_by("pk").values()),
            "vehicle": list(VehicleInventory.objects.filter(pk=order.allocated_vehicle_id).values())}
    return hashlib.sha256(json.dumps(data, cls=DjangoJSONEncoder, sort_keys=True).encode()).hexdigest()


def confirmation_token(order, user):
    return signing.dumps({"order": order.pk, "actor": user.pk, "fingerprint": impact_fingerprint(order)}, salt="order-delete-impact-v1")


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
def review_deletion(*, user, order_id, action, reason, expected_updated_at):
    require_access(user)
    try:
        order = SalesOrder.objects.select_for_update().get(pk=order_id)
    except SalesOrder.DoesNotExist as exc:
        raise ValidationError("訂單已被處理，請重新整理。") from exc
    if expected_updated_at != order.updated_at.isoformat():
        raise ValidationError("訂單已更新，請重新載入後確認。")
    reason = (reason or "").strip()
    if action == "request":
        if order.deletion_requested_at:
            raise ValidationError("此訂單已在刪除確認中，請勿重複申請。")
        if not reason or len(reason) > 500:
            raise ValidationError("請說明刪除原因，最多 500 字。")
        changes = dict(deletion_requested_at=timezone.now(), deletion_requested_by=user,
                       deletion_request_reason=reason)
        label = "申請刪除，等待 admin 確認"
    elif action in {"cancel", "reject"}:
        if not order.deletion_requested_at:
            raise ValidationError("此申請已被處理，請重新整理。")
        if action == "cancel" and order.deletion_requested_by_id != user.pk:
            raise PermissionDenied("只有原申請人可以取消刪除申請。")
        if action == "reject" and not is_root(user):
            raise PermissionDenied("只有 admin 可以駁回刪除申請。")
        if action == "reject" and (not reason or len(reason) > 500):
            raise ValidationError("請填寫駁回原因，最多 500 字。")
        changes = dict(deletion_requested_at=None, deletion_requested_by=None, deletion_request_reason="")
        label = "取消刪除申請" if action == "cancel" else "admin 駁回刪除申請"
        reason = reason or order.deletion_request_reason
    else:
        raise ValidationError("未知的審核操作。")
    SalesOrder.objects.filter(pk=order.pk).update(**changes, updated_at=timezone.now(), revision=order.revision + 1)
    OrderEvent.objects.create(order=order, actor_name=user.get_username(), event_type=f"deletion_{action}", description=f"{label}：{reason}")
    return order


def _locked_order(order_id):
    # 結算更正採「結算 → 訂單」鎖順序；先鎖規則亦避免新結算混入。
    settlement_ids = list(DealerVolumeBonusAllocation.all_objects.filter(order_id=order_id).values_list("settlement_id", flat=True))
    rule_ids = DealerVolumeBonusSettlement.objects.filter(pk__in=settlement_ids).values_list("rule_id", flat=True)
    list(DealerVolumeBonusRule.objects.select_for_update().filter(pk__in=rule_ids).order_by("pk"))
    settlements = list(DealerVolumeBonusSettlement.objects.select_for_update().filter(pk__in=settlement_ids).order_by("pk"))
    order = SalesOrder.all_objects.select_for_update().get(pk=order_id)
    current_ids = set(DealerVolumeBonusAllocation.all_objects.filter(order_id=order_id).values_list("settlement_id", flat=True))
    if current_ids != set(settlement_ids):
        raise ValidationError("結算關聯已改變，請重新檢查刪除影響。")
    return order, settlements


def _sync_settlements(settlements, user, reason):
    for settlement in settlements:
        amounts = list(settlement.allocations.values_list("amount", flat=True))
        tier = settlement.rule.tiers.filter(minimum_quantity__lte=len(amounts)).order_by("-minimum_quantity").first()
        previous = settlement.actual_amount
        settlement.qualified_quantity = len(amounts)
        settlement.bonus_per_vehicle = tier.bonus_per_vehicle if tier else Decimal("0")
        settlement.expected_amount = settlement.bonus_per_vehicle * len(amounts)
        # 刪除只扣除原單分配，不把差額轉嫁給其他訂單或改寫其歷史淨利。
        settlement.actual_amount = sum(amounts, Decimal("0"))
        settlement.adjustment_reason = reason
        settlement.save(update_fields=["qualified_quantity", "bonus_per_vehicle", "expected_amount", "actual_amount", "adjustment_reason", "updated_at"])
        DealerVolumeBonusAdjustment.objects.create(settlement=settlement, previous_amount=previous,
            revised_amount=settlement.actual_amount, reason=reason, adjusted_by=user.get_username())


def _change_effects(order, settlements, user, restore, reason, now):
    effects = order.deletion_effects if restore else {"allocations": list(order.dealer_volume_bonus_allocations.values_list("pk", flat=True))}
    vehicle_id = effects.get("vehicle", {}).get("id") if restore else order.allocated_vehicle_id
    if vehicle_id:
        vehicle = VehicleInventory.objects.select_for_update().get(pk=vehicle_id)
        before = vehicle.status
        if restore:
            saved = effects["vehicle"]
            if (vehicle.status != saved["after"] or vehicle.updated_at.isoformat() != saved["updated_at"]
                    or SalesOrder.all_objects.filter(allocated_vehicle_id=vehicle.pk).exclude(pk=order.pk).exists()):
                raise ValidationError("庫存車已異動或另行配車，不可直接還原；未覆蓋新交易。")
            after = saved["before"]
        else:
            physical_evidence = bool(order.delivered_at or order.registration_date or order.registration_completed_at or order.final_plate_number
                or vehicle.status in {VehicleInventory.Status.DELIVERED, VehicleInventory.Status.SOLD})
            after = (VehicleInventory.Status.INACTIVE if physical_evidence else
                     VehicleInventory.Status.AVAILABLE if before in {VehicleInventory.Status.RESERVED, VehicleInventory.Status.DELIVERY_PENDING} else before)
            effects["vehicle"] = {"id": vehicle.pk, "before": before, "after": after, "updated_at": now.isoformat()}
        VehicleInventory.objects.filter(pk=vehicle.pk).update(status=after, updated_at=now)
        VehicleInventoryHistory.objects.create(vehicle=vehicle, event_type=VehicleInventoryHistory.EventType.UPDATED,
            actor_name=user.get_username(), reason=f"{'還原' if restore else '刪除'}訂單 {order.number}：{reason}",
            changes={"status": {"before": before, "after": after}, "order": order.number}, status_snapshot=after,
            location_store_snapshot=vehicle.location_store, location_label_snapshot=vehicle.actual_location_label,
            condition_note_snapshot=vehicle.condition_note, condition_resolution_snapshot=vehicle.condition_resolution)
    DealerVolumeBonusAllocation.all_objects.filter(pk__in=effects.get("allocations", [])).update(voided_at=None if restore else now)
    _sync_settlements(settlements, user, f"{'還原' if restore else '刪除'}訂單 {order.number}：{reason}")
    return effects, vehicle_id if restore else None


@transaction.atomic
def change_deletion(*, user, order_id, restore, reason, expected_updated_at, editing_session="", force=False, confirmation=""):
    require_access(user)
    order, settlements = _locked_order(order_id)
    if force and not is_root(user):
        raise PermissionDenied("只有 admin 可以強制刪除。")
    if force:
        if order.allocated_vehicle_id:
            VehicleInventory.objects.select_for_update().get(pk=order.allocated_vehicle_id)
        list(order.payment_records.select_for_update().order_by("pk"))
        try:
            signed = signing.loads(confirmation, salt="order-delete-impact-v1", max_age=3600)
        except signing.BadSignature as exc:
            raise ValidationError("刪除影響確認已失效，請重新載入後確認。") from exc
        if signed != {"order": order.pk, "actor": user.pk, "fingerprint": impact_fingerprint(order)}:
            raise ValidationError("訂單、收款或關聯已變更，請重新檢查刪除影響。")
    if not restore and not is_root(user):
        raise PermissionDenied("請提出刪除申請，由 admin 確認後執行。")
    if restore and order.deletion_effects and not is_root(user):
        raise PermissionDenied("含關聯異動的訂單只能由 admin 還原。")
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
        if blockers and not force:
            raise ValidationError(blockers)
    effects = order.deletion_effects
    allocated_vehicle_id = order.allocated_vehicle_id
    if force or (restore and effects):
        effects, allocated_vehicle_id = _change_effects(order, settlements, user, restore, reason, now)
    # 白名單更新不觸發儲存整單、財務重算或歷史快照覆寫。
    SalesOrder.all_objects.filter(pk=order.pk).update(
        deleted_at=None if restore else now,
        deleted_by="" if restore else user.get_username(),
        deletion_reason="" if restore else reason,
        revision=order.revision + 1, updated_at=now,
        editing_session="", editing_at=None, editing_by="",
        allocated_vehicle_id=allocated_vehicle_id,
        deletion_effects={} if restore else effects,
        deletion_requested_at=None, deletion_requested_by=None, deletion_request_reason="",
    )
    OrderEvent.objects.create(order=order, event_type="restored" if restore else "soft_deleted",
        actor_name=user.get_username(), description=f"{'還原訂單' if restore else '刪除訂單（可還原）'}：{reason}" +
            (f"\n申請原因：{order.deletion_request_reason}" if order.deletion_requested_at else "") +
            (f"\n影響快照：{json.dumps(effects, ensure_ascii=False)}" if effects else ""))
    return order
