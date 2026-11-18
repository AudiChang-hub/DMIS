"""T-232：營運匯出併入訂單匯出（匯出改看 `orders` 的匯出授權）。

原本能匯出營運資料的帳號＝已設定權限、有「財務彙總與營運匯出」(operations) 查看＋匯出，且有「查看淨利」查看＋匯出
（舊端點另由 middleware 要求淨利匯出）。這些帳號補上「訂單、草稿與文件」(orders) 的查看＋匯出，上線後照樣能匯出；
其餘授權不動。沿用 0141 的寫法：版本號加一並寫入權限歷程（actor_name 標系統遷移）。
未設定權限的帳號、root 原本就全開，不處理。反向不還原（無法分辨哪些是之後人工勾的）。
"""
from django.db import migrations

ACTOR = "system:0216-order-export"


def grant_order_export(apps, schema_editor):
    Grant = apps.get_model("sales", "ScreenAccessGrant")
    State = apps.get_model("sales", "UserAccessState")
    Revision = apps.get_model("sales", "UserAccessRevision")
    Report = apps.get_model("sales", "ReportAccessGrant")
    db = schema_editor.connection.alias
    for state in State.objects.using(db).filter(configured=True).iterator():
        grants = Grant.objects.using(db).filter(user_id=state.user_id)
        could_export = (grants.filter(screen_key="operations", view=True, export=True).exists()
                        and grants.filter(screen_key="profit", view=True, export=True).exists())
        if not could_export or grants.filter(screen_key="orders", view=True, export=True).exists():
            continue
        before = {"screens": {g.screen_key: {"view": g.view, "operate": g.operate, "export": g.export} for g in grants},
                  "reports": {str(r.report_id): {"view": r.view, "operate": r.operate, "export": r.export}
                              for r in Report.objects.using(db).filter(user_id=state.user_id)}}
        orders, _created = Grant.objects.using(db).get_or_create(user_id=state.user_id, screen_key="orders")
        orders.view = True
        orders.export = True
        orders.save(using=db, update_fields=["view", "export"])
        after = {**before, "screens": {**before["screens"],
                                       "orders": {"view": True, "operate": orders.operate, "export": True}}}
        state.version += 1
        state.save(using=db, update_fields=["version", "updated_at"])
        Revision.objects.using(db).create(user_id=state.user_id, version=state.version, before=before, after=after,
                                         actor_name=ACTOR)


class Migration(migrations.Migration):
    dependencies = [("sales", "0215_order_export_record")]
    operations = [migrations.RunPython(grant_order_export, migrations.RunPython.noop)]
