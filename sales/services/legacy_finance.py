"""歷史財務映射與獨立核對，不改寫付款確認或套用現行主檔。"""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from sales.models import OrderOperationsProfile

BASE_MAPPING = {
    "vehicle_cost": "成本",
    "registration_tax_expense": "領牌稅金支出",
    "compulsory_insurance_expense": "強制險支出",
    "plate_selection_expense": "選號支出",
    "dealer_commission_expense": "車行傭金支出",
    "registration_tax_income": "領牌稅金收入",
    "compulsory_insurance_income": "強制險收入",
    "agency_fee_income": "代辦費收入",
    "plate_selection_income": "選號收入",
    "sales_bonus": "實銷獎勵金",
    "promotion_subsidy": "促銷補助金",
    "installment_interest_subsidy": "分期補貼息",
    "insurance_commission": "強制險傭金",
    "credit_card_commission": "信用卡傭金",
}
MAPPING = {
    **BASE_MAPPING,
    "actual_disbursement": "收款價",
    "legacy_card_fee_expense": "信用卡手續費支出",
    "installment_fee_expense": "分期手續費支出",
    "used_vehicle_expense": "中古車支出",
    "gift_shipping_expense": "贈品、運費支出",
    "friendly_dealer_bonus_expense": "友善車行獎金支出",
    "first_sale_bonus_expense": "首賣獎金支出",
    "volume_bonus_expense": "台數獎金支出",
    "used_vehicle_income": "中古車收入",
    "scrap_agency_income": "報廢代辦收入",
    "scrap_vehicle_income": "報廢車收入",
    "card_installment_fee_income": "刷卡、分期手續費收入",
    "yamaha_bonus_income": "山葉獎金收入",
    "friendly_dealer_bonus_income": "友善車行獎金收入",
    "other_income": "其他收入",
}
BONUS_EXPENSES = ("friendly_dealer_bonus_expense", "first_sale_bonus_expense", "volume_bonus_expense")
FINANCIAL_FIELDS = tuple(dict.fromkeys((
    "actual_disbursement", "vehicle_cost", *OrderOperationsProfile.EXPENSE_FIELDS,
    *OrderOperationsProfile.INCOME_FIELDS, *OrderOperationsProfile.INCENTIVE_FIELDS,
)))


def source_decimal(value):
    if value is None or str(value).strip() in ("", "-"):
        return Decimal("0")
    try:
        result = Decimal(str(value).strip().replace(",", "").replace("$", ""))
        if not result.is_finite() or abs(result) >= Decimal("1000000000000"):
            raise ValueError("金額超出範圍")
        return result.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("來源金額不是有效數字") from exc


def reconcile_source(raw):
    """只接受已核對的兩種來源公式；不使用淨利倒推任何收支。"""
    try:
        values = {field: source_decimal(raw.get(label)) for field, label in MAPPING.items()}
        if raw.get("收款價") in (None, "") or raw.get("成本") in (None, ""):
            return {"status": "missing", "reason": "缺少收款價或成本"}, {}
        reference = raw.get("單筆淨利")
        if reference in (None, ""):
            return {"status": "missing", "reason": "缺少原 Excel 單筆淨利，尚未核對"}, values
        reference = source_decimal(reference)
        for scope in ("L:V", "L:S"):
            candidate = dict(values)
            if scope == "L:S":
                candidate.update(dict.fromkeys(BONUS_EXPENSES, Decimal("0")))
            calculated = OrderOperationsProfile(**candidate).net_profit
            delta = calculated - reference
            if abs(delta) <= Decimal("0.0001"):
                return {"status": "matched", "expense_scope": scope,
                        "source_profit": str(reference), "calculated_profit": str(calculated),
                        "difference": str(delta), "values": {k: str(v) for k, v in candidate.items()}}, candidate
        return {"status": "mismatch", "reason": "來源收支與原 Excel 淨利不一致",
                "source_profit": str(reference), "calculated_profit": str(OrderOperationsProfile(**values).net_profit),
                "difference": str(OrderOperationsProfile(**values).net_profit - reference)}, {}
    except ValueError as exc:
        return {"status": "invalid", "reason": str(exc)}, {}


def import_financials(profile, raw):
    reconciliation, values = reconcile_source(raw)
    for field, value in values.items():
        setattr(profile, field, value)
    profile.legacy_finance_reconciliation = reconciliation


def repair_plan(snapshot):
    profile = getattr(snapshot.order, "operations", None)
    if profile is None:
        return {"order_id": snapshot.order_id, "status": "missing_profile"}
    reconciliation, values = reconcile_source(snapshot.raw_financials)
    before = {field: str(getattr(profile, field)) for field in FINANCIAL_FIELDS}
    result = {"order_id": snapshot.order_id, "source_row": snapshot.import_row.source_row,
              "batch_id": str(snapshot.import_row.batch_id), "before": before,
              "reconciliation": reconciliation, "after": {k: str(v) for k, v in values.items()},
              "revision": snapshot.order.revision, "profile_updated_at": profile.updated_at.isoformat(),
              "source": {label: snapshot.raw_financials.get(label) for label in (*MAPPING.values(), "單筆淨利")}}
    if profile.legacy_finance_reconciliation.get("status") in ("matched", "reviewed"):
        result["status"] = "already_reconciled"
    elif reconciliation["status"] != "matched":
        result["status"] = reconciliation["status"]
    elif (profile.manual_financial_fields or profile.vehicle_cost_manual
          or profile.payment_disbursement_snapshot or profile.vehicle_cost_rule_id or profile.incentive_rule_id
          or profile.vehicle_cost_locked_at or profile.incentive_locked_at or profile.dealer_commission_locked_at
          or snapshot.order.changes.exists() or snapshot.order.revision > 1
          or snapshot.order.status != snapshot.order.Status.COMPLETED):
        result["status"] = "preserved_changes"
    else:
        # 舊匯入器僅寫入 BASE_MAPPING；其他財務欄位非零即視為已調整。
        baseline = {field: source_decimal(snapshot.raw_financials.get(label)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
                    for field, label in BASE_MAPPING.items()}
        result["status"] = "ready" if all(
            getattr(profile, field) == baseline.get(field, Decimal("0")) for field in FINANCIAL_FIELDS
        ) else "preserved_changes"
    return result
