"""admin：歷史匯入的待交車訂單補登車牌並完成交車（路由列在 ROOT_ONLY）。"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from sales.services import historical_delivery


@login_required
@require_POST
def complete(request, pk):
    actor = request.user.get_full_name() or request.user.get_username()
    try:
        day = parse_date((request.POST.get("delivered_on") or "").strip())
    except ValueError:
        day = None
    try:
        order = historical_delivery.complete_imported_order(
            pk, plate=request.POST.get("plate", ""), delivered_on=day,
            actor=actor, reason=request.POST.get("reason", ""),
        )
    except ValueError as exc:
        messages.error(request, f"未完成交車：{exc}")
    else:
        messages.success(request, f"已補登車牌 {order.final_plate_number}，訂單改為已完成。")
    return redirect("order_detail", pk=pk)
