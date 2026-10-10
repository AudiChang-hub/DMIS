"""預先建立使用者提到的補助方案（2026-10-10）；單位設「其他」、預設金額留空，由使用者在主檔調整。"""
from django.db import migrations

PROGRAMS = (
    ("汰舊換新", True, 10),
    ("新購補助", False, 20),
    ("貨物稅補助", False, 30),
)


def seed(apps, schema_editor):
    SubsidyProgram = apps.get_model("sales", "SubsidyProgram")
    for name, requires_old_vehicle, sort_order in PROGRAMS:
        SubsidyProgram.objects.get_or_create(
            name=name,
            defaults={"category": "other", "requires_old_vehicle": requires_old_vehicle, "sort_order": sort_order},
        )


class Migration(migrations.Migration):
    dependencies = [
        ("sales", "0175_subsidy_program"),
    ]

    operations = [
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
