from django.db import migrations, models


def create_index(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute("CREATE INDEX IF NOT EXISTS sales_order_safe_search_trgm ON sales_salesordersearchindex USING gin (safe_search_text gin_trgm_ops)")


def drop_index(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute("DROP INDEX IF EXISTS sales_order_safe_search_trgm")


def backfill(apps, schema_editor):
    """從既有快取移除原始財務標籤；同名一般欄位也保守排除，待重建恢復。"""
    Index = apps.get_model("sales", "SalesOrderSearchIndex")
    Snapshot = apps.get_model("sales", "LegacySalesSnapshot")
    Profile = apps.get_model("sales", "OrderOperationsProfile")
    db = schema_editor.connection.alias
    private_labels = {str(f.verbose_name) for f in Profile._meta.fields if isinstance(f, models.JSONField)}
    raw_labels = {row.order_id: set((row.raw_financials or {}).keys()) for row in Snapshot.objects.using(db).all().iterator()}
    for row in Index.objects.using(db).all().iterator():
        excluded = private_labels | raw_labels.get(row.order_id, set())
        payload = [item for item in row.match_payload if item.get("label") not in excluded]
        def normalise(value):
            return str(value or "").strip().casefold().replace(" ", "").replace("-", "").replace("/", "").replace("／", "")
        Index.objects.using(db).filter(pk=row.pk).update(safe_match_payload=payload,
            safe_search_text="\n".join({normalise(item.get("value")) for item in payload if item.get("value")}))


class Migration(migrations.Migration):
    dependencies = [("sales", "0138_dealer_visible_features")]
    operations = [
        migrations.AddField(model_name="salesordersearchindex", name="safe_search_text", field=models.TextField("不含原始財務的搜尋文字", blank=True)),
        migrations.AddField(model_name="salesordersearchindex", name="safe_match_payload", field=models.JSONField("不含原始財務的命中資料", default=list, blank=True)),
        migrations.RunPython(backfill, migrations.RunPython.noop),
        migrations.RunPython(create_index, drop_index),
    ]
