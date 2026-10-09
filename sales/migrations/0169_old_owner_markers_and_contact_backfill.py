"""舊車主資料整理（1.59.0，使用者核准方案 B）。

1. Excel「舊車車主」填「有」代表有舊車要汰舊、「無」代表沒有；匯入時被當成姓名保存。
   「無」→ 清空；「有」→ 清空並將新車訂單標為申請汰舊／政府補助。舊車主證號的「有／無」一併清空。
   每筆寫入一筆訂單變更紀錄（原因以 MARK 開頭），反向遷移依這些紀錄還原並刪除紀錄。
2. 從匯入快照回填 Excel「舊車車主電話」「舊車戶籍」到新欄位（只填目前空白的訂單）。
"""
from django.db import migrations

MARK = "資料整理（1.59.0）：Excel 舊車車主「有／無」"
LABELS = {
    "old_owner_name": "舊車主姓名",
    "old_owner_id_number": "舊車主身分證字號",
    "is_trade_in_subsidy": "申請汰舊／政府補助",
}
MARKERS = {"有", "無"}


def _clean(value):
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = str(value).strip()
    return "" if text in {"0", "0.0"} else text


def forwards(apps, schema_editor):
    SalesOrder = apps.get_model("sales", "SalesOrder")
    OrderChange = apps.get_model("sales", "OrderChange")
    LegacySalesSnapshot = apps.get_model("sales", "LegacySalesSnapshot")

    for order in SalesOrder.objects.filter(old_owner_name__in=MARKERS) | SalesOrder.objects.filter(old_owner_id_number__in=MARKERS):
        changes = {}
        has_trade_in = "有" in {order.old_owner_name.strip(), order.old_owner_id_number.strip()}
        for field in ("old_owner_name", "old_owner_id_number"):
            if getattr(order, field).strip() in MARKERS:
                changes[LABELS[field]] = {"before": getattr(order, field), "after": ""}
                setattr(order, field, "")
        if has_trade_in and order.vehicle_category == "new" and not order.is_trade_in_subsidy:
            changes[LABELS["is_trade_in_subsidy"]] = {"before": "False", "after": "True"}
            order.is_trade_in_subsidy = True
        if not changes:
            continue
        order.save(update_fields=["old_owner_name", "old_owner_id_number", "is_trade_in_subsidy", "updated_at"])
        OrderChange.objects.create(
            order=order,
            reason=f"{MARK}轉為汰舊標記：「有」代表有舊車要汰舊，「無」代表沒有。",
            changes=changes,
            actor_name="系統資料整理",
        )

    for snapshot in LegacySalesSnapshot.objects.select_related("order", "import_row"):
        raw = snapshot.import_row.raw_data or {}
        order = snapshot.order
        phone = _clean(raw.get("舊車車主電話"))
        household = _clean(raw.get("舊車戶籍"))
        fields = []
        if phone and not order.old_owner_phone:
            order.old_owner_phone = phone[:50]
            fields.append("old_owner_phone")
        if household and not order.old_owner_household_address:
            order.old_owner_household_address = household[:255]
            fields.append("old_owner_household_address")
        if fields:
            order.save(update_fields=[*fields, "updated_at"])


def backwards(apps, schema_editor):
    SalesOrder = apps.get_model("sales", "SalesOrder")
    OrderChange = apps.get_model("sales", "OrderChange")
    fields = {label: field for field, label in LABELS.items()}
    for change in OrderChange.objects.filter(reason__startswith=MARK, actor_name="系統資料整理"):
        order = SalesOrder.objects.filter(pk=change.order_id).first()
        if order:
            for label, values in change.changes.items():
                field = fields[label]
                before = values["before"]
                setattr(order, field, before == "True" if field == "is_trade_in_subsidy" else before)
            order.save(update_fields=["old_owner_name", "old_owner_id_number", "is_trade_in_subsidy", "updated_at"])
        change.delete()
    # 回填的電話與戶籍隨 0168 反向移除欄位一併刪除。


class Migration(migrations.Migration):

    dependencies = [
        ("sales", "0168_sales_order_old_owner_contact"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
