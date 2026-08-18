from decimal import Decimal, ROUND_HALF_UP

from django.db.models import Q
from django.utils import timezone

from sales.models import (
    InstallmentPlanOption,
    InstallmentPlanVersion,
    OrderOperationsProfile,
    SalesOrder,
)


def resolve_installment_plan_version(vehicle_model_id, order_date):
    if not vehicle_model_id or not order_date:
        return None
    return (
        InstallmentPlanVersion.objects.filter(
            vehicle_model_id=vehicle_model_id,
            active=True,
            effective_from__lte=order_date,
        )
        .filter(Q(effective_to__isnull=True) | Q(effective_to__gte=order_date))
        .order_by("-effective_from", "-id")
        .first()
    )


def resolve_installment_plan_option(vehicle_model_id, order_date, periods):
    version = resolve_installment_plan_version(vehicle_model_id, order_date)
    if not version or not periods:
        return None
    return version.options.select_related("company").filter(periods=periods).first()


def calculate_expected_disbursement(option, vehicle_price):
    if not option:
        return None
    method = option.expected_disbursement_method
    if method == InstallmentPlanOption.ExpectedDisbursementMethod.RATE:
        if option.expected_disbursement_rate is None or vehicle_price is None:
            return None
        return (
            Decimal(vehicle_price)
            * option.expected_disbursement_rate
            / Decimal("100")
        ).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    if method == InstallmentPlanOption.ExpectedDisbursementMethod.FIXED:
        return option.expected_disbursement_fixed_amount
    return None


def installment_option_payload(option, vehicle_price=None):
    if not option:
        return None
    return {
        "option_id": option.pk,
        "version_id": option.version_id,
        "periods": option.periods,
        "monthly_amount": int(option.monthly_amount),
        "company_id": option.company_id,
        "company": option.company.name,
        "customer_service_phone": option.company.customer_service_phone,
        "opening_fee": int(option.opening_fee),
        "expected_disbursement_method": option.expected_disbursement_method,
        "expected_disbursement_method_label": (
            option.get_expected_disbursement_method_display()
        ),
        "expected_disbursement_rate": (
            str(option.expected_disbursement_rate)
            if option.expected_disbursement_rate is not None
            else None
        ),
        "expected_disbursement_fixed_amount": (
            int(option.expected_disbursement_fixed_amount)
            if option.expected_disbursement_fixed_amount is not None
            else None
        ),
        "expected_disbursement_amount": (
            int(calculated)
            if (
                calculated := calculate_expected_disbursement(
                    option, vehicle_price
                )
            ) is not None
            else None
        ),
        "effective_from": option.version.effective_from.isoformat(),
        "effective_to": (
            option.version.effective_to.isoformat()
            if option.version.effective_to
            else None
        ),
    }


def apply_order_installment_snapshot(order):
    if order.payment_type != SalesOrder.PaymentType.INSTALLMENT:
        order.installment_company_master = None
        order.installment_plan_option = None
        order.installment_plan_snapshot = {}
        SalesOrder.objects.filter(pk=order.pk).update(
            installment_company_master=None,
            installment_plan_option=None,
            installment_plan_snapshot={},
            updated_at=timezone.now(),
        )
        return None

    option = resolve_installment_plan_option(
        order.vehicle_model_id,
        order.order_date,
        order.installment_periods,
    )
    if not option:
        order.installment_company_master = None
        order.installment_plan_option = None
        order.installment_plan_snapshot = {
            "manual_override": True,
            "company": order.installment_company,
            "periods": order.installment_periods,
            "monthly_amount": int(order.installment_monthly or Decimal("0")),
            "opening_fee": int(order.installment_opening_fee or Decimal("0")),
            "expected_disbursement_method": "manual",
            "expected_disbursement_method_label": "本單另填",
            "expected_disbursement_amount": None,
            "captured_at": timezone.now().isoformat(),
        }
        SalesOrder.objects.filter(pk=order.pk).update(
            installment_company_master=None,
            installment_plan_option=None,
            installment_plan_snapshot=order.installment_plan_snapshot,
            updated_at=timezone.now(),
        )
        return None

    payload = installment_option_payload(option, order.vehicle_price)
    payload["manual_override"] = any(
        (
            order.installment_company != option.company.name,
            (order.installment_monthly or Decimal("0")) != option.monthly_amount,
            (order.installment_opening_fee or Decimal("0")) != option.opening_fee,
        )
    )
    payload["captured_at"] = timezone.now().isoformat()
    order.installment_company_master = option.company
    order.installment_plan_option = option
    order.installment_plan_snapshot = payload
    SalesOrder.objects.filter(pk=order.pk).update(
        installment_company_master=option.company,
        installment_plan_option=option,
        installment_plan_snapshot=payload,
        updated_at=timezone.now(),
    )
    profile, _ = OrderOperationsProfile.objects.get_or_create(order=order)
    if not payload["manual_override"] or not profile.customer_service_phone:
        profile.customer_service_phone = option.company.customer_service_phone
        profile.save(update_fields=["customer_service_phone", "updated_at"])
    return option
