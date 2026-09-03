from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("sales", "0111_order_commission_recipient")]
    operations = [
        migrations.AddField(
            model_name="orderoperationsprofile",
            name="payment_disbursement_snapshot",
            field=models.JSONField(
                "收款連動前撥款快照", default=dict, blank=True, editable=False,
                help_text="取消收款確認時恢復先前值；不回推舊資料。",
            ),
        ),
    ]
