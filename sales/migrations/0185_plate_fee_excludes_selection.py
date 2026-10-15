"""牌險不含選號與動保設定（使用者 2026-10-15，方案 A）。

既有訂單的牌險（實收與試算）都含選號費＋動保設定費；改成另列後，從牌險扣掉這兩項，
總價改由 `SalesOrder.calculate_balance` 另加，客人應付金額不變。牌險小於這兩項合計的
（本來就沒有併入）牌險不動；進行中訂單的尾款補上選號費。進行中的一般訂單若把「選號收入」人工設成客人付的選號費（舊口徑），
改回跟著選號支出，差額由代辦費收入承接，避免重複計算。

只改金額口徑、不刪資料；還原用部署前備份（deploy_django.sh 會先備份）。
"""
from django.db import migrations

CLOSED_STATUSES = ("completed", "cancelled", "cancel_refund_pending", "exception_closed")


def forwards(apps, schema_editor):
    SalesOrder = apps.get_model("sales", "SalesOrder")
    OrderOperationsProfile = apps.get_model("sales", "OrderOperationsProfile")
    orders = SalesOrder.objects.filter(plate_selection_fee__gt=0) | SalesOrder.objects.filter(lien_registration_fee__gt=0)
    for order in orders:
        extras = order.plate_selection_fee + order.lien_registration_fee
        changed = []
        pairs = (
            ("plate_insurance_fee", "registration_fee_variance_confirmed_actual_total"),
            ("registration_calculated_total", "registration_fee_variance_confirmed_calculated_total"),
        )
        for total_name, confirmed_name in pairs:
            if getattr(order, total_name) >= extras > 0:
                setattr(order, total_name, getattr(order, total_name) - extras)
                changed.append(total_name)
                confirmed = getattr(order, confirmed_name)
                if confirmed is not None and confirmed >= extras:
                    setattr(order, confirmed_name, confirmed - extras)
                    changed.append(confirmed_name)
        if (
            "plate_insurance_fee" not in changed
            and order.status not in CLOSED_STATUSES
            and order.actual_balance == order.calculated_balance
        ):
            # 牌險本來就沒併入選號（例如微電車手填 0）：進行中訂單的尾款補上另收的選號費，
            # 與新的總價口徑一致（使用者 2026-10-15）。
            order.calculated_balance += extras
            order.actual_balance += extras
            changed += ["calculated_balance", "actual_balance"]
        if changed:
            order.save(update_fields=changed)
    profiles = OrderOperationsProfile.objects.filter(
        order__legacy_snapshot__isnull=True,
        order__plate_selection_fee__gt=0,
    ).exclude(order__status__in=CLOSED_STATUSES).select_related("order")
    for profile in profiles:
        manual = list(profile.manual_financial_fields or [])
        if "plate_selection_income" in manual and profile.plate_selection_income == profile.order.plate_selection_fee:
            manual.remove("plate_selection_income")
            profile.manual_financial_fields = manual
            profile.save(update_fields=["manual_financial_fields"])


class Migration(migrations.Migration):

    dependencies = [
        ("sales", "0184_compulsory_insurance_three_years"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
