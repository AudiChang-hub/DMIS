from decimal import Decimal

from django.db import migrations
from django.db.models import Q


INSTALLMENT_FIELDS = (
    "installment_company",
    "installment_amount",
    "installment_periods",
    "installment_opening_fee",
    "installment_monthly",
    "installment_applied_on",
    "installment_status",
    "installment_decided_on",
)


def clear_non_installment_details(apps, schema_editor):
    SalesOrder = apps.get_model("sales", "SalesOrder")
    OrderChange = apps.get_model("sales", "OrderChange")
    OrderEvent = apps.get_model("sales", "OrderEvent")

    residual_data = (
        ~Q(installment_company="")
        | ~Q(installment_amount=0)
        | ~Q(installment_periods=0)
        | ~Q(installment_opening_fee=0)
        | ~Q(installment_monthly=0)
        | Q(installment_applied_on__isnull=False)
        | ~Q(installment_status="")
        | Q(installment_decided_on__isnull=False)
    )
    orders = SalesOrder.objects.exclude(payment_type="installment").filter(
        residual_data
    )

    for order in orders.iterator():
        old_calculated = order.calculated_balance
        old_actual = order.actual_balance
        old_values = {
            field: getattr(order, field)
            for field in INSTALLMENT_FIELDS
        }
        accessory_total = sum(
            line.quantity * line.amount
            for line in order.accessories.all()
        )
        other_fee_total = sum(
            line.amount
            for line in order.other_fees.all()
        )
        corrected_calculated = (
            order.vehicle_price
            + order.plate_insurance_fee
            + other_fee_total
            + order.old_vehicle_tax
            + accessory_total
            - order.deposit_amount
            - order.old_vehicle_valuation
        )
        corrected_actual = (
            corrected_calculated
            if old_actual == old_calculated
            else old_actual
        )

        order.installment_company = ""
        order.installment_amount = Decimal("0")
        order.installment_periods = 0
        order.installment_opening_fee = Decimal("0")
        order.installment_monthly = Decimal("0")
        order.installment_applied_on = None
        order.installment_status = ""
        order.installment_decided_on = None
        order.calculated_balance = corrected_calculated
        order.actual_balance = corrected_actual
        order.revision += 1
        order.save(
            update_fields=[
                *INSTALLMENT_FIELDS,
                "calculated_balance",
                "actual_balance",
                "revision",
                "updated_at",
            ]
        )

        changes = {}
        labels = {
            "installment_company": "分期公司",
            "installment_amount": "分期申請金額",
            "installment_periods": "分期期數",
            "installment_opening_fee": "分期開辦費",
            "installment_monthly": "每期金額",
            "installment_applied_on": "分期申請日期",
            "installment_status": "分期狀態",
            "installment_decided_on": "核准／拒絕日期",
        }
        for field, before in old_values.items():
            after = getattr(order, field)
            if before != after:
                changes[labels[field]] = {
                    "before": str(before or ""),
                    "after": str(after or ""),
                }
        if old_calculated != corrected_calculated:
            changes["系統試算尾款"] = {
                "before": str(old_calculated),
                "after": str(corrected_calculated),
            }
        if old_actual != corrected_actual:
            changes["實際尾款"] = {
                "before": str(old_actual),
                "after": str(corrected_actual),
            }

        reason = "系統修正：非分期訂單不應保留分期資料"
        OrderChange.objects.create(
            order=order,
            reason=reason,
            changes=changes,
            actor_name="系統",
        )
        OrderEvent.objects.create(
            order=order,
            event_type="system_corrected",
            description=reason,
            actor_name="系統",
        )


class Migration(migrations.Migration):
    dependencies = [("sales", "0013_registration_fee_calculator")]

    operations = [
        migrations.RunPython(
            clear_non_installment_details,
            reverse_code=migrations.RunPython.noop,
        )
    ]
