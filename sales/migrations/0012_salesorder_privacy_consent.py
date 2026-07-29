from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("sales", "0011_order_editing_and_remove_contract_gate")]

    operations = [
        migrations.AddField(
            model_name="salesorder",
            name="privacy_consent",
            field=models.FileField(
                blank=True,
                upload_to="orders/privacy-consents/%Y/%m/",
                verbose_name="已簽署個資同意書",
            ),
        ),
        migrations.AddField(
            model_name="salesorder",
            name="privacy_consent_uploaded_at",
            field=models.DateTimeField(
                blank=True,
                null=True,
                verbose_name="個資同意書上傳時間",
            ),
        ),
    ]
