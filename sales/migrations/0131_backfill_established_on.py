from django.db import migrations
from django.utils import timezone


def backfill(apps, schema_editor):
    Order = apps.get_model("sales", "SalesOrder")
    Snapshot = apps.get_model("sales", "LegacySalesSnapshot")
    db = schema_editor.connection.alias
    imported = set(Snapshot.objects.using(db).values_list("order_id", flat=True))
    for order in Order.objects.using(db).only("id", "created_at", "registration_date").iterator():
        formed = order.registration_date if order.pk in imported else timezone.localdate(order.created_at)
        Order.objects.using(db).filter(pk=order.pk).update(established_on=formed)


class Migration(migrations.Migration):
    dependencies = [("sales", "0130_imported_card_fee_snapshot")]
    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
