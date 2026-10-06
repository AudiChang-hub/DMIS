"""車行附加獎勵快照：建立訂單時保存當時適用的方案，之後修改主檔不影響既有訂單。

快照比照售價快照（`price_version.apply_order_price_snapshot`）：建立時保存，
訂單車型或來源在未完成前變更時重新保存；舊訂單沒有快照時退回依日期查詢主檔。
"""
from django.db.models import Q
from django.utils import timezone

from sales.models import DealerVehicleRewardPlan

SNAPSHOT_VERSION = 1


def resolve_dealer_reward_plans(vehicle_model_id, day):
    """依日期查詢目前主檔中有效的車行附加獎勵方案（含項目）。"""
    if not vehicle_model_id or not day:
        return DealerVehicleRewardPlan.objects.none()
    return (
        DealerVehicleRewardPlan.objects.filter(vehicle_model_id=vehicle_model_id, active=True, effective_from__lte=day)
        .filter(Q(effective_to__isnull=True) | Q(effective_to__gte=day))
        .prefetch_related("items")
        .order_by("pk")
    )


def _decimal_text(value):
    return "" if value is None else format(value.normalize(), "f")


def _plan_payload(plan):
    return {
        "plan_id": plan.pk,
        "effective_from": plan.effective_from.isoformat(),
        "effective_to": plan.effective_to.isoformat() if plan.effective_to else "",
        "note": plan.note,
        "items": [
            {
                "item_id": item.pk,
                "catalog_item_id": item.catalog_item_id,
                "reward_type": item.reward_type,
                "reward_type_label": item.get_reward_type_display(),
                "name": item.name,
                "quantity": _decimal_text(item.quantity),
                "unit": item.unit,
                "unit_cost_snapshot": _decimal_text(item.unit_cost_snapshot),
                "cost_effective_on_snapshot": (
                    item.cost_effective_on_snapshot.isoformat() if item.cost_effective_on_snapshot else ""
                ),
                "note": item.note,
                "label": item.display_label,
            }
            for item in plan.items.all()
        ],
    }


def build_dealer_reward_snapshot(order):
    day = order.order_date
    plans = resolve_dealer_reward_plans(order.vehicle_model_id, day)
    return {
        "version": SNAPSHOT_VERSION,
        "vehicle_model_id": order.vehicle_model_id,
        "source_type": order.source_type,
        "reference_date": day.isoformat() if day else "",
        "captured_at": timezone.now().isoformat(),
        "plans": [_plan_payload(plan) for plan in plans],
    }


def has_dealer_reward_snapshot(order):
    return isinstance(order.dealer_reward_snapshot, dict) and "plans" in order.dealer_reward_snapshot


def apply_order_dealer_reward_snapshot(order, *, force=False):
    """保存訂單日適用的車行附加獎勵；已有快照且未要求重新保存時不覆蓋。"""
    if has_dealer_reward_snapshot(order) and not force:
        return order
    order.dealer_reward_snapshot = build_dealer_reward_snapshot(order)
    order.dealer_reward_snapshot_locked_at = timezone.now()
    if order.pk:
        # 只落地快照欄位，不因其他欄位的現行驗證阻擋快照保存。
        now = timezone.now()
        type(order).objects.filter(pk=order.pk).update(
            dealer_reward_snapshot=order.dealer_reward_snapshot,
            dealer_reward_snapshot_locked_at=order.dealer_reward_snapshot_locked_at,
            updated_at=now,
        )
        order.updated_at = now
    return order


def order_dealer_reward_plans(order, day=None):
    """訂單的附加獎勵：有快照讀快照；舊訂單退回依日期（預設訂單日）查詢主檔。

    回傳與快照相同結構的方案清單，呼叫端不必分辨來源。
    """
    if has_dealer_reward_snapshot(order):
        return order.dealer_reward_snapshot["plans"]
    return [_plan_payload(plan) for plan in resolve_dealer_reward_plans(order.vehicle_model_id, day or order.order_date)]


def reward_plan_summary(plan):
    return "、".join(item["label"] for item in plan.get("items", []))
