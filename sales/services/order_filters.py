"""營運指標、查單與舊匯出共用的明細條件。"""
from django.core.exceptions import SuspiciousOperation
from django.db.models import F
from django.utils.dateparse import parse_date

from sales.models import VehicleModel
from .sales_metrics import CANCELLED_STATUSES, filter_payment_risk

FILTER_KEYS = ("risk", "date_basis", "date_from", "date_to", "energy_type", "payment_status", "business_only", "include_cancelled", "attention", "drafts")


def fee_variance_orders(rows):
    return (rows.filter(registration_date__isnull=False, registration_calculated_total__gt=0)
        .exclude(status__in=CANCELLED_STATUSES)
        .exclude(plate_insurance_fee=F("registration_calculated_total"))
        .exclude(registration_fee_variance_confirmed_calculated_total=F("registration_calculated_total"),
                 registration_fee_variance_confirmed_actual_total=F("plate_insurance_fee")))


def filter_order_analysis(rows, params, *, business_default=False):
    status = params.get("status")
    groups = {
        "registration_pending": ["allocated", "transfer_pending", "in_transfer"],
        "urgent": ["cancel_refund_pending", "delivered_docs_pending"],
    }
    if status == "deletion_pending":
        rows = rows.filter(deletion_requested_at__isnull=False)
    elif status in groups:
        rows = rows.filter(status__in=groups[status])
    elif status == "in_progress":
        rows = rows.exclude(status__in=["intake_pending", "allocation_pending", "cancel_refund_pending", "delivered_docs_pending", "completed", "cancelled"])
    elif status:
        rows = rows.filter(status=status)
    rows = filter_payment_risk(rows, params.get("risk", ""))
    if params.get("energy_type") in {v for v, _ in VehicleModel.EnergyType.choices}:
        rows = rows.filter(vehicle_model__energy_type=params["energy_type"])
    if params.get("payment_status") == "confirmed":
        rows = rows.filter(operations__payment_confirmed=True)
    elif params.get("payment_status") == "pending":
        rows = rows.exclude(operations__payment_confirmed=True)
    field = {"order": "order_date", "established": "established_on", "delivery": "delivered_at__date"}.get(params.get("date_basis"), "registration_date")
    dates = {}
    for key, lookup in (("date_from", "gte"), ("date_to", "lte")):
        if params.get(key):
            try:
                value = parse_date(params[key])
            except ValueError:
                value = None
            if value is None:
                raise SuspiciousOperation("日期格式不正確，請使用 YYYY-MM-DD。")
            dates[key] = value
            rows = rows.filter(**{f"{field}__{lookup}": value})
    if len(dates) == 2 and dates["date_from"] > dates["date_to"]:
        raise SuspiciousOperation("開始日期不能晚於結束日期。")
    if (business_default or params.get("business_only") == "1") and params.get("include_cancelled") != "1" and params.get("risk") != "refund":
        rows = rows.exclude(status__in=CANCELLED_STATUSES)
    if params.get("attention") == "fees":
        rows = fee_variance_orders(rows)
    elif params.get("attention") == "dealer":
        from .business_days import build_dealer_reminders
        rows = rows.filter(pk__in={item["order"].pk for item in build_dealer_reminders() if item["is_due"]})
    return rows


def analysis_filter_context(params):
    selected = [(key, params[key]) for key in FILTER_KEYS if params.get(key)]
    return {"analysis_filters": selected, "has_analysis_filters": bool(selected),
            "energy_types": VehicleModel.EnergyType.choices}
