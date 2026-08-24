from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("sales", "0079_alter_vehiclemodel_model_code"),
    ]

    operations = [
        migrations.AlterField(
            model_name="vehiclemodel",
            name="model_code",
            field=models.CharField(
                blank=True,
                choices=[
                    ("drum", "鼓"),
                    ("hub_front_drum", "輪轂前鼓"),
                    ("hub_front_disc", "輪轂前碟"),
                    ("front_disc_rear_drum", "前碟後鼓"),
                    ("cbs_drum", "CBS鼓"),
                    ("cbs_disc", "CBS碟"),
                    ("abs_disc", "ABS碟"),
                    ("cbs_dual_disc", "CBS雙碟"),
                    ("abs_dual_disc", "ABS雙碟"),
                    ("disc", "碟"),
                    ("abs_triple_disc", "ABS三碟"),
                ],
                max_length=40,
                verbose_name="型式",
            ),
        ),
    ]
