from django.db.models import Q
from django.utils import timezone

from sales.models import VehiclePriceVersion


PRICE_FIELDS = (
    "suggested_retail_price",
    "cash_price_including_registration",
    "cash_price_excluding_registration",
    "cash_purchase_bonus",
)


def resolve_vehicle_price_version(vehicle_model_id, order_date):
    """依訂單日取得有效售價版本；不從欄位間推導價格。"""
    if not vehicle_model_id or not order_date:
        return None
    return (
        VehiclePriceVersion.objects.filter(
            vehicle_model_id=vehicle_model_id,
            active=True,
            effective_from__lte=order_date,
        )
        .filter(Q(effective_to__isnull=True) | Q(effective_to__gte=order_date))
        .order_by("-effective_from", "-id")
        .first()
    )


def apply_order_price_snapshot(order, *, force=False):
    """保存訂單日適用版本，但不覆蓋業務實際輸入的成交車價。"""
    if order.price_snapshot and not force:
        return order
    version = resolve_vehicle_price_version(order.vehicle_model_id, order.order_date)
    if not version:
        order.price_version = None
        order.price_snapshot = {}
        order.price_snapshot_locked_at = None
    else:
        order.price_version = version
        order.price_snapshot = {
            "version_id": version.pk,
            "vehicle_model_id": version.vehicle_model_id,
            "announced_on": version.announced_on.isoformat(),
            "effective_from": version.effective_from.isoformat(),
            "effective_to": (
                version.effective_to.isoformat() if version.effective_to else ""
            ),
            "source_note": version.source_note,
            **{
                field: str(getattr(version, field))
                if getattr(version, field) is not None
                else ""
                for field in PRICE_FIELDS
            },
            "entered_vehicle_price": str(order.vehicle_price or 0),
        }
        order.price_snapshot_locked_at = timezone.now()
    if order.pk:
        # 僅落地快照欄位；不可因歷史訂單其他欄位的現行驗證規則，
        # 阻擋或改動這次獨立的快照保存。
        now = timezone.now()
        type(order).objects.filter(pk=order.pk).update(
            price_version=order.price_version,
            price_snapshot=order.price_snapshot,
            price_snapshot_locked_at=order.price_snapshot_locked_at,
            updated_at=now,
        )
        order.updated_at = now
    return order
