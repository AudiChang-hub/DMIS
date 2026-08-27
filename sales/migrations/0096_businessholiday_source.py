from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("sales", "0095_reclassify_in_house_sales_sources"),
    ]

    operations = [
        migrations.AddField(
            model_name="businessholiday",
            name="source",
            field=models.CharField(
                choices=[
                    ("manual", "人工設定"),
                    ("dgpa", "人事行政總處同步"),
                ],
                db_index=True,
                default="manual",
                max_length=20,
                verbose_name="資料來源",
            ),
        ),
    ]
