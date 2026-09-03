from django.db.models.signals import m2m_changed, post_delete, post_save
from django.dispatch import receiver

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
    SalesSourceBrandPolicy,
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
