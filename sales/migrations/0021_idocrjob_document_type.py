from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("sales", "0020_salesordersearchindex_idocrjob"),
    ]

    operations = [
        migrations.AddField(
            model_name="idocrjob",
            name="document_type",
            field=models.CharField(
                choices=[
                    ("national_id", "國民身分證"),
                    ("resident_certificate", "居留證"),
                ],
                default="national_id",
                max_length=30,
                verbose_name="證件類型",
            ),
        ),
    ]
