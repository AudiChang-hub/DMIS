"""清單的「啟用中／已停用」狀態頁籤（T-209，比照「機種與售價」）。

- 網址參數預設 `status=active|inactive`，其他值一律當成啟用中。
- 頁籤筆數是這一頁的全部資料（不套搜尋與其他篩選），與機種與售價相同。
- 切換頁籤保留其他條件，去掉頁碼與 edit／new／saved 這類一次性參數。
- 畫面用 `templates/sales/_status_tabs.html`；清單外層加 `data-status-tab`，
  Switch 停用後由 `active-quick-toggle.js` 提示「重新整理後移到已停用」並更新筆數。
"""
from django.db.models import Count, Q

STATUSES = ("active", "inactive")
ONE_TIME_PARAMS = ("page", "edit", "new", "saved")


def requested_status(params, param="status"):
    value = (params.get(param) or "").strip()
    return value if value in STATUSES else "active"


def queryset_status_counts(queryset, field="active"):
    totals = queryset.order_by().aggregate(
        status_active=Count("pk", filter=Q(**{field: True}), distinct=True),
        status_inactive=Count("pk", filter=Q(**{field: False}), distinct=True),
    )
    return {"active": totals["status_active"], "inactive": totals["status_inactive"]}


def item_status_counts(items, attr="active"):
    items = list(items)
    active = sum(1 for item in items if getattr(item, attr))
    return {"active": active, "inactive": len(items) - active}


def status_tabs(request, status, counts, *, param="status", drop=ONE_TIME_PARAMS, path=None):
    query = request.GET.copy()
    for key in drop:
        query.pop(key, None)
    urls = {}
    for value in STATUSES:
        query[param] = value
        urls[value] = f"{path or request.path}?{query.urlencode()}"
    return {"status": status, "param": param, "counts": counts, "urls": urls}


def keep_status(url, request, param="status"):
    """同頁編輯送出後導回原本的狀態頁籤（只有已停用需要帶參數）。"""
    if requested_status(request.GET, param) == "inactive":
        return f"{url}{'&' if '?' in url else '?'}{param}=inactive"
    return url
