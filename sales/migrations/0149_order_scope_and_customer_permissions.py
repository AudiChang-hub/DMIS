from django.db import migrations, models
from django.db.models import F


def preserve_permissions(apps, schema_editor):
    Profile = apps.get_model("sales", "OrderAccountProfile")
    Grant = apps.get_model("sales", "ScreenAccessGrant")
    State = apps.get_model("sales", "UserAccessState")
    # 店內既有資料範圍維持原狀；車行依核准方案改為本人，不猜測 Excel 建立者。
    Profile.objects.filter(kind="internal").update(order_scope="all")
    Profile.objects.all().update(revision=F("revision") + 1)
    dealers = set(Profile.objects.filter(kind="dealer").values_list("user_id", flat=True))
    configured = set(State.objects.filter(configured=True).values_list("user_id", flat=True))
    gifts = set(Grant.objects.filter(screen_key="order_pricing", view=True, operate=True, user_id__in=configured).values_list("user_id", flat=True))
    gifts.update(Grant.objects.filter(screen_key="order_finance", view=True, operate=True, user_id__in=configured).exclude(user_id__in=dealers).values_list("user_id", flat=True))
    printing = set(Grant.objects.filter(screen_key="orders", view=True, export=True, user_id__in=configured).exclude(user_id__in=dealers).values_list("user_id", flat=True))
    printing.update(Profile.objects.filter(kind="dealer", can_view_orders=True).values_list("user_id", flat=True))
    for user_id in gifts:
        Grant.objects.get_or_create(user_id=user_id, screen_key="order_gift", defaults={"view": True, "operate": True, "export": False})
    for user_id in printing:
        Grant.objects.get_or_create(user_id=user_id, screen_key="order_documents", defaults={"view": True, "operate": False, "export": True})
    State.objects.filter(user_id__in=gifts | printing).update(version=F("version") + 1)


class Migration(migrations.Migration):
    dependencies = [("sales", "0148_order_print_company")]
    operations = [
        migrations.AddField(model_name="orderaccountprofile", name="order_scope", field=models.CharField(choices=[("own", "本人建立的訂單"), ("dealer", "所屬車行的訂單"), ("all", "全公司訂單（僅店內）")], default="own", max_length=12, verbose_name="訂單資料範圍")),
        migrations.AlterField(model_name="orderaccountprofile", name="can_view_orders", field=models.BooleanField(default=True, verbose_name="可查詢訂單")),
        migrations.RunPython(preserve_permissions, migrations.RunPython.noop),
    ]
