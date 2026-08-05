from datetime import date

from django.db import migrations


HOLIDAYS = {
    date(2026, 1, 1): "中華民國開國紀念日",
    date(2026, 2, 16): "春節連假",
    date(2026, 2, 17): "春節連假",
    date(2026, 2, 18): "春節連假",
    date(2026, 2, 19): "春節連假",
    date(2026, 2, 20): "春節連假",
    date(2026, 2, 27): "和平紀念日補假",
    date(2026, 4, 3): "兒童節補假",
    date(2026, 4, 6): "清明節補假",
    date(2026, 5, 1): "勞動節",
    date(2026, 6, 19): "端午節",
    date(2026, 9, 25): "中秋節",
    date(2026, 9, 28): "教師節",
    date(2026, 10, 9): "國慶日補假",
    date(2026, 10, 26): "臺灣光復暨金門古寧頭大捷紀念日補假",
    date(2026, 12, 25): "行憲紀念日",
    date(2027, 1, 1): "中華民國開國紀念日",
    date(2027, 2, 4): "春節連假",
    date(2027, 2, 5): "春節連假",
    date(2027, 2, 8): "春節連假",
    date(2027, 2, 9): "春節連假",
    date(2027, 2, 10): "春節連假",
    date(2027, 3, 1): "和平紀念日補假",
    date(2027, 4, 5): "兒童節補假",
    date(2027, 4, 6): "清明節補假",
    date(2027, 4, 30): "勞動節補假",
    date(2027, 6, 9): "端午節",
    date(2027, 9, 15): "中秋節",
    date(2027, 9, 28): "教師節",
    date(2027, 10, 11): "國慶日補假",
    date(2027, 10, 25): "臺灣光復暨金門古寧頭大捷紀念日",
    date(2027, 12, 24): "行憲紀念日補假",
    date(2027, 12, 31): "中華民國開國紀念日補假",
}


def seed_holidays(apps, schema_editor):
    BusinessHoliday = apps.get_model("sales", "BusinessHoliday")
    for holiday_date, name in HOLIDAYS.items():
        BusinessHoliday.objects.update_or_create(
            date=holiday_date,
            defaults={"name": name, "active": True},
        )


def remove_seeded_holidays(apps, schema_editor):
    BusinessHoliday = apps.get_model("sales", "BusinessHoliday")
    for holiday_date, name in HOLIDAYS.items():
        BusinessHoliday.objects.filter(date=holiday_date, name=name).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("sales", "0039_businessholiday_salesorder_cancellation_completed_at_and_more"),
    ]

    operations = [
        migrations.RunPython(seed_holidays, remove_seeded_holidays),
    ]
