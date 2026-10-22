from django.db import migrations

# 統一撥款對帳（使用者 2026-10-22 T-96）：系統建立的網路平台單補一筆「平台撥款」列，應收 0、未入帳，
# 由人員在對帳頁按入帳。Excel 匯入單不補。只寫資料，不改資料表。


def add_platform_rows(apps, schema_editor):
    SalesOrder = apps.get_model("sales", "SalesOrder")
    PaymentRecord = apps.get_model("sales", "PaymentRecord")
    orders = SalesOrder.objects.filter(
        source_type="platform", deleted_at__isnull=True, legacy_snapshot__isnull=True,
    ).exclude(payment_records__system_key="platform_disbursement")
    for order in orders:
        PaymentRecord.objects.create(
            order=order, system_key="platform_disbursement", item_name="平台撥款", receipt_kind="lender",
            expected_amount=0, received_amount=0, payment_method="平台撥款",
        )


def refresh_stale_installment_estimates(apps, schema_editor):
    """10-21 T-62 之前存的自訂分期快照沒有預估撥款；改用同期數方案比例重算，未入帳的撥款列跟著更新預計金額。"""
    SalesOrder = apps.get_model("sales", "SalesOrder")
    PaymentRecord = apps.get_model("sales", "PaymentRecord")
    candidates = [
        order.pk for order in SalesOrder.objects.filter(
            payment_type="installment", deleted_at__isnull=True, legacy_snapshot__isnull=True,
        ).only("pk", "installment_plan_snapshot")
        if (order.installment_plan_snapshot or {}).get("expected_disbursement_method") == "manual"
        and (order.installment_plan_snapshot or {}).get("expected_disbursement_amount") is None
    ]
    open_rows = PaymentRecord.objects.filter(
        order_id__in=candidates, system_key="installment_disbursement", confirmed=False,
        received_amount=0, expected_amount_overridden=False,
    )
    order_ids = list(open_rows.values_list("order_id", flat=True))
    if not order_ids:
        return
    # 只有正式資料有符合的訂單時才載入現行程式，空資料庫（測試）不受日後欄位變動影響。
    from sales.models import SalesOrder as LiveOrder
    from sales.services.installment_plan import apply_order_installment_snapshot

    for order in LiveOrder.objects.filter(pk__in=order_ids):
        apply_order_installment_snapshot(order)
        amount = (order.installment_plan_snapshot or {}).get("expected_disbursement_amount")
        if amount is not None:
            open_rows.filter(order_id=order.pk).update(expected_amount=amount)


def remove_empty_platform_rows(apps, schema_editor):
    PaymentRecord = apps.get_model("sales", "PaymentRecord")
    PaymentRecord.objects.filter(
        system_key="platform_disbursement", confirmed=False, received_amount=0, proof="", note="",
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("sales", "0195_salesorder_status_awaiting_registration_label"),
    ]

    operations = [
        migrations.RunPython(add_platform_rows, remove_empty_platform_rows),
        migrations.RunPython(refresh_stale_installment_estimates, migrations.RunPython.noop),
    ]
