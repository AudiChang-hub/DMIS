from datetime import date

from django.db import migrations


def move_legacy_suggested_prices(apps, schema_editor):
    VehicleModel = apps.get_model("sales", "VehicleModel")
    VehiclePriceVersion = apps.get_model("sales", "VehiclePriceVersion")

    for vehicle_model in VehicleModel.objects.exclude(suggested_price__isnull=True).iterator():
        legacy_price = vehicle_model.suggested_price
        if legacy_price is None:
            continue

        latest_version = (
            VehiclePriceVersion.objects.filter(vehicle_model_id=vehicle_model.pk)
            .order_by("-effective_from", "-id")
            .first()
        )
        if latest_version is None:
            VehiclePriceVersion.objects.create(
                vehicle_model_id=vehicle_model.pk,
                suggested_retail_price=legacy_price,
                announced_on=date(2026, 1, 1),
                effective_from=date(2026, 1, 1),
                source_note="舊車型建議售價轉入",
                active=True,
            )
            continue

        if latest_version.suggested_retail_price in (None, 0):
            latest_version.suggested_retail_price = legacy_price
            latest_version.save(update_fields=["suggested_retail_price", "updated_at"])


class Migration(migrations.Migration):
    dependencies = [
        ("sales", "0057_alter_vehiclemodel_model_code"),
    ]

    operations = [
        migrations.RunPython(move_legacy_suggested_prices, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="vehiclemodel",
            name="suggested_price",
        ),
    ]
