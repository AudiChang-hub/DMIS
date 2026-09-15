from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("sales", "0141_order_intake_access"), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.AddField(model_name="salesorder", name="deletion_requested_at", field=models.DateTimeField("刪除申請時間", null=True, blank=True, db_index=True, editable=False)),
        migrations.AddField(model_name="salesorder", name="deletion_requested_by", field=models.ForeignKey(to=settings.AUTH_USER_MODEL, on_delete=django.db.models.deletion.PROTECT, null=True, blank=True, related_name="order_deletion_requests", editable=False)),
        migrations.AddField(model_name="salesorder", name="deletion_request_reason", field=models.CharField("刪除申請原因", max_length=500, blank=True, editable=False)),
        migrations.AddField(model_name="salesorder", name="deletion_effects", field=models.JSONField("刪除影響快照", default=dict, blank=True, editable=False)),
        migrations.AddField(model_name="dealervolumebonusallocation", name="voided_at", field=models.DateTimeField("訂單刪除作廢時間", null=True, blank=True, editable=False)),
    ]
