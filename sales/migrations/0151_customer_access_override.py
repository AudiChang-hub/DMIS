from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("sales", "0150_customer_order_access")]
    operations = [migrations.AddField(
        model_name="ordercustomeraccessgrant", name="is_override",
        field=models.BooleanField(default=False, verbose_name="使用本筆自訂權限"),
    )]
