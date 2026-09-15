from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("sales", "0139_safe_order_search")]
    operations = [
        migrations.AddField(model_name="salesorder", name="deleted_at", field=models.DateTimeField("刪除時間", null=True, blank=True, db_index=True, editable=False)),
        migrations.AddField(model_name="salesorder", name="deleted_by", field=models.CharField("刪除人員", max_length=150, blank=True, editable=False)),
        migrations.AddField(model_name="salesorder", name="deletion_reason", field=models.CharField("刪除原因", max_length=500, blank=True, editable=False)),
    ]
