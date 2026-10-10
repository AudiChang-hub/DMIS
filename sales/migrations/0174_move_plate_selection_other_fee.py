"""把填在「其他費用」的選號改到「選號費」（使用者 2026-10-10 選方案 1）。

只處理尚未完成領牌、選號費仍是 0 的訂單：其他費用名稱為「選號／選號費」的金額移到選號費並計入牌險合計，
客人應付總額不變（其他費用減少、牌險合計增加相同金額）；收支表的選號收入／支出同步帶入（人工調整過的欄位不動）。
"""
from django.db import migrations

NAMES = {"選號", "選號費"}


def move(apps, schema_editor):
    OtherFeeLine = apps.get_model("sales", "OtherFeeLine")
    SalesOrder = apps.get_model("sales", "SalesOrder")
    Profile = apps.get_model("sales", "OrderOperationsProfile")
    OrderEvent = apps.get_model("sales", "OrderEvent")
    for line in OtherFeeLine.objects.select_related("order").order_by("id"):
        if line.name.strip() not in NAMES or not line.amount:
            continue
        order = line.order
        if order.registration_completed_at or order.plate_selection_fee:
            continue
        amount = line.amount
        automatic = order.plate_insurance_fee == order.registration_calculated_total
        SalesOrder.objects.filter(pk=order.pk).update(
            plate_selection_fee=amount,
            plate_insurance_fee=order.plate_insurance_fee + amount,
            registration_calculated_total=(
                order.registration_calculated_total + amount if automatic else order.registration_calculated_total
            ),
        )
        line.delete()
        profile = Profile.objects.filter(order_id=order.pk).first()
        if profile:
            manual = set(profile.manual_financial_fields or [])
            fields = [name for name in ("plate_selection_income", "plate_selection_expense") if name not in manual]
            for name in fields:
                setattr(profile, name, amount)
            if fields:
                profile.save(update_fields=[*fields, "updated_at"])
        OrderEvent.objects.create(
            order_id=order.pk, event_type="updated", actor_name="系統（1.63.0 選號費搬移）",
            description=f"其他費用「{line.name}」{amount:.0f} 元改記為選號費並計入牌險合計；客人應付總額不變。",
        )


class Migration(migrations.Migration):
    dependencies = [
        ("sales", "0173_fix_future_disposition_dates"),
    ]

    operations = [
        migrations.RunPython(move, migrations.RunPython.noop),
    ]
