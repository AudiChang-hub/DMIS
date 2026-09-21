import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("sales", "0145_announcement_targeting_and_custom_pricing")]

    operations = [
        migrations.AlterModelOptions(name="announcementimage", options={"ordering": ("position", "pk")}),
        migrations.AddField(model_name="announcementimage", name="position", field=models.PositiveIntegerField(default=0)),
        migrations.AddField(model_name="salesorder", name="cash_receivable_v2", field=models.BooleanField(default=False, editable=False)),
        migrations.AlterField(model_name="orderintakeattachment", name="kind", field=models.CharField(choices=[("installment", "分期表"), ("supplement", "補充檔案"), ("owner_bankbook", "車主存摺封面"), ("old_id_front", "舊車主證件正面"), ("old_id_back", "舊車主證件反面"), ("old_bankbook", "舊車主存摺封面")], max_length=16, verbose_name="附件類型")),
        migrations.CreateModel(name="AnnouncementAttachment", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("file", models.FileField(upload_to="announcements/attachments/%Y/%m/")),
            ("name", models.CharField(max_length=255)),
            ("removed", models.BooleanField(default=False)),
            ("announcement", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="attachments", to="sales.systemannouncement")),
        ]),
    ]
