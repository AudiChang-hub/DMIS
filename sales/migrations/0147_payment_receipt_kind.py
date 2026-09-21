from django.db import migrations, models


def classify_existing(apps, schema_editor):
    Payment = apps.get_model("sales", "PaymentRecord")
    Payment.objects.using(schema_editor.connection.alias).filter(
        system_key="installment_disbursement"
    ).update(receipt_kind="lender")


class Migration(migrations.Migration):
    dependencies = [("sales", "0146_announcement_media_and_receivables")]
    operations = [
        migrations.AddField(
            model_name="paymentrecord", name="receipt_kind",
            field=models.CharField(choices=[("customer", "客戶收款"), ("lender", "分期公司撥款")],
                                   default="customer", max_length=20, verbose_name="款項分類"),
        ),
        migrations.RunPython(classify_existing, migrations.RunPython.noop),
    ]
