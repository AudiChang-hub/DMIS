"""分離建立權限，保留既有能力並記錄系統遷移稽核。"""
from django.db import migrations


def split_intake_access(apps, schema_editor):
    Grant = apps.get_model("sales", "ScreenAccessGrant")
    State = apps.get_model("sales", "UserAccessState")
    Revision = apps.get_model("sales", "UserAccessRevision")
    Report = apps.get_model("sales", "ReportAccessGrant")
    db = schema_editor.connection.alias
    for state in State.objects.using(db).filter(configured=True).iterator():
        grants = Grant.objects.using(db).filter(user_id=state.user_id)
        if grants.filter(screen_key="order_intake").exists() or not grants.filter(screen_key="orders", view=True, operate=True).exists():
            continue
        before = {"screens": {g.screen_key: {"view": g.view, "operate": g.operate, "export": g.export} for g in grants},
                  "reports": {str(r.report_id): {"view": r.view, "operate": r.operate, "export": r.export}
                              for r in Report.objects.using(db).filter(user_id=state.user_id)}}
        Grant.objects.using(db).create(user_id=state.user_id, screen_key="order_intake", view=True, operate=True)
        after = {**before, "screens": {**before["screens"], "order_intake": {"view": True, "operate": True, "export": False}}}
        state.version += 1
        state.save(using=db, update_fields=["version", "updated_at"])
        Revision.objects.using(db).create(user_id=state.user_id, version=state.version, before=before, after=after,
                                         actor_name="system:0141-order-intake")


class Migration(migrations.Migration):
    dependencies = [("sales", "0140_salesorder_recycle_bin")]
    operations = [migrations.RunPython(split_intake_access, migrations.RunPython.noop)]
