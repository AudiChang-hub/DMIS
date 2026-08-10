from django.db import migrations


# 來源：歷史「車行、網路平台.xlsx」的「車行」頁，原「月餅」欄標記 V。
LEGACY_HOLIDAY_GIFT_DEALERS = (
    "尚勁",
    "旭昶",
    "金泰發",
    "日信",
    "源泰",
    "天佑",
    "凱弘",
    "金利富",
    "嘉仁",
    "泳辰",
    "明輝",
    "昌勝",
    "宏偉",
    "岩谷",
    "北野電能",
    "奕鈞工坊",
)


def backfill_legacy_gift_dealers(apps, schema_editor):
    SalesSource = apps.get_model("sales", "SalesSource")
    SalesSource.objects.filter(
        source_type="dealer",
        name__in=LEGACY_HOLIDAY_GIFT_DEALERS,
    ).update(holiday_gift=True)


def clear_legacy_gift_dealers(apps, schema_editor):
    SalesSource = apps.get_model("sales", "SalesSource")
    SalesSource.objects.filter(
        source_type="dealer",
        name__in=LEGACY_HOLIDAY_GIFT_DEALERS,
    ).update(holiday_gift=False)


class Migration(migrations.Migration):
    dependencies = [("sales", "0050_salessource_holiday_gift")]

    operations = [
        migrations.RunPython(backfill_legacy_gift_dealers, clear_legacy_gift_dealers),
    ]
