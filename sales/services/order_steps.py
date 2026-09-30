"""訂單工作台步驟：依作業順序整理狀態與摘要，目前步驟由既有下一步建議決定。"""
from decimal import Decimal

ZERO = Decimal("0")

STEP_ORDER = ("order", "deposit", "documents", "allocation", "registration", "finance", "delivery")
EXTRA_STEPS = ("subsidy", "closing")

# 下一步建議（order_next_actions）對應到工作台步驟。
ACTION_STEP = {
    "receive-order": "order", "complete-order": "order",
    "allocation": "allocation", "inventory-entry": "allocation", "vehicle-condition": "allocation",
    "stale-allocation": "allocation",
    "registration": "registration", "settlement-cost": "registration",
    "delivery": "delivery", "documents": "documents",
    "reconciliation": "finance", "settlement-gap": "finance",
    "subsidy": "subsidy", "refund": "closing",
}
# 舊網址 ?tab= 與各功能導回的參數。
TAB_STEP = {
    "order": "order", "deposit": "deposit", "documents": "documents", "allocation": "allocation",
    "registration": "registration", "finance": "finance", "delivery": "delivery", "subsidy": "subsidy",
    "closing": "closing", "history": "history",
}

STATE_LABELS = {"done": "已完成", "current": "目前步驟", "todo": "待處理", "optional": "隨時可填", "locked": "尚未開放"}


def _document_summary(order, document):
    from sales.services.document_signing import document_state
    return {"electronic": "已電子簽署", "paper": "已上傳", "stale": "需重簽", "missing": "未簽署"}[
        document_state(order, document)
    ]


def _money(value):
    return f"{(value or ZERO):,.0f}"


def _deposit(order):
    record = next((p for p in order.payment_records.all() if p.system_key == "deposit"), None)
    expected = order.deposit_amount or ZERO
    received = record.received_amount if record and record.confirmed else ZERO
    return record, expected, received


def build_order_steps(order, *, next_actions=None, requested=None, summary=None):
    from .payment_summary import payment_summary

    summary = summary or payment_summary(order)
    record, expected, received = _deposit(order)
    accessories = list(order.accessories.all())
    steps = {
        "order": dict(
            number=1, title="訂車與配件", state="done",
            summary=f"{order.get_payment_type_display()}・車價 {_money(order.vehicle_price)}"
                    + (f"・配件 {len(accessories)} 項" if accessories else "・無配件"),
        ),
        "deposit": dict(
            number=2, title="訂金",
            state="done" if expected <= 0 or (received >= expected) else "todo",
            summary=("未約定訂金" if expected <= 0 else
                     f"約定 {_money(expected)}・" + (f"已收 {_money(received)}" if received else "尚未確認收款")),
        ),
        "documents": dict(
            number=3, title="列印與簽署文件",
            state="done" if order.has_signed_contract and order.has_privacy_consent else "todo",
            summary="訂購單" + _document_summary(order, "contract")
                    + "・個資同意書" + _document_summary(order, "privacy"),
        ),
        "allocation": dict(
            number=4, title="配車",
            state="done" if order.allocated_vehicle_id or order.is_delivered else "todo",
            summary=(str(order.allocated_vehicle.identifier) if order.allocated_vehicle_id
                     else "已交付" if order.is_delivered else "有車配車，沒車先進車"),
        ),
        "registration": dict(
            number=5, title="領牌",
            state="done" if order.is_registration_complete else ("todo" if order.allocated_vehicle_id else "locked"),
            summary=(f"{order.final_plate_number}・{order.registration_date:%Y/%m/%d}"
                     if order.is_registration_complete and order.registration_date else
                     "配車後開放" if not order.allocated_vehicle_id else
                     "合作車行可交車後補" if order.source_type == "dealer" else "填寫領牌資料與文件"),
        ),
        "finance": dict(
            number=6, title="收入與支出", state="optional",
            summary=f"客戶應收 {_money(summary['customer_expected'])}・已收 {_money(summary['customer_received'])}"
                    + (f"・尚欠 {_money(summary['customer_due'])}" if summary["customer_due"] else ""),
        ),
        "delivery": dict(
            number=7, title="交車與收尾款",
            state="done" if order.is_delivered else ("todo" if order.allocated_vehicle_id else "locked"),
            summary=(f"{order.delivered_at:%Y/%m/%d} 已交付" if order.is_delivered and order.delivered_at else
                     "已交付" if order.is_delivered else "收尾款並完成交車"),
        ),
        "subsidy": dict(
            number=None, title="汰舊補助",
            state=("optional" if not order.is_trade_in_subsidy else "done" if order.is_subsidy_ready else "todo"),
            summary="未申請（需要時可開啟）" if not order.is_trade_in_subsidy else
                    "資料已齊" if order.is_subsidy_ready else "補助資料待補",
        ),
        "closing": dict(
            number=None, title="取消與結案", state="optional",
            summary=order.get_status_display() if order.is_cancelled_sale else "客戶不再購車時由此處理",
        ),
    }
    current = None
    if next_actions and next_actions.primary:
        current = ACTION_STEP.get(next_actions.primary.key)
    if order.is_cancelled_sale:
        current = "closing"
    if current and steps[current]["state"] in {"todo", "optional"}:
        steps[current]["state"] = "current"
    for key, step in steps.items():
        step["key"] = key
        step["state_label"] = STATE_LABELS[step["state"]]
    open_step = TAB_STEP.get(requested or "") or current
    return {
        "steps": steps,
        "step_list": [steps[key] for key in STEP_ORDER],
        "current_step": current,
        "open_step": open_step,
    }
