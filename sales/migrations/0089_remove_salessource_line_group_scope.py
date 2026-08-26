from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("sales", "0088_sales_source_contact_and_cooperation_profiles"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="salessource",
            name="line_group_scope",
        ),
    ]
