from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from sales.models import DealerVolumeBonusRule, DealerVolumeBonusSettlement, OrderChange, OrderEvent, SalesOrder, SalesSource


@transaction.atomic
def change_order_commission_recipient(
    *, order_id, recipient_id, reason, expected_revision, actor_name, editing_session,
    presence_timeout=timedelta(seconds=90),
):
    """已交付也能調整歸屬；不可重存整單或重算任何歷史金額。"""
    # 與結算維持相同順序：先規則、再訂單，避免改歸屬同時撞上結算。
    initial_order = SalesOrder.objects.select_related("vehicle_model").get(pk=order_id)
    target_id = recipient_id or initial_order.source_id
    locked_rule_ids = []
    if initial_order.registration_date:
        locked_rule_ids = list(DealerVolumeBonusRule.objects.select_for_update().filter(
            dealer_id=target_id, brand__iexact=initial_order.vehicle_model.brand,
            starts_on__lte=initial_order.registration_date, ends_on__gte=initial_order.registration_date,
        ).order_by("pk").values_list("pk", flat=True))
    order = SalesOrder.objects.select_for_update(of=("self",)).select_related(
        "source", "commission_recipient", "vehicle_model",
    ).get(pk=order_id)
    block_reason = order.commission_attribution_block_reason
    if block_reason:
        raise ValidationError(block_reason)
    if expected_revision != order.revision:
        raise ValidationError("此訂單已被更新，請重新載入後再調整歸屬。")
    if (order.registration_date != initial_order.registration_date
            or order.vehicle_model.brand != initial_order.vehicle_model.brand
            or order.source_id != initial_order.source_id):
        raise ValidationError("訂單的來源或領牌資料已更新，請重新載入後再調整歸屬。")
    now = timezone.now()
    if (order.editing_session and order.editing_session != editing_session
            and order.editing_at and order.editing_at >= now - presence_timeout):
        raise ValidationError("此訂單目前有其他人正在編輯，請稍後再調整歸屬。")
    reason = (reason or "").strip()
    if not reason or len(reason) > 500:
        raise ValidationError("請填寫調整原因，最多 500 字。")

    # 選回原車行即恢復預設；既有停用歸屬允許不變，不接受新指定。
    recipient = None
    if recipient_id and recipient_id != order.source_id:
        recipient = SalesSource.objects.filter(
            pk=recipient_id, source_type=SalesSource.SourceType.DEALER,
        ).first()
        if not recipient or (not recipient.active and recipient.pk != order.commission_recipient_id):
            raise ValidationError("請選擇啟用中的合作車行。")
    normalized_id = recipient.pk if recipient else None
    if normalized_id == order.commission_recipient_id:
        return False
    if DealerVolumeBonusSettlement.objects.filter(rule_id__in=locked_rule_ids).exists():
        raise ValidationError("指定車行在這張訂單的領牌期間已結算台數獎金，不能直接加入已結算清單。")

    before = str(order.effective_commission_recipient)
    after = str(recipient or order.source)
    # 有意使用白名單 update：save()/signals 會整理交付日期與重同步財務。
    # 上方已在列鎖內完成此專用操作驗證；下方稽核信號會更新搜尋索引。
    SalesOrder.objects.filter(pk=order.pk).update(
        commission_recipient_id=normalized_id, revision=order.revision + 1, updated_at=now,
    )
    OrderChange.objects.create(
        order=order, reason=reason, actor_name=actor_name,
        changes={"台數與傭金歸屬車行": {"before": before, "after": after}},
    )
    OrderEvent.objects.create(
        order=order, event_type="commission_attribution_updated", actor_name=actor_name,
        description=f"調整台數與傭金歸屬：{before} → {after}；原因：{reason}",
    )
    return True
