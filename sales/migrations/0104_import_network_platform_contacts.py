from django.db import migrations


# 原本內含合作平台窗口的姓名、手機與 Email（2026-10-22 資安健檢 F4：repo 公開，不可帶個資）。
# 已套用的資料庫不受影響；新建資料庫只建立平台來源，聯絡人改由「資料維護」頁手動建立。
PLATFORM_NAMES = [
    "遠時",
    "Friday",
    "Friday加購",
    "UDN聯合報",
    "神坊",
    "東森",
    "博客來",
    "大買家",
    "亞柏",
    "百利市",
    "Myfone",
    "PC",
    "Pchome商店街",
    "Yahoo",
    "momo",
    "台塑購物網",
    "燦坤",
    "蔡家國際",
    "露天拍賣",
    "PchomePay支付連",
    "沐集購",
    "三立電電購",
    "生活市集",
    "家樂福商城",
    "蝦皮",
    "Coupang 酷澎",
]


def import_network_platform_contacts(apps, schema_editor):
    SalesSource = apps.get_model("sales", "SalesSource")
    SalesSourceCategory = apps.get_model("sales", "SalesSourceCategory")

    category = SalesSourceCategory.objects.filter(
        system_behavior="platform",
        name="網路平台",
    ).first()
    if category is None:
        category = SalesSourceCategory.objects.create(
            name="網路平台",
            system_behavior="platform",
            active=True,
        )

    for platform_name in PLATFORM_NAMES:
        source = SalesSource.objects.filter(
            source_type="platform",
            name=platform_name,
        ).first()
        if source is None:
            SalesSource.objects.create(
                source_type="platform",
                category_id=category.pk,
                name=platform_name,
                active=True,
            )
            continue
        updates = {}
        if source.category_id is None:
            updates["category_id"] = category.pk
        generic_note = f"歷史聯絡資料：{source.name}（負責人）"
        if source.responsible_person.strip() == source.name:
            updates["responsible_person"] = ""
        if source.note.strip() == generic_note:
            updates["note"] = ""
        if updates:
            SalesSource.objects.filter(pk=source.pk).update(**updates)


class Migration(migrations.Migration):

    dependencies = [
        ("sales", "0103_network_platform_contacts"),
    ]

    operations = [
        migrations.RunPython(
            import_network_platform_contacts,
            migrations.RunPython.noop,
        ),
    ]
