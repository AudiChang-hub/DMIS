from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_http_methods

from sales.access.services import policy_for
from sales.models import SalesOrder
from sales.services.order_overview import build_order_overview


@login_required
@require_http_methods(["GET", "HEAD"])
def order_overview(request, pk):
    """訂單總覽（唯讀）：訂單頁側邊列開啟時只回傳內容片段；直接開網址則是完整頁面。"""
    order = get_object_or_404(
        SalesOrder.objects.select_related(
            "source", "vehicle_model", "color", "allocated_vehicle", "accepted_by", "print_company",
        ).prefetch_related("accessories", "other_fees", "subsidy_items", "payment_records"),
        pk=pk,
    )
    overview = build_order_overview(order, include_finance=policy_for(request).route("order_operations", kwargs={"pk": pk}))
    template = "sales/_order_overview.html" if request.GET.get("fragment") == "1" else "sales/order_overview.html"
    response = render(request, template, {"order": order, "overview": overview})
    response["Cache-Control"] = "private, no-store, max-age=0"
    return response
