"""T-232 第 3a 版：「訂單批次修改（回匯）」上線時授權給所有現有帳號（使用者 2026-11-18 Q3 選 A）。

已設定權限的帳號補上 `order_bulk_update` 查看＋操作；之後新增的帳號要在權限頁手動勾。權限判斷邏輯不變，
寫入時照樣逐區段檢查與訂單頁相同的操作權限。未設定權限的帳號、root 原本就全開，不處理。
沿用 0141／0216 的寫法：版本號加一並寫入權限歷程。反向不還原（無法分辨哪些是之後人工勾的）。
"""
from django.db import migrations

ACTOR = "system:0218-order-bulk-update"
SCREEN = "order_bulk_update"


def grant_bulk_update(apps, schema_editor):
    Grant = apps.get_model("sales", "ScreenAccessGrant")
    State = apps.get_model("sales", "UserAccessState")
    Revision = apps.get_model("sales", "UserAccessRevision")
    Report = apps.get_model("sales", "ReportAccessGrant")
    db = schema_editor.connection.alias
    for state in State.objects.using(db).filter(configured=True, user__is_active=True).iterator():
        grants = Grant.objects.using(db).filter(user_id=state.user_id)
        if grants.filter(screen_key=SCREEN, view=True, operate=True).exists():
            continue
        before = {"screens": {g.screen_key: {"view": g.view, "operate": g.operate, "export": g.export} for g in grants},
                  "reports": {str(r.report_id): {"view": r.view, "operate": r.operate, "export": r.export}
                              for r in Report.objects.using(db).filter(user_id=state.user_id)}}
        grant, _created = Grant.objects.using(db).get_or_create(user_id=state.user_id, screen_key=SCREEN)
        grant.view = True
        grant.operate = True
        grant.save(using=db, update_fields=["view", "operate"])
        after = {**before, "screens": {**before["screens"],
                                       SCREEN: {"view": True, "operate": True, "export": grant.export}}}
        state.version += 1
        state.save(using=db, update_fields=["version", "updated_at"])
        Revision.objects.using(db).create(user_id=state.user_id, version=state.version, before=before, after=after,
                                         actor_name=ACTOR)


class Migration(migrations.Migration):
    dependencies = [("sales", "0217_order_bulk_update")]
    operations = [migrations.RunPython(grant_bulk_update, migrations.RunPython.noop)]
