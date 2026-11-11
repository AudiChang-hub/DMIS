from django.db.models.signals import m2m_changed, pre_delete, post_delete, post_save, pre_save
from django.dispatch import receiver
from django.db import transaction
from .models import OrderAttachment, OrderIntakeAttachment


@receiver(post_delete, sender=OrderAttachment)
@receiver(post_delete, sender=OrderIntakeAttachment)
def remove_intake_attachment_file(sender, instance, **kwargs):
    if instance.file:
        storage, name = instance.file.storage, instance.file.name
        transaction.on_commit(lambda: storage.delete(name))

from .models import (
    AccessoryLine,
    OrderChange,
    OrderEvent,
    OrderOperationsProfile,
    OtherFeeLine,
    PaymentRecord,
    RegistrationDocument,
    SalesOrder,
    SubsidyDocument,
    VehicleInventory,
    VehicleFactoryModelCode,
    VehicleModel,
    VehicleSettlementCostRule,
    VehicleIncentiveRule,
    IncentiveCampaign,
    DealerRewardCampaign,
    DealerRewardCampaignItem,
    SalesSourceBrandPolicy,
    DealerVolumeBonusRule,
    DealerVolumeBonusPeriod,
    DealerVolumeBonusBrand,
    DealerVolumeBonusTier,
    DealerVolumeBonusSettlement,
)
from .services.operations_sync import (
    refresh_payment_confirmation,
    sync_payment_financials,
    sync_order_operations,
)
from .services.order_search import schedule_order_search_rebuild


ORDER_CHILD_MODELS = (
    AccessoryLine,
    OtherFeeLine,
    RegistrationDocument,
    SubsidyDocument,
    OrderEvent,
    OrderChange,
    OrderOperationsProfile,
    PaymentRecord,
)


@receiver(m2m_changed, sender=DealerVolumeBonusRule.vehicle_models.through)
def protect_settled_bonus_models(sender, instance, action, reverse, pk_set, **kwargs):
    if action not in {"pre_add", "pre_remove", "pre_clear"}:
        return
    from django.core.exceptions import ValidationError
    from django.db import transaction
    ids = (pk_set if pk_set is not None else instance.volume_bonus_rules.values_list("pk", flat=True)) if reverse else [instance.pk]
    with transaction.atomic():
        locked = list(DealerVolumeBonusRule.objects.select_for_update().filter(pk__in=ids).order_by("pk").values_list("pk", flat=True))
        if DealerVolumeBonusSettlement.objects.filter(rule_id__in=locked).exists():
            raise ValidationError("已結算規則不可修改指定車型，請另建新規則。")


@receiver(pre_delete, sender=DealerVolumeBonusTier)
@receiver(pre_delete, sender=DealerVolumeBonusBrand)
def protect_settled_bonus_tier_delete(sender, instance, **kwargs):
    from django.core.exceptions import ValidationError
    from django.db import transaction
    with transaction.atomic():
        DealerVolumeBonusRule.objects.select_for_update().get(pk=instance.rule_id)
        if DealerVolumeBonusSettlement.objects.filter(rule_id=instance.rule_id).exists():
            raise ValidationError("已結算規則不可刪除門檻或品牌，請另建新規則。")


@receiver(pre_delete, sender=DealerVolumeBonusPeriod)
def protect_settled_bonus_period(sender, instance, **kwargs):
    from django.core.exceptions import ValidationError
    from django.db import transaction
    with transaction.atomic():
        DealerVolumeBonusRule.objects.select_for_update().get(pk=instance.rule_id)
        if instance.settlements.exists():
            raise ValidationError("已結算期間不可取消。")


# 台數獎金自動計算（T-148）：影響台數群組的欄位一變，就重算原本與現在所屬的群組。
VOLUME_BONUS_ORDER_FIELDS = ("source_type", "source_id", "commission_recipient_id", "vehicle_model_id",
                             "registration_date", "registration_completed_at", "status", "deleted_at")


@receiver(pre_save, sender=SalesOrder)
def remember_volume_bonus_fields(sender, instance, raw=False, **kwargs):
    if raw or not instance.pk:
        instance._volume_bonus_before = None
        return
    instance._volume_bonus_before = SalesOrder.all_objects.filter(pk=instance.pk).values(*VOLUME_BONUS_ORDER_FIELDS).first()


@receiver(post_save, sender=SalesOrder)
def refresh_volume_bonus_after_order_save(sender, instance, created, raw=False, **kwargs):
    if raw:
        return
    before = getattr(instance, "_volume_bonus_before", None)
    if created or before is None or any(before[name] != getattr(instance, name) for name in VOLUME_BONUS_ORDER_FIELDS):
        if created and not instance.registration_completed_at:
            return
        from .services.volume_bonus import schedule_order_refresh
        schedule_order_refresh(instance.pk)


@receiver(post_save, sender=DealerVolumeBonusRule)
def refresh_volume_bonus_after_rule_save(sender, instance, raw=False, **kwargs):
    if not raw:
        from .services.volume_bonus import schedule_rule_refresh
        schedule_rule_refresh(instance.pk)


@receiver(pre_delete, sender=DealerVolumeBonusPeriod)
def refresh_commission_before_bonus_period_delete(sender, instance, **kwargs):
    # 期間（或整條規則）刪除會連帶刪掉獎金列；提交後把已入帳的獎金從傭金支出拿掉。
    from .models import OrderVolumeBonus
    from .services.volume_bonus import schedule_commission_refresh
    schedule_commission_refresh(set(OrderVolumeBonus.objects.filter(
        period=instance, posted_at__isnull=False).values_list("order_id", flat=True)))


@receiver(post_save, sender=SalesOrder)
def rebuild_search_after_order_save(sender, instance, **kwargs):
    sync_order_operations(instance.pk, update_receivables=getattr(instance, "_receivable_changed", False))
    schedule_order_search_rebuild(instance.pk)


def _rebuild_child_order(instance):
    if instance.order_id:
        schedule_order_search_rebuild(instance.order_id)


for child_model in ORDER_CHILD_MODELS:
    post_save.connect(
        lambda sender, instance, **kwargs: _rebuild_child_order(instance),
        sender=child_model,
        weak=False,
        dispatch_uid=f"sales.search_index.save.{child_model.__name__}",
    )
    post_delete.connect(
        lambda sender, instance, **kwargs: _rebuild_child_order(instance),
        sender=child_model,
        weak=False,
        dispatch_uid=f"sales.search_index.delete.{child_model.__name__}",
    )


@receiver(post_save, sender=VehicleInventory)
def rebuild_search_after_vehicle_save(sender, instance, **kwargs):
    order_id = (
        SalesOrder.objects.filter(allocated_vehicle_id=instance.pk)
        .values_list("pk", flat=True)
        .first()
    )
    if order_id:
        sync_order_operations(order_id)
        schedule_order_search_rebuild(order_id)


def _rebuild_vehicle_model_orders(vehicle_model_ids):
    order_ids = SalesOrder.objects.filter(
        vehicle_model_id__in=vehicle_model_ids
    ).values_list("pk", flat=True)
    for order_id in order_ids.iterator(chunk_size=200):
        schedule_order_search_rebuild(order_id)


@receiver(post_save, sender=VehicleModel)
def rebuild_search_after_vehicle_model_save(sender, instance, **kwargs):
    _rebuild_vehicle_model_orders([instance.pk])
    _refresh_pending_rates(SalesOrder.objects.filter(vehicle_model_id=instance.pk))


def _refresh_pending_rates(orders):
    from .services.financial_refresh import refresh_unlocked_financials
    for order_id in orders.filter(registration_completed_at__isnull=True).exclude(
        status=SalesOrder.Status.CANCELLED,
    ).order_by("pk").values_list("pk", flat=True):
        refresh_unlocked_financials(order_id)


@receiver(post_save, sender=VehicleSettlementCostRule)
@receiver(post_delete, sender=VehicleSettlementCostRule)
@receiver(post_save, sender=VehicleIncentiveRule)
@receiver(post_delete, sender=VehicleIncentiveRule)
@receiver(post_save, sender=SalesSourceBrandPolicy)
@receiver(post_delete, sender=SalesSourceBrandPolicy)
def refresh_pending_rates_after_rule_change(sender, instance, **kwargs):
    orders = SalesOrder.objects.filter(source_id=instance.source_id) if sender is SalesSourceBrandPolicy else (
        SalesOrder.objects.filter(vehicle_model_id=instance.vehicle_model_id)
    )
    _refresh_pending_rates(orders)


def _refresh_campaign_orders():
    _refresh_pending_rates(SalesOrder.objects.all())


def _schedule_campaign_refresh():
    """活動、條件多選或項目異動後，提交時重算未完成領牌的訂單（T-149）；已完成領牌的訂單固定不動。"""
    transaction.on_commit(_refresh_campaign_orders)


@receiver(post_save, sender=IncentiveCampaign)
@receiver(post_delete, sender=IncentiveCampaign)
@receiver(post_save, sender=DealerRewardCampaign)
@receiver(post_delete, sender=DealerRewardCampaign)
@receiver(post_save, sender=DealerRewardCampaignItem)
@receiver(post_delete, sender=DealerRewardCampaignItem)
def refresh_pending_orders_after_campaign_change(sender, instance, **kwargs):
    _schedule_campaign_refresh()


@receiver(m2m_changed, sender=IncentiveCampaign.vehicle_models.through)
@receiver(m2m_changed, sender=DealerRewardCampaign.vehicle_models.through)
@receiver(m2m_changed, sender=DealerRewardCampaign.dealers.through)
def refresh_pending_orders_after_campaign_conditions(sender, action, **kwargs):
    if action in {"post_add", "post_remove", "post_clear"}:
        _schedule_campaign_refresh()


@receiver(post_save, sender=VehicleFactoryModelCode)
def rebuild_search_after_factory_model_code_save(sender, instance, **kwargs):
    _rebuild_vehicle_model_orders(
        instance.versions.values_list("pk", flat=True)
    )


@receiver(m2m_changed, sender=VehicleModel.factory_model_codes.through)
def rebuild_search_after_factory_model_code_link(sender, instance, action, reverse, **kwargs):
    if action not in {"post_add", "post_remove", "post_clear"}:
        return
    if reverse:
        model_ids = instance.versions.values_list("pk", flat=True)
    else:
        model_ids = [instance.pk]
    _rebuild_vehicle_model_orders(model_ids)


@receiver(post_save, sender=PaymentRecord)
@receiver(post_delete, sender=PaymentRecord)
def refresh_confirmation_after_payment_change(sender, instance, **kwargs):
    if instance.order_id:
        sync_payment_financials(
            instance.order_id,
            adopt_payment_id=instance.pk if getattr(instance, "_disbursement_changed", False) else None,
            touch_revision=True,
        )


# ---- 訂單檔案同步到 NAS：訂單或其檔案有異動就排入背景同步（未設定 NAS 時不動作）----
from .models import DeliveryRecord  # noqa: E402
from .services.order_archive import schedule_order_archive  # noqa: E402


@receiver(post_save, sender=SalesOrder)
def archive_order_on_save(sender, instance, raw=False, **kwargs):
    if not raw:
        schedule_order_archive(instance.pk)


@receiver(post_save, sender=PaymentRecord)
@receiver(post_delete, sender=PaymentRecord)
@receiver(post_save, sender=DeliveryRecord)
@receiver(post_save, sender=RegistrationDocument)
@receiver(post_delete, sender=RegistrationDocument)
@receiver(post_save, sender=SubsidyDocument)
@receiver(post_delete, sender=SubsidyDocument)
@receiver(post_save, sender=OrderIntakeAttachment)
@receiver(post_delete, sender=OrderIntakeAttachment)
@receiver(post_save, sender=OrderAttachment)
@receiver(post_delete, sender=OrderAttachment)
def archive_order_files(sender, instance, raw=False, **kwargs):
    if not raw and getattr(instance, "order_id", None):
        schedule_order_archive(instance.order_id)
