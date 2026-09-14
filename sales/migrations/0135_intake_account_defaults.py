from django.conf import settings
from django.db import migrations


def defaults(apps, schema_editor):
    alias = schema_editor.connection.alias
    User = apps.get_model(*settings.AUTH_USER_MODEL.split("."))
    Source = apps.get_model("sales", "SalesSource")
    Profile = apps.get_model("sales", "OrderAccountProfile")
    Grant = apps.get_model("sales", "ScreenAccessGrant")
    admin = User.objects.using(alias).filter(username="admin").first()
    if admin:
        source, _ = Source.objects.using(alias).get_or_create(source_type="store", name="馭盛", defaults={"active": True})
        if source.active:
            Profile.objects.using(alias).get_or_create(user_id=admin.pk, defaults={"kind": "internal", "source_id": source.pk})
    # 保留先前已可編輯訂單或作業的店內權限；之後由 admin 個別調整。
    user_ids = Grant.objects.using(alias).filter(screen_key__in=["orders", "work"], view=True, operate=True).values_list("user_id", flat=True).distinct()
    for user_id in user_ids.iterator():
        Grant.objects.using(alias).get_or_create(user_id=user_id, screen_key="order_finance", defaults={"view": True, "operate": True})


class Migration(migrations.Migration):
    dependencies = [("sales", "0134_unified_order_intake")]
    operations = [migrations.RunPython(defaults, migrations.RunPython.noop)]
