"""訂單「收入與支出」的版面分組：只決定欄位放在哪一側、哪一組，不改任何計算。

收入合計＝實際撥款＋收入欄位＋獎勵與補助；支出合計＝車輛成本＋支出欄位；
兩者相減即為 OrderOperationsProfile.net_profit。
"""
from decimal import Decimal

from sales.models import OrderOperationsProfile

ZERO = Decimal("0")

INCOME_GROUPS = (
    ("撥款", "現金單為車價；分期單為分期公司撥款", ("actual_disbursement",)),
    ("領牌相關", "客戶支付的牌險費用", ("registration_tax_income", "compulsory_insurance_income", "plate_selection_income")),
    ("手續費與代辦", "", ("agency_fee_income", "installment_fee_income", "card_fee_income", "other_income")),
    ("中古與報廢", "", ("used_vehicle_income", "scrap_agency_income", "scrap_vehicle_income")),
    ("獎勵與補助", "依實際領牌日期套用車型版本", OrderOperationsProfile.INCENTIVE_FIELDS),
    ("歷史匯入欄位", "舊資料合併欄位，新訂單通常為 0", ("card_installment_fee_income", "yamaha_bonus_income", "friendly_dealer_bonus_income")),
)
EXPENSE_GROUPS = (
    ("車輛成本", "", ("vehicle_cost",)),
    ("領牌相關", "監理站規費、強制險與選號", ("registration_tax_expense", "compulsory_insurance_expense", "plate_selection_expense")),
    ("傭金", "", ("dealer_commission_expense",)),
    ("手續費", "", ("card_fee_expense", "installment_fee_expense")),
    ("贈品、運費與中古車", "", ("gift_expense", "shipping_expense", "used_vehicle_expense")),
    ("歷史匯入欄位", "舊資料合併欄位，新訂單通常為 0", (
        "legacy_card_fee_expense", "gift_shipping_expense", "friendly_dealer_bonus_expense",
        "first_sale_bonus_expense", "volume_bonus_expense",
    )),
)
LABELS = {
    "actual_disbursement": "實際撥款",
    "dealer_commission_expense": "傭金支出（車行／本店人員）",
    "card_fee_expense": "刷卡手續費支出",
    "legacy_card_fee_expense": "匯入信用卡手續費支出",
}
HINTS = {
    "registration_tax_income": "牌險費扣除強制險與選號",
    "registration_tax_expense": "號牌、行照、檢驗、公路養管、牌照稅",
    "plate_selection_income": "沒有選號時為 0 元",
    "plate_selection_expense": "沒有選號時為 0 元",
}
LEGACY_GROUP = "歷史匯入欄位"


def ledger_fields():
    income = [name for _title, _hint, names in INCOME_GROUPS for name in names]
    expense = [name for _title, _hint, names in EXPENSE_GROUPS for name in names]
    return income, expense


def _amount(profile, name):
    return getattr(profile, name, None) or ZERO


def _source_tag(profile, form, name, manual):
    field = form.fields.get(name)
    if field is not None and field.disabled:
        return ("synced", "自動同步")
    if name in OrderOperationsProfile.MANUAL_PROTECTABLE_FINANCIAL_FIELDS:
        if name in manual or (name == "vehicle_cost" and profile.vehicle_cost_manual):
            return ("manual", "已人工調整")
        return ("system", "系統帶入")
    return ("", "")


def _block(groups, profile, form, manual):
    rows_total = ZERO
    built = []
    for title, hint, names in groups:
        rows = []
        for name in names:
            if name not in form.fields:
                continue
            tag, tag_label = _source_tag(profile, form, name, manual)
            # 金額一律整數；即時小計由 data-ledger-input 取值。
            form.fields[name].widget.attrs.update({
                "data-ledger-input": "", "placeholder": "0", "inputmode": "numeric", "step": "1",
            })
            rows.append({
                "name": name,
                "field": form[name],
                "label": LABELS.get(name) or form.fields[name].label,
                "hint": HINTS.get(name, ""),
                "tag": tag,
                "tag_label": tag_label,
                "amount": _amount(profile, name),
            })
        if not rows:
            continue
        subtotal = sum((row["amount"] for row in rows), ZERO)
        rows_total += subtotal
        built.append({
            "title": title,
            "hint": hint,
            "rows": rows,
            "subtotal": subtotal,
            "legacy": title == LEGACY_GROUP,
            "has_value": any(row["amount"] for row in rows),
            "incentive": title == "獎勵與補助",
        })
    return {"groups": built, "total": rows_total}


def finance_totals(profile):
    """伺服器端的收入、支出合計；與 net_profit 使用同一組欄位。"""
    income_names, expense_names = ledger_fields()
    income = sum((_amount(profile, name) for name in income_names), ZERO)
    expense = sum((_amount(profile, name) for name in expense_names), ZERO)
    return {"income": income, "expense": expense, "net": income - expense}


def finance_ledger(form, profile):
    manual = set(profile.manual_financial_fields or [])
    return {
        "income": _block(INCOME_GROUPS, profile, form, manual),
        "expense": _block(EXPENSE_GROUPS, profile, form, manual),
    }
