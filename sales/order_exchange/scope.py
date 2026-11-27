"""匯出範圍：與全部訂單頁同口徑（帳號可見範圍、全欄位搜尋、狀態、營運條件、頁籤、排序）。

只組查詢，不改全部訂單頁本身；規則都來自同一組服務函式，篩選條件一變，兩邊一起變。
"""
from django.db.models import Prefetch
from django.http import QueryDict

from sales.models import PaymentRecord, SalesOrder

# 從全部訂單頁帶過來、會影響範圍的參數；其餘（分頁、每頁筆數）一律不帶。
SCOPE_KEYS = (
    "q", "status", "tab", "sort", "risk", "date_basis", "date_from", "date_to", "energy_type",
    "payment_status", "registered", "attention", "business_only", "include_cancelled", "txn",
)


def scope_params(source):
    params = QueryDict(mutable=True)
    for key in SCOPE_KEYS:
        value = (source.get(key) or "").strip()
        if value:
            params[key] = value
    return params


def export_queryset(request, params):
    from sales.services import order_tabs as tab_rules
    from sales.services.order_filters import filter_order_analysis
    from sales.services.order_intake import scoped_orders
    from sales.services.order_search import build_order_search_query
    from sales.services.order_sorting import default_sort, parse_sort, sort_orders
    from sales.services.profit_access import profit_is_unlocked
    from sales.views import ORDER_LIST_FILTER_KEYS

    profit_visible = profit_is_unlocked(request)
    orders = scoped_orders(request.user)
    query = params.get("q", "")
    if query:
        orders = orders.filter(build_order_search_query(query, profit_unlocked=profit_visible)).distinct()
    orders = filter_order_analysis(orders, params)
    tab = params.get("tab")
    # 「全部」只在匯出頁與舊匯出網址明確指定（舊匯出不分頁籤）；全部訂單頁的頁籤沒有這個值。
    if tab != "all" and tab not in tab_rules.TAB_KEYS:
        filtered = query or params.get("status") or any(params.get(key) for key in ORDER_LIST_FILTER_KEYS)
        tab = "all" if filtered else "open"
    if tab != "all":
        orders = orders.filter(tab_rules.tab_filter(tab))
    tokens = parse_sort(params.get("sort", ""))
    if not profit_visible:
        tokens = [token for token in tokens if token.lstrip("-") != "profit"]
    default_tokens, _label = default_sort(tab)
    orders = sort_orders(orders, tokens or default_tokens)
    orders = orders.select_related(
        "source", "commission_recipient", "vehicle_model", "color", "allocated_vehicle", "operations",
        "legacy_snapshot",
    ).prefetch_related("accessories", "other_fees", "subsidy_items",
                       Prefetch("payment_records", queryset=PaymentRecord.objects.all()))
    return orders, tab


def scope_labels(params, tab):
    """把範圍寫成人看得懂的條件（畫面與匯出紀錄共用）。"""
    from sales.services import order_tabs as tab_rules
    from sales.services.order_filters import TRANSACTION_SCOPES

    labels = []
    if params.get("q"):
        labels.append(("搜尋", params["q"]))
    tabs = {key: label for key, label, _hint in tab_rules.TABS}
    labels.append(("分類", tabs.get(tab, "全部")))
    status = params.get("status")
    if status:
        extra = {"deletion_pending": "刪除確認中", "urgent": "需要優先處理", "in_progress": "進行中",
                 "registration_pending": "待領牌（含調車）"}
        labels.append(("狀態", extra.get(status) or dict(SalesOrder.Status.choices).get(status, status)))
    if params.get("date_from") or params.get("date_to"):
        basis = {"order": "訂單版本日期", "established": "訂單成立日期", "delivery": "交車日期"}.get(
            params.get("date_basis"), "實際領牌日期")
        labels.append((basis, f"{params.get('date_from') or '不限'} ～ {params.get('date_to') or '不限'}"))
    named = {
        "risk": ("收款風險", {"outstanding": "待收款", "unconfirmed": "已有收款待確認", "refund": "取消待退款"}),
        "energy_type": ("能源別", None),
        "payment_status": ("收款確認", {"confirmed": "已確認", "pending": "待確認"}),
        "registered": ("領牌", {"yes": "已領牌", "no": "未領牌"}),
        "attention": ("作業提醒", {"dealer": "車行到期提醒", "fees": "牌險金額差異待確認"}),
        "business_only": ("成交範圍", {"1": "排除取消／退款", "0": "包含取消／退款"}),
        "txn": ("交易類型", {key: label for key, (label, _q) in TRANSACTION_SCOPES.items()}),
    }
    for key, (label, mapping) in named.items():
        value = params.get(key)
        if value:
            if key == "energy_type":
                from sales.models import VehicleModel
                text = dict(VehicleModel.EnergyType.choices).get(value, value)
            else:
                text = (mapping or {}).get(value, value)
            labels.append((label, text))
    return labels
