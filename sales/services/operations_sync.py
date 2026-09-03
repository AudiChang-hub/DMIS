from decimal import Decimal

from django.db import transaction
from django.db.models import Sum


def _money(value):
    return value or Decimal("0")


def _sync_financial_field(profile, field_name, value):
    if field_name not in (profile.manual_financial_fields or []):
        setattr(profile, field_name, _money(value))


def _expected_installment_disbursement(order):
    snapshot = order.installment_plan_snapshot or {}
    if "expected_disbursement_method" not in snapshot:
        return _money(order.installment_amount)
    amount = snapshot.get("expected_disbursement_amount")
    return Decimal(str(amount)) if amount is not None else Decimal("0")


def _upsert_system_payment(order, key, defaults, *, update_receivables=False):
    from sales.models import PaymentRecord

    payment, created = PaymentRecord.objects.get_or_create(
        order=order,
        system_key=key,
        defaults=defaults,
    )
    if created:
        return payment
    before = {name: getattr(payment, name) for name in defaults}
    protected = payment.confirmed or payment.received_amount or payment.proof
    payment.item_name = defaults["item_name"]
    if (not protected or update_receivables) and not payment.expected_amount_overridden:
        payment.expected_amount = defaults["expected_amount"]
    if key == "deposit" and not protected:
        for field in (
            "received_amount",
            "received_on",
            "payment_method",
        ):
            setattr(payment, field, defaults[field])
    changed = [name for name in defaults if getattr(payment, name) != before[name]]
    if changed:
        payment.save(update_fields=[*changed, "updated_at"])
    return payment


def refresh_payment_confirmation(order_id):
    from sales.models import OrderOperationsProfile, PaymentRecord

    profile = OrderOperationsProfile.objects.filter(order_id=order_id).first()
    if not profile:
        return
    records = PaymentRecord.objects.filter(order_id=order_id)
    expected = records.aggregate(total=Sum("expected_amount"))["total"] or Decimal("0")
    # 某筆溢收不能抵掉另一筆尚未收清的款項。
    confirmed = bool(records.exists() and expected > 0 and all(
        record.is_settled for record in records
    ))
    installment_record = records.filter(
        system_key="installment_disbursement",
    ).first()
    # 匯款已確認不等於所有款項已收清；短款仍由 payment_confirmed／應收差額呈現。
    installment_confirmed = bool(installment_record and installment_record.confirmed)
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
def sync_payment_financials(order_id, *, adopt_payment_id=None, touch_revision=False):
    """所有收款入口共用；原始收款紀錄與營運財務在同一交易更新。"""
    from sales.models import OrderOperationsProfile, SalesOrder

    order = SalesOrder.objects.select_for_update().filter(pk=order_id).first()
    if not order:
        return
    profile = OrderOperationsProfile.objects.filter(order_id=order_id).first()
    if not profile:
        return
    fields = ("card_fee_income", "card_fee_expense", "actual_disbursement",
              "payment_disbursement_snapshot", "manual_financial_fields")
    before = {name: getattr(profile, name) for name in fields}
    totals = order.payment_records.aggregate(income=Sum("card_fee_charged"), expense=Sum("bank_card_fee"))
    profile.card_fee_income = totals["income"] or Decimal("0")
    profile.card_fee_expense = totals["expense"] or Decimal("0")
    key = ("installment_disbursement" if order.payment_type == order.PaymentType.INSTALLMENT
           else "balance" if order.source_type == order.SourceType.PLATFORM else None)
    payment = order.payment_records.filter(system_key=key, confirmed=True).first() if key else None
    snapshot = dict(profile.payment_disbursement_snapshot or {})
    protected = set(profile.manual_financial_fields or [])
    if payment and (snapshot or payment.pk == adopt_payment_id):
        if not snapshot:
            snapshot = {"previous": str(profile.actual_disbursement),
                        "was_manual": "actual_disbursement" in protected}
        profile.actual_disbursement = payment.received_amount
        protected.add("actual_disbursement")
        snapshot.update(payment_id=payment.pk, applied=str(payment.received_amount))
    elif not payment and snapshot:
        # 只撤回由收款管理的金額，不覆寫之後另行人工輸入的金額。
        if profile.actual_disbursement == Decimal(snapshot["applied"]):
            if snapshot["was_manual"]:
                profile.actual_disbursement = Decimal(snapshot["previous"])
            else:
                from .incentive_rule import _calculated_disbursement
                profile.actual_disbursement = _calculated_disbursement(order) or Decimal("0")
                protected.discard("actual_disbursement")
        snapshot = {}
    profile.payment_disbursement_snapshot = snapshot
    profile.manual_financial_fields = sorted(protected)
    changed = [name for name in fields if getattr(profile, name) != before[name]]
    # 明細變更即使未改變合計，也須使其他人已開啟的營運表單失效。
    if changed or touch_revision:
        profile.save(update_fields=[*changed, "updated_at"])
    refresh_payment_confirmation(order_id)


@transaction.atomic
def sync_order_operations(order_id, *, update_receivables=False):
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
    profile_before = {field.attname: field.value_from_object(profile) for field in profile._meta.concrete_fields}
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
    changed = [name for name, value in profile_before.items() if getattr(profile, name) != value]
    if changed:
        profile.save(update_fields=[*changed, "updated_at"])

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
        update_receivables=update_receivables,
    )

    if order.payment_type == SalesOrder.PaymentType.INSTALLMENT:
        financed = _money(order.installment_amount)
        expected_disbursement = _expected_installment_disbursement(order)
        extra_bonus = Decimal(
            str(
                (order.installment_plan_snapshot or {}).get(
                    "extra_disbursement_bonus"
                )
                or 0
            )
        )
        cash_due = max(_money(order.actual_balance) - financed, Decimal("0"))
        active_keys.update({"installment_disbursement", "balance"})
        _upsert_system_payment(
            order,
            "installment_disbursement",
            {
                "item_name": (
                    f"分期公司撥款（含額外獎金 {extra_bonus:.0f} 元）"
                    if extra_bonus > 0
                    else "分期公司撥款"
                ),
                "expected_amount": expected_disbursement,
                "received_amount": Decimal("0"),
                "received_on": None,
                "payment_method": "分期撥款",
            },
            update_receivables=update_receivables,
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
        update_receivables=update_receivables,
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
