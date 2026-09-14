from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("sales", "0137_catalog_dealer_accounts")]
    operations = [
        migrations.AddField(model_name="vehiclecolor", name="catalog_image", field=models.ImageField(blank=True, upload_to="catalog/colors/%Y/%m/", verbose_name="車色展示圖片")),
        migrations.AddField(model_name="orderaccountprofile", name="can_view_orders", field=models.BooleanField(default=True, verbose_name="可查看本車行訂單")),
        migrations.AddField(model_name="orderaccountprofile", name="can_browse_catalog", field=models.BooleanField(default=True, verbose_name="可使用選車入口")),
    ]
