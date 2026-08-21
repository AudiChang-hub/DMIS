from decimal import Decimal, InvalidOperation

from django.db.models import Q
from django.utils import timezone

from sales.models import VehiclePriceVersion


PRICE_FIELDS = (
    "suggested_price",
    "cash_price",
)


def resolve_vehicle_price_version(
    vehicle_model_id,
    order_date,
    *,
    exclude_version_id=None,
):
    """依訂單日取得有效售價版本；不從欄位間推導價格。"""
    if not vehicle_model_id or not order_date:
        return None
    queryset = (
        VehiclePriceVersion.objects.filter(
            vehicle_model_id=vehicle_model_id,
            active=True,
            effective_from__lte=order_date,
        )
        .filter(Q(effective_to__isnull=True) | Q(effective_to__gte=order_date))
    )
    if exclude_version_id:
        queryset = queryset.exclude(pk=exclude_version_id)
    return queryset.order_by("-effective_from", "-id").first()


def recommended_vehicle_price(version, payment_type):
    """依付款方式取得建議帶入的成交車價，不自行推導牌險或折扣。"""
    if not version:
        return None, ""
    if payment_type == "installment":
        candidates = (
            ("suggested_price", "建議售價"),
            ("cash_price", "現金價"),
        )
    else:
        candidates = (
            ("cash_price", "現金價"),
            ("suggested_price", "建議售價"),
        )
    for field_name, label in candidates:
        value = getattr(version, field_name)
        if value is not None:
            return value, label
    return None, ""


def recommended_price_from_snapshot(snapshot, payment_type):
    """從訂單已鎖定的售價快照取得建議價，供歷史訂單編輯與顯示。"""
    if not snapshot:
        return None, ""
    if payment_type == "installment":
        candidates = (
            ("suggested_price", "建議售價"),
            ("cash_price", "現金價"),
        )
    else:
        candidates = (
            ("cash_price", "現金價"),
            ("suggested_price", "建議售價"),
        )
    for field_name, label in candidates:
        raw_value = snapshot.get(field_name)
        if raw_value not in (None, ""):
            try:
                return Decimal(str(raw_value)), label
            except (InvalidOperation, TypeError, ValueError):
                continue
    return None, ""


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
        recommended_price, recommended_price_label = recommended_vehicle_price(
            version,
            order.payment_type,
        )
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
            "suggested_price_includes_registration": (
                version.suggested_price_includes_registration
            ),
            **{
                field: str(getattr(version, field))
                if getattr(version, field) is not None
                else ""
                for field in PRICE_FIELDS
            },
            "recommended_price": (
                str(recommended_price) if recommended_price is not None else ""
            ),
            "recommended_price_label": recommended_price_label,
            "entered_vehicle_price": str(order.vehicle_price or 0),
            "adjustment_reason": order.vehicle_price_adjustment_reason,
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
