"""從哪來回哪去（T-291）：跨區連結帶 back_to＝來源頁的本站相對路徑（含篩選與期間），目的頁返回列回到來源。

- 來源端：白名單頁的 <main> 帶 data-link-source，ui-navigation.js 在點連結當下替通往其他頁的本站連結補 back_to。
- 目的端：_page_back.html／site_navigation 用 resolve_back_source() 驗證；只接受本站相對路徑、
  且解析後是白名單頁，標籤用白名單名稱。查不到就照原本的階層返回，沒有 back_to 時頁面完全不變。
參數名不用 from：進車／調車簽收的日期篩選、批次調整 from=costs、報表編輯 from 都已占用。
"""
from urllib.parse import urlsplit

from django.urls import Resolver404, resolve
from django.utils.http import url_has_allowed_host_and_scheme

PARAM = "back_to"
MAX_LENGTH = 2000

# 可當來源的頁面（url_name → 返回列名稱）。同一份清單決定哪些頁的連結會帶來源、目的頁顯示什麼名稱。
SOURCE_LABELS = {
    "dashboard": "首頁",
    "operations_report": "營運總表",
    "operations_dealer_credit": "車行未付",
    "manufacturer_advance_list": "原廠代墊／代轉",
    "manufacturer_advance_campaign_list": "代墊／代轉活動",
    "inventory_shortage": "缺貨風險車型",
    "reconciliation_list": "統一撥款對帳",
    "report_center": "報表中心",
    "report_display": "報表",
    "order_list": "全部訂單",
    "order_detail": "訂單",
    "notification_list": "我的通知",
    "dealer_payout_list": "車行傭金／獎金給付",
    "data_maintenance": "資料維護區",
    "inventory_list": "車輛庫存",
    "inventory_receipt_list": "進車紀錄",
    "transfer_signoff_list": "調車紀錄",
    "customer_list": "客戶查詢",
    "customer_detail": "客戶資料",
    "vehicle_brand_list": "車輛品牌",
    "vehicle_model_list": "機種與售價",
    "accessory_product_list": "配件與工資",
    "dealer_reward_catalog_list": "車行獎勵品項",
    "sales_source_list": "通路與人員",
    "price_list_distribution": "價格表分發",
    "gift_distribution": "年節送禮分發",
    "settlement_cost_rule_list": "車輛結算成本",
    "incentive_rule_list": "原廠獎勵與補助",
    "dealer_sales_program_list": "車行傭金與銷售獎勵",
    "dealer_volume_bonus_list": "車行台數獎金",
    "installment_company_list": "分期公司",
    "subsidy_program_list": "補助方案",
}


def _route_name(request):
    match = getattr(request, "resolver_match", None)
    return match.url_name if match else ""


def is_link_source(request):
    return _route_name(request) in SOURCE_LABELS


def resolve_back_source(request):
    """回傳 {"url", "label", "path"}；back_to 不合法、不是白名單頁或就是本頁時回 None。"""
    if request is None:
        return None
    target = request.GET.get(PARAM) or ""
    if not target or len(target) > MAX_LENGTH or not target.startswith("/") or target.startswith("//"):
        return None
    if "\\" in target or any(ord(char) < 32 for char in target):
        return None
    if not url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return None
    parts = urlsplit(target)
    if parts.scheme or parts.netloc:
        return None
    try:
        match = resolve(parts.path)
    except Resolver404:
        return None
    label = SOURCE_LABELS.get(match.url_name)
    if not label or parts.path == request.path:
        return None
    url = parts.path + (f"?{parts.query}" if parts.query else "")
    return {"url": url, "label": label, "path": parts.path}
