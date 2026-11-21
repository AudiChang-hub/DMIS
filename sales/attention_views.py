"""營運總表「需要處理」的唯讀明細頁（T-275）：點進來只列卡片算到的那一批，條件與卡片共用同一函式。

- 缺貨風險車型（使用者選 A）：列車型、在庫台數、近 90 天領牌台數、可銷天數；權限同車輛庫存。
- 車行掛帳超過額度（使用者選補連結）：列超過額度的車行與它們的掛帳訂單；權限同營運總表的財務彙總。
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

    dealers = [{**row, "excess": row["amount"] - row["limit"]} for row in cockpit.dealer_credit_rows() if row["over"]]
    return render(request, "sales/operations_dealer_credit.html", {
        "dealers": dealers, "today": timezone.localdate(), "can_open_orders": policy_for(request).route("order_list"),
    })
