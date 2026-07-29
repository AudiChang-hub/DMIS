from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("sales", "0009_draftfieldpresence_draftfieldstate")]

    operations = [
        migrations.AddField(
            model_name="salesorder",
            name="vehicle_category",
            field=models.CharField(
                choices=[("new", "新車"), ("used", "中古車")],
                default="new",
                max_length=10,
                verbose_name="車輛類別",
            ),
        ),
        migrations.AddField(
            model_name="salesorder",
            name="old_owner_name",
            field=models.CharField(
                blank=True, max_length=160, verbose_name="舊車主姓名"
            ),
        ),
    ]
