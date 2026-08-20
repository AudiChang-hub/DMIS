from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("sales", "0071_clean_legacy_odoo_price_notes")]

    operations = [
        migrations.AddField(
            model_name="vehiclebrand",
            name="logo_crop_data",
            field=models.JSONField(
                blank=True,
                default=dict,
                editable=False,
                verbose_name="品牌 LOGO 裁切設定",
            ),
        ),
        migrations.AddField(
            model_name="vehiclebrand",
            name="logo_original",
            field=models.ImageField(
                blank=True,
                editable=False,
                upload_to="brands/logo-originals/%Y/%m/",
                verbose_name="品牌 LOGO 原圖",
            ),
        ),
    ]
