"""首頁收藏只保存穩定代碼，連結一律由路由與當次權限產生。"""
from django.urls import reverse

from .mobile_quick_links import MOBILE_QUICK_LINK_DEFINITIONS


EXTRA_LINKS = (
    {"key": "catalog", "label": "選車下單", "route": "catalog"},
    {"key": "catalog-manage", "label": "選車展示管理", "route": "catalog_manage"},
    {"key": "orders", "label": "全部訂單", "route": "order_list"},
    {"key": "new-order", "label": "建立訂單", "route": "order_create"},
    {"key": "operations", "label": "營運總表", "route": "operations_report"},
    {"key": "reconciliation", "label": "對帳作業", "route": "reconciliation_list"},
    {"key": "help", "label": "使用說明", "route": "user_guide"},
    {"key": "imports", "label": "舊資料 Excel 匯入", "route": "legacy_import_list"},
    {"key": "diagnostics", "label": "系統狀態檢查", "route": "system_diagnostics"},
    {"key": "integrity", "label": "系統完整性報告", "route": "system_integrity_report"},
    {"key": "report-design", "label": "報表設計管理", "route": "report_manage"},
    {"key": "report-categories", "label": "報表分類設定", "route": "report_classification"},
    {"key": "announcements", "label": "系統公告管理", "route": "announcement_manage"},
)
LINKS = {item["key"]: item for item in (*MOBILE_QUICK_LINK_DEFINITIONS, *EXTRA_LINKS)}
GROUPS = (
    ("orders", "全部訂單", "查詢、建立及處理訂單", ("orders", "new-order", "catalog", "catalog-manage")),
    ("operations", "營運總表", "公司走勢與對帳", ("operations", "reconciliation")),
    ("reports", "報表中心", "分析、設計及分類", ("reports", "report-design", "report-categories")),
    ("vehicles", "資料維護・車輛與商品", "品牌、售價、庫存及配件", ("vehicle-brands", "vehicle-models", "inventory", "accessories", "dealer-reward-items")),
    ("people", "資料維護・通路與人員", "客戶、車行及工作分發", ("customers", "sales-sources", "network-platforms", "staff", "source-categories", "price-list-distribution")),
    ("rules", "資料維護・費率與規則", "成本、獎勵、分期與日曆", ("settlement-costs", "incentives", "dealer-sales-programs", "dealer-bonuses", "installment-companies", "registration-fees", "business-holidays")),
    ("tools", "資料維護・工具與管理", "匯入、列印、帳號及公告", ("imports", "print-templates", "diagnostics", "integrity", "user-management", "announcements")),
    ("help", "使用說明", "隨時查閱操作方式", ("help",)),
)
DEFAULT_KEYS = ("orders", "new-order", "operations", "reports", "help")


def favorite_context(user, preference=None, *, policy=None, selected=None):
    from sales.access.services import AccessPolicy
    policy = policy or AccessPolicy(user)
    groups, options = [], []
    for key, title, description, keys in GROUPS:
        items = [{**LINKS[k], "url": reverse("catalog" if k == "new-order" and policy.route("catalog") else LINKS[k]["route"]), "group": title}
                 for k in keys if policy.route(LINKS[k]["route"])]
        if items:
            groups.append({"key": key, "title": title, "description": description, "options": items})
            options.extend(items)
    by_key = {item["key"]: item for item in options}
    defaults = [key for key in DEFAULT_KEYS if key in by_key]
    if selected is None:
        selected = preference.home_favorites if preference else None
        if selected is None:
            # 初次啟用保留使用者曾自行設定的手機捷徑，之後獨立維護。
            selected = [*defaults, *(preference.mobile_quick_links if preference else [])]
    selected_keys = list(dict.fromkeys(key for key in selected if isinstance(key, str) and key in by_key))
    return {
        "favorite_groups": groups, "favorite_options": options,
        "favorite_keys": selected_keys, "favorite_links": [by_key[key] for key in selected_keys],
        "favorite_defaults": defaults,
        "favorite_version": preference.home_favorites_version if preference else 0,
        "favorites_customized": bool(preference and preference.home_favorites is not None),
    }
