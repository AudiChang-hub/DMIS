from django.db import migrations, models
import django.db.models.deletion


def link_emoving_to_suzuki(apps, schema_editor):
    VehicleBrand = apps.get_model("sales", "VehicleBrand")
    suzuki = VehicleBrand.objects.filter(name__iexact="SUZUKI").first()
    emoving = VehicleBrand.objects.filter(name__iexact="eMOVING").first()
    if suzuki and emoving and emoving.pk != suzuki.pk:
        VehicleBrand.objects.filter(pk=emoving.pk).update(parent_id=suzuki.pk)


def unlink_emoving(apps, schema_editor):
    VehicleBrand = apps.get_model("sales", "VehicleBrand")
    VehicleBrand.objects.filter(name__iexact="eMOVING").update(parent_id=None)


class Migration(migrations.Migration):
    dependencies = [("sales", "0060_vehicle_brand_master")]

    operations = [
        migrations.AddField(
            model_name="vehiclebrand",
            name="parent",
            field=models.ForeignKey(
                blank=True,
                help_text="例如 eMOVING 所屬主品牌為 SUZUKI；交易仍保留 eMOVING 品牌名稱。",
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="sub_brands",
                to="sales.vehiclebrand",
                verbose_name="所屬主品牌",
            ),
        ),
        migrations.RunPython(link_emoving_to_suzuki, unlink_emoving),
    ]
