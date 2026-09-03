from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("sales", "0112_payment_disbursement_snapshot")]
    operations = [migrations.AddField(
        model_name="userappearancepreference", name="calendar_view",
        field=models.CharField("工作日曆檢視", max_length=5, default="month", choices=[("year", "年"), ("month", "月"), ("day", "日")]),
    )]
