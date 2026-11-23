"""營運總表「需要處理」的唯讀明細頁（T-275）：點進來只列卡片算到的那一批，條件與卡片共用同一函式。

- 缺貨風險車型（使用者選 A）：列車型、在庫台數、近 90 天領牌台數、可銷天數；權限同車輛庫存。
- 車行未付：列全部有未付的車行與它們的未付訂單；權限同營運總表的財務彙總。營運總表「錢」的車行未付連到這裡。
  車行額度 2026-11-23 T-288 移除，不再分「只列超額」；舊連結的 scope=all 照樣能開、內容相同。
"""
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET

from sales.services import operations_cockpit as cockpit


@login_required
@require_GET
def inventory_shortage(request):
    today = timezone.localdate()
    rows = [row for row in cockpit.model_velocity(today) if row["shortage"]]
    return render(request, "sales/inventory_shortage.html", {
        "rows": rows, "today": today, "velocity_days": cockpit.VELOCITY_DAYS,
        "min_sold": cockpit.SHORTAGE_MIN_SOLD, "cover_days": cockpit.SHORTAGE_COVER_DAYS,
    })


@login_required
@require_GET
def operations_dealer_credit(request):
    from sales.access.services import policy_for

    # 列全部有未付的車行與訂單，家數、張數和卡片相同；scope 參數（T-279 的 scope=all）不再有作用，帶不帶都一樣。
    dealers = cockpit.dealer_credit_rows()
    return render(request, "sales/operations_dealer_credit.html", {
        "dealers": dealers, "today": timezone.localdate(), "can_open_orders": policy_for(request).route("order_list"),
        "order_count": sum(len(row["orders"]) for row in dealers),
    })
