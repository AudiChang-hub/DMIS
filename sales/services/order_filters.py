"""營運指標、查單與舊匯出共用的明細條件。"""
from django.core.exceptions import SuspiciousOperation
from django.db.models import Case, DateField, F, Q, When
from django.utils.dateparse import parse_date

from sales.models import VehicleModel, registration_confirmed_q
from .sales_metrics import CANCELLED_STATUSES, filter_payment_risk

FILTER_KEYS = ("risk", "date_basis", "date_from", "date_to", "energy_type", "payment_status", "registered", "business_only", "include_cancelled", "attention", "drafts")


def plate_fee_variance_q():
    """牌險差異：0 < 牌險費 < 試算合計（T-168，使用者 2026-11-13 選 A）。

    填 0（不向客人收）與收得比試算高（照通路價收）都不算。全部訂單 attention=fees 與訂單頁「牌險差異」卡共用。
    """
    return Q(registration_calculated_total__gt=0, plate_insurance_fee__gt=0,
             plate_insurance_fee__lt=F("registration_calculated_total"))


def new_order_date():
    """新成立訂單的歸屬日（T-271，使用者 2026-11-21 選 A）：口徑只寫在 BUSINESS_RULES「營運總表顯示門檻」。

    實際領牌日（已確認）早於成立日的補登單用領牌日，其他用成立日；只算查詢，不改 established_on。
    """
    return Case(When(registration_confirmed_q() & Q(registration_date__lt=F("established_on")), then=F("registration_date")),
                default=F("established_on"), output_field=DateField())


def new_orders_between(rows, start, end):
    """營運總表「新成立訂單」：歸屬日落在期間內、排除取消／退款。"""
    return (rows.exclude(status__in=CANCELLED_STATUSES).alias(new_order_on=new_order_date())
            .filter(new_order_on__range=(start, end)))


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
    # 領牌（T-233，使用者 2026-11-18）：沿用 registration_confirmed_q，按過確認完成且有領牌日才算已領牌；
    # 只填預計日的單算未領牌。日期起訖依實際領牌日期，所以「未領牌」加日期範圍不會有結果。
    if params.get("registered") == "yes":
        rows = rows.filter(registration_confirmed_q())
    elif params.get("registered") == "no":
        rows = rows.exclude(registration_confirmed_q())
    field = {"order": "order_date", "established": "established_on", "delivery": "delivered_at__date",
             "new_order": "new_order_on"}.get(params.get("date_basis"), "registration_date")
    if field == "new_order_on":
        rows = rows.alias(new_order_on=new_order_date())
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
    elif params.get("attention") == "stuck":
        # 營運總表「流程卡關訂單」（T-275）：四站各自超過門檻的單一起列，判斷與卡片共用 is_stuck。
        from .operations_cockpit import stuck_order_ids
        rows = rows.filter(pk__in=stuck_order_ids())
    return rows


# T-233（使用者 2026-11-18）：全部訂單畫面只留日期起訖、能源別、收款確認；以下四項不在畫面上，
# 但營運總表等連結帶來的網址參數照舊有效，篩選表單以隱藏欄位帶著走，並在已套用條件列顯示名稱。
# 預設值（實際領牌日期、包含取消／退款）不算條件。
HIDDEN_FILTERS = {
    "date_basis": ("日期依據", {"established": "訂單成立日期", "order": "訂單版本日期", "delivery": "實際交付日期",
                               "new_order": "訂單成立日期（補登依領牌日）"}),
    "risk": ("收款風險", {"outstanding": "待收款", "unconfirmed": "已有收款待確認", "refund": "取消待退款",
                         "overpaid": "溢收待退", "stale_allocation": "配車保留逾期",
                         "unsettled_delivered": "交車後未結清"}),
    "attention": ("作業提醒", {"dealer": "車行到期提醒", "fees": "牌險金額差異待確認", "stuck": "流程卡關"}),
    "business_only": ("成交範圍", {"1": "排除取消／退款"}),
}


def analysis_filter_context(params):
    selected = [(key, params[key]) for key in FILTER_KEYS if params.get(key)]
    hidden = [(key, params[key], f"{name}「{values[params[key]]}」")
              for key, (name, values) in HIDDEN_FILTERS.items() if params.get(key) in values]
    return {"analysis_filters": selected, "has_analysis_filters": bool(selected), "hidden_filters": hidden,
            "energy_types": VehicleModel.EnergyType.choices}
