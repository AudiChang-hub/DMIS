from django.db.models.signals import post_delete, post_save
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
    VehicleModel,
)
from .services.operations_sync import (
    refresh_payment_confirmation,
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
    sync_order_operations(instance.pk)
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


@receiver(post_save, sender=VehicleModel)
def rebuild_search_after_vehicle_model_save(sender, instance, **kwargs):
    order_ids = SalesOrder.objects.filter(
        vehicle_model_id=instance.pk
    ).values_list("pk", flat=True)
    for order_id in order_ids.iterator(chunk_size=200):
        schedule_order_search_rebuild(order_id)


@receiver(post_save, sender=PaymentRecord)
@receiver(post_delete, sender=PaymentRecord)
def refresh_confirmation_after_payment_change(sender, instance, **kwargs):
    if instance.order_id:
        refresh_payment_confirmation(instance.order_id)
