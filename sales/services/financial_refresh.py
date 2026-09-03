from django.db import transaction


def lock_bonus_periods(order):
    """整單儲存與結算互斥；NOWAIT 避免已持訂單鎖時反向等待規則鎖。"""
    from django.core.exceptions import ValidationError
    from django.db import DatabaseError
    from sales.models import DealerVolumeBonusRule

    if not order.registration_completed_at or not order.registration_date or not order.vehicle_model_id:
        return
    try:
        with transaction.atomic():
            list(DealerVolumeBonusRule.objects.select_for_update(nowait=True).filter(
                dealer_id=order.commission_recipient_id or order.source_id,
                brand__iexact=order.vehicle_model.brand,
                starts_on__lte=order.registration_date, ends_on__gte=order.registration_date,
            ).order_by("pk").values_list("pk", flat=True))
    except DatabaseError as exc:
        cause = exc.__cause__
        if getattr(cause, "sqlstate", None) == "55P03" or getattr(cause, "pgcode", None) == "55P03":
            raise ValidationError("台數獎金正在結算，請稍後重新載入再儲存。") from exc
        raise


@transaction.atomic
def refresh_unlocked_financials(order_id):
    """只有尚未領牌且未鎖定的費率隨輸入重算；歷史訂單不重套主檔。"""
    from sales.models import SalesOrder
    from .dealer_commission import apply_order_dealer_commission
    from .incentive_rule import apply_order_incentive_rule
    from .settlement_cost import apply_order_settlement_cost

    order = SalesOrder.objects.select_for_update().get(pk=order_id)
    if order.registration_completed_at or order.status == SalesOrder.Status.CANCELLED:
        return
    apply_order_settlement_cost(order)
    apply_order_incentive_rule(order)
    apply_order_dealer_commission(order)
