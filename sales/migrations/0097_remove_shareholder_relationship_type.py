from django.db import migrations, models


def normalize_shareholder_relationships(apps, schema_editor):
    profile_model = apps.get_model("sales", "SalesSourceCooperationProfile")
    profile_model.objects.filter(relationship_type="shareholder").update(
        relationship_type="general"
    )


class Migration(migrations.Migration):
    dependencies = [
        ("sales", "0096_businessholiday_source"),
    ]

    operations = [
        migrations.RunPython(
            normalize_shareholder_relationships,
            migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name="salessourcecooperationprofile",
            name="relationship_type",
            field=models.CharField(
                choices=[("general", "一般"), ("exclusive", "專銷")],
                default="general",
                max_length=20,
                verbose_name="關係類型",
            ),
        ),
    ]
