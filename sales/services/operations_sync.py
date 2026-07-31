from decimal import Decimal

from django.db import transaction
from django.db.models import Sum


def _money(value):
    return value or Decimal("0")


def _sync_financial_field(profile, field_name, value):
    if field_name not in (profile.manual_financial_fields or []):
        setattr(profile, field_name, _money(value))


def _upsert_system_payment(order, key, defaults):
    from sales.models import PaymentRecord

    payment, created = PaymentRecord.objects.get_or_create(
        order=order,
        system_key=key,
        defaults=defaults,
    )
    if created:
        return payment
    protected = payment.confirmed or payment.received_amount or payment.proof
    for field in ("item_name", "expected_amount"):
        setattr(payment, field, defaults[field])
    if key == "deposit" and not protected:
        for field in (
            "received_amount",
            "received_on",
            "payment_method",
        ):
            setattr(payment, field, defaults[field])
    payment.save()
    return payment


def refresh_payment_confirmation(order_id):
    from sales.models import OrderOperationsProfile, PaymentRecord

    profile = OrderOperationsProfile.objects.filter(order_id=order_id).first()
    if not profile:
        return
    records = PaymentRecord.objects.filter(order_id=order_id)
    expected = records.aggregate(total=Sum("expected_amount"))["total"] or Decimal("0")
    received = records.filter(confirmed=True).aggregate(
        total=Sum("received_amount")
    )["total"] or Decimal("0")
    confirmed = bool(records.exists() and expected > 0 and received >= expected)
    installment_confirmed = records.filter(
        system_key="installment_disbursement",
        confirmed=True,
    ).exists()
    updates = []
    if profile.payment_confirmed != confirmed:
        profile.payment_confirmed = confirmed
        updates.append("payment_confirmed")
    if profile.installment_transfer_confirmed != installment_confirmed:
        profile.installment_transfer_confirmed = installment_confirmed
        updates.append("installment_transfer_confirmed")
    if updates:
        profile.save(update_fields=[*updates, "updated_at"])


@transaction.atomic
def sync_order_operations(order_id):
    from sales.models import OrderOperationsProfile, PaymentRecord, SalesOrder

    order = (
        SalesOrder.objects.select_related(
            "source",
            "allocated_vehicle",
        )
        .filter(pk=order_id)
        .first()
    )
    if not order:
        return None
    profile, _created = OrderOperationsProfile.objects.get_or_create(order=order)
    profile.dealer_name = order.source.name if order.source_id else ""
    if (
        order.source_type != order.SourceType.PLATFORM
        and order.payment_type == order.PaymentType.CASH
        and "actual_disbursement" not in (profile.manual_financial_fields or [])
    ):
        profile.actual_disbursement = _money(order.vehicle_price)
    registration_tax_expense = sum(
        (
            _money(order.registration_plate_fee),
            _money(order.registration_license_fee),
            _money(order.registration_inspection_fee),
            _money(order.road_maintenance_fee),
            _money(order.license_tax_fee),
        ),
        Decimal("0"),
    )
    registration_tax_income = max(
        _money(order.plate_insurance_fee)
        - _money(order.compulsory_insurance_fee)
        - _money(order.plate_selection_fee),
        Decimal("0"),
    )
    _sync_financial_field(
        profile,
        "registration_tax_expense",
        registration_tax_expense,
    )
    _sync_financial_field(
        profile,
        "compulsory_insurance_expense",
        order.compulsory_insurance_fee,
    )
    _sync_financial_field(
        profile,
        "plate_selection_expense",
        order.plate_selection_fee,
    )
    _sync_financial_field(
        profile,
        "registration_tax_income",
        registration_tax_income,
    )
    _sync_financial_field(
        profile,
        "compulsory_insurance_income",
        order.compulsory_insurance_fee,
    )
    _sync_financial_field(
        profile,
        "plate_selection_income",
        order.plate_selection_fee,
    )
    profile.installment_fee_income = (
        _money(order.installment_opening_fee)
        if order.payment_type == SalesOrder.PaymentType.INSTALLMENT
        else Decimal("0")
    )
    profile.installment_info = (
        f"{order.installment_company}／{order.installment_periods}期／"
        f"每期 {order.installment_monthly:.0f} 元"
        if order.payment_type == SalesOrder.PaymentType.INSTALLMENT
        else ""
    )
    profile.save()

    active_keys = {"deposit"}
    _upsert_system_payment(
        order,
        "deposit",
        {
            "item_name": "訂金",
            "expected_amount": _money(order.deposit_amount),
            "received_amount": _money(order.deposit_amount),
            "received_on": order.deposit_date,
            "payment_method": order.get_deposit_method_display()
            if order.deposit_method
            else "",
        },
    )

    if order.payment_type == SalesOrder.PaymentType.INSTALLMENT:
        financed = _money(order.installment_amount)
        cash_due = max(_money(order.actual_balance) - financed, Decimal("0"))
        active_keys.update({"installment_disbursement", "balance"})
        _upsert_system_payment(
            order,
            "installment_disbursement",
            {
                "item_name": "分期公司撥款",
                "expected_amount": financed,
                "received_amount": Decimal("0"),
                "received_on": None,
                "payment_method": "分期撥款",
            },
        )
        balance_label = "分期外應收"
    else:
        cash_due = _money(order.actual_balance)
        active_keys.add("balance")
        balance_label = "尾款"
    _upsert_system_payment(
        order,
        "balance",
        {
            "item_name": balance_label,
            "expected_amount": cash_due,
            "received_amount": Decimal("0"),
            "received_on": None,
            "payment_method": order.get_payment_type_display(),
        },
    )

    stale = PaymentRecord.objects.filter(order=order).exclude(system_key="")
    stale = stale.exclude(system_key__in=active_keys)
    for payment in stale:
        if not payment.confirmed and not payment.received_amount and not payment.proof:
            payment.delete()
        else:
            payment.system_key = ""
            payment.note = (
                f"{payment.note}；" if payment.note else ""
            ) + "付款方式已變更，已保留為人工收款紀錄"
            payment.save(update_fields=["system_key", "note", "updated_at"])

    refresh_payment_confirmation(order.pk)
    return profile
