"""營運指標、查單與舊匯出共用的明細條件。"""
from django.core.exceptions import SuspiciousOperation
from django.db.models import F, Q
from django.utils.dateparse import parse_date

from sales.models import VehicleModel, registration_confirmed_q
from .sales_metrics import CANCELLED_STATUSES, filter_payment_risk

FILTER_KEYS = ("risk", "date_basis", "date_from", "date_to", "energy_type", "payment_status", "business_only", "include_cancelled", "attention", "drafts")


def plate_fee_variance_q():
    """牌險差異：0 < 牌險費 < 試算合計（T-168，使用者 2026-11-13 選 A）。

    填 0（不向客人收）與收得比試算高（照通路價收）都不算。全部訂單 attention=fees 與訂單頁「牌險差異」卡共用。
    """
    return Q(registration_calculated_total__gt=0, plate_insurance_fee__gt=0,
             plate_insurance_fee__lt=F("registration_calculated_total"))


def fee_variance_orders(rows):
    # 牌險差異只看已確認領牌的單；確認前的試算會隨預計日變動（T-172 A′）。
    return (rows.filter(plate_fee_variance_q(), registration_confirmed_q())
        .exclude(status__in=CANCELLED_STATUSES)
        .exclude(registration_fee_variance_confirmed_calculated_total=F("registration_calculated_total"),
                 registration_fee_variance_confirmed_actual_total=F("plate_insurance_fee")))


def filter_order_analysis(rows, params, *, business_default=False):
    status = params.get("status")
    groups = {
        "registration_pending": ["allocated"],
        "urgent": ["cancel_refund_pending", "delivered_docs_pending"],
    }
    if status == "deletion_pending":
        rows = rows.filter(deletion_requested_at__isnull=False)
    elif status in groups:
        rows = rows.filter(status__in=groups[status])
    elif status == "in_progress":
        rows = rows.exclude(status__in=["allocation_pending", "cancel_refund_pending", "delivered_docs_pending", "completed", "cancelled", "exception_closed"])
    elif status:
        rows = rows.filter(status=status)
    rows = filter_payment_risk(rows, params.get("risk", ""))
    if params.get("energy_type") in {v for v, _ in VehicleModel.EnergyType.choices}:
        rows = rows.filter(vehicle_model__energy_type=params["energy_type"])
    if params.get("payment_status") == "confirmed":
        rows = rows.filter(operations__payment_confirmed=True)
    elif params.get("payment_status") == "pending":
        # 與「風險：未收」同口徑：已取消類的單沒有待收款（使用者 2026-11-06，T-113）。
        rows = rows.exclude(operations__payment_confirmed=True).exclude(status__in=CANCELLED_STATUSES)
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
            if field == "registration_date":
                # 依領牌日篩選只算已確認領牌；預計日不算（T-172 A′）。
                rows = rows.filter(registration_confirmed_q())
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
