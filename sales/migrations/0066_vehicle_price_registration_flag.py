from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("sales", "0065_populate_vehicle_model_families"),
    ]

    operations = [
        migrations.RenameField(
            model_name="vehiclepriceversion",
            old_name="suggested_price_including_registration",
            new_name="suggested_price",
        ),
        migrations.AlterField(
            model_name="vehiclepriceversion",
            name="suggested_price",
            field=models.DecimalField(
                blank=True,
                decimal_places=0,
                max_digits=12,
                null=True,
                verbose_name="建議售價",
            ),
        ),
        migrations.AddField(
            model_name="vehiclepriceversion",
            name="suggested_price_includes_registration",
            field=models.BooleanField(
                default=True,
                help_text=(
                    "勾選表示此版本的建議售價已包含牌險；未勾選則依正式單據另收。"
                ),
                verbose_name="建議售價包含牌險",
            ),
        ),
    ]
