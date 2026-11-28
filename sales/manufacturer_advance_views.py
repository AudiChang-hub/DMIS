"""原廠代墊／代轉（T-334 第一版）的網址：追蹤頁（含營運總表側邊明細與卡片的片段）、訂單頁新增、勾選、刪除與登記撥款。

權限比照訂單頁「收入與支出」（sales/access/registry.py 的 order_finance）：查看就看得到，操作才能勾；
訂單範圍同全部訂單（新增走 ORDER_PK_ROUTES，其餘逐筆在這裡檢查）。讀寫邏輯都在 sales/services/manufacturer_advance.py。
"""
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_POST

from sales.models import ManufacturerAdvanceCampaign, ManufacturerAdvancePayout, SalesOrder
from sales.services import manufacturer_advance as advances
from sales.services import manufacturer_advance_campaign as advance_campaigns
from sales.services.order_intake import can_edit_finance, scoped_orders


def _is_ajax(request):
    return request.headers.get("x-requested-with") == "XMLHttpRequest"


def _reply(request, status, payload, fallback):
    if _is_ajax(request):
        return JsonResponse(payload, status=status)
    (messages.success if payload.get("ok") else messages.error)(request, payload.get("message", ""))
    next_url = request.POST.get("next", "")
    if not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        next_url = fallback
    return redirect(next_url)


def _visible_item(request, pk):
    item = advances.visible_items(request.user).filter(pk=pk).first()
    if item is None:
        # 已刪除（作廢）的項目也要能復原，只要訂單看得到。
        from sales.models import ManufacturerAdvance
        item = ManufacturerAdvance.objects.filter(
            pk=pk, order__in=scoped_orders(request.user, SalesOrder.objects.all())).select_related("order").first()
    if item is None:
        raise Http404
    return item


def block_context(request, order):
    """訂單頁「原廠代墊／代轉」小區塊。"""
    from sales.models import ManufacturerAdvance

    return {
        "order": order,
        "advance_items": advances.order_items(order),
        "advance_editable": can_edit_finance(request.user),
        "advance_dealer_available": advances.dealer_available(order),
        "advance_default_manufacturer": advances.default_manufacturer(order),
        "advance_manufacturers": advances.manufacturer_suggestions(),
        "advance_campaigns": advances.campaign_suggestions(),
        "advance_recipients": ManufacturerAdvance.Recipient,
        "advance_kinds": ManufacturerAdvance.Kind,
        # T-337：還沒確認領牌的單依訂單日期「預計適用」的活動，與標了「不適用」的活動。
        "advance_projected": advance_campaigns.projected_campaigns(order),
        "advance_projected_on": order.order_date,
        "advance_exclusions": advance_campaigns.exclusions(order),
    }


def render_block(request, order):
    return render_to_string("sales/_manufacturer_advance_block.html", block_context(request, order), request=request)


def _tab(request):
    tab = request.GET.get("tab", "")
    return tab if tab in advances.TABS else "reimburse"


def panel_context(request, *, in_drawer=False):
    tab = _tab(request)
    manufacturer = request.GET.get("manufacturer", "").strip()
    visible = advances.visible_items(request.user)
    options = advances.manufacturers_in(advances.pending(visible, "reimburse") | advances.pending(visible, "handover"))
    if manufacturer and manufacturer not in options:
        options.append(manufacturer)
    counts = advances.tab_counts(request.user, manufacturer)
    base = reverse("manufacturer_advance_list")
    tabs = []
    for key, label in advances.TABS.items():
        query = urlencode({"tab": key, **({"manufacturer": manufacturer} if manufacturer else {})})
        tabs.append({"key": key, "label": label, "count": counts[key], "active": key == tab, "query": query,
                     "url": f"{base}?{query}"})
    return {
        "tab": tab, "tab_label": advances.TABS[tab], "tabs": tabs,
        "manufacturer": manufacturer, "manufacturer_options": options,
        "rows": advances.tracking_rows(request.user, tab, manufacturer),
        "alert_days": advances.ALERT_DAYS,
        "advance_editable": can_edit_finance(request.user),
        "in_drawer": in_drawer,
        "list_url": base,
        "today": timezone.localdate(),
    }


@login_required
@require_GET
def manufacturer_advance_list(request):
    fragment = request.GET.get("fragment", "")
    if fragment == "card":
        return render(request, "sales/_manufacturer_advance_card.html",
                      {"advance_summary": advances.summary(request.user), "list_url": reverse("manufacturer_advance_list")})
    if fragment == "panel":
        return render(request, "sales/_manufacturer_advance_panel.html", panel_context(request, in_drawer=True))
    return render(request, "sales/manufacturer_advance_list.html", panel_context(request))


@login_required
@require_POST
def manufacturer_advance_create(request, pk):
    order = get_object_or_404(SalesOrder.objects.select_related("vehicle_model", "source"), pk=pk)
    fallback = reverse("order_detail", args=[order.pk]) + "?tab=finance"
    form = advances.ManufacturerAdvanceForm(request.POST, order=order)
    if not form.is_valid():
        errors = {name: [str(error) for error in errors] for name, errors in form.errors.items()}
        first = next(iter(errors.values()))[0] if errors else "資料不完整。"
        return _reply(request, 400, {"ok": False, "message": first, "errors": errors}, fallback)
    item = advances.create_item(order, form, request.user)
    return _reply(request, 200, {
        "ok": True, "id": item.pk, "html": render_block(request, order),
        "message": f"已新增「{item.campaign_name}」{item.content_label}",
    }, fallback)


def _conflict_payload(request, conflict):
    return {"ok": False, "message": conflict.message, "items": [advances.item_state(item) for item in conflict.items]}


@login_required
@require_POST
def manufacturer_advance_toggle(request, pk):
    item = _visible_item(request, pk)
    fallback = reverse("manufacturer_advance_list")
    flag = request.POST.get("flag", "")
    value = request.POST.get("value") == "1"
    expected = request.POST.get("expected")
    try:
        item, changed = advances.set_flag(item.pk, flag, value, request.user, expected=expected,
                                          undo=request.POST.get("undo") == "1")
    except advances.Conflict as conflict:
        return _reply(request, 409, _conflict_payload(request, conflict), fallback)
    except ValidationError as error:
        return _reply(request, 400, {"ok": False, "message": error.messages[0]}, fallback)
    label = advances.FLAGS[flag]
    if not changed:
        message = f"這筆本來就{'已' if value else '還沒'}勾「{label}」。"
    elif value:
        message = f"已勾「{label}」，記在 {advances.flag_label(item, flag)}"
    else:
        message = f"已取消「{label}」"
    return _reply(request, 200, {"ok": True, "changed": changed, "message": message, "items": [advances.item_state(item)]},
                  fallback)


def _exclude_reply(request, order, campaign, restore):
    fallback = reverse("order_detail", args=[order.pk]) + "?tab=finance"
    try:
        if restore:
            item = advance_campaigns.clear_not_applicable(order, campaign, request.user)
        else:
            item = advance_campaigns.mark_not_applicable(order, campaign, request.user)
    except advances.Conflict as conflict:
        return _reply(request, 409, _conflict_payload(request, conflict), fallback)
    order = SalesOrder.objects.select_related("vehicle_model", "source").get(pk=order.pk)
    message = (f"已復原「{campaign.name}」，依活動條件重新比對" if restore
               else f"已把「{campaign.name}」標為不適用，之後不會再自動掛上")
    payload = {"ok": True, "message": message, "html": render_block(request, order)}
    if item is not None:
        item.refresh_from_db()
        payload["items"] = [advances.item_state(item)]
    return _reply(request, 200, payload, fallback)


@login_required
@require_POST
def manufacturer_advance_exclude(request, pk, campaign_pk):
    """T-337 單張訂單標「不適用」某個活動（restore=1 復原）。訂單範圍走 ORDER_PK_ROUTES。"""
    order = get_object_or_404(SalesOrder.objects.select_related("vehicle_model", "source"), pk=pk)
    campaign = get_object_or_404(ManufacturerAdvanceCampaign, pk=campaign_pk)
    return _exclude_reply(request, order, campaign, request.POST.get("restore") == "1")


@login_required
@require_POST
def manufacturer_advance_void(request, pk):
    item = _visible_item(request, pk)
    restore = request.POST.get("restore") == "1"
    if item.campaign_id:
        # 依活動自動掛上的項目不實體作廢，改成標「不適用」，才不會再被自動掛回去（T-337）。
        order = SalesOrder.objects.select_related("vehicle_model", "source").get(pk=item.order_id)
        return _exclude_reply(request, order, item.campaign, restore)
    fallback = reverse("order_detail", args=[item.order_id]) + "?tab=finance"
    try:
        item = advances.void_item(item.pk, request.user, restore=restore)
    except advances.Conflict as conflict:
        return _reply(request, 409, _conflict_payload(request, conflict), fallback)
    order = SalesOrder.objects.select_related("vehicle_model", "source").get(pk=item.order_id)
    message = f"已復原「{item.campaign_name}」" if restore else f"已刪除「{item.campaign_name}」"
    return _reply(request, 200, {"ok": True, "id": item.pk, "message": message, "html": render_block(request, order),
                                 "items": [advances.item_state(item)]}, fallback)


@login_required
@require_POST
def manufacturer_advance_payout(request):
    fallback = reverse("manufacturer_advance_list")
    ids = request.POST.getlist("items")
    form = advances.PayoutForm(request.POST)
    if not form.is_valid():
        first = next(iter(form.errors.values()))[0]
        return _reply(request, 400, {"ok": False, "message": str(first)}, fallback)
    try:
        payout, items = advances.register_payout(
            request.user, [pk for pk in ids if str(pk).isdigit()], form.cleaned_data["paid_on"], form.cleaned_data["amount"],
            visible=advances.visible_items(request.user),
        )
    except advances.Conflict as conflict:
        return _reply(request, 409, _conflict_payload(request, conflict), fallback)
    except ValidationError as error:
        return _reply(request, 400, {"ok": False, "message": error.messages[0]}, fallback)
    totals = advances.payout_totals(items, payout.amount)
    difference = totals["difference"]
    diff_text = "沒有差額" if not difference else f"差額 {'＋' if difference > 0 else '−'}${abs(difference):,.0f}"
    return _reply(request, 200, {
        "ok": True, "payout": payout.pk,
        "message": f"已登記 {payout.manufacturer} 撥款 {len(items)} 筆，實撥 ${payout.amount:,.0f}（{diff_text}）",
        "items": [advances.item_state(item) for item in items],
    }, fallback)


@login_required
@require_POST
def manufacturer_advance_payout_void(request, pk):
    fallback = reverse("manufacturer_advance_list")
    payout = get_object_or_404(ManufacturerAdvancePayout, pk=pk)
    visible = advances.visible_items(request.user)
    if payout.items.exists() and visible.filter(payout=payout).count() != payout.items.count():
        raise Http404
    payout, items = advances.void_payout(payout.pk, request.user)
    return _reply(request, 200, {"ok": True, "message": f"已復原這次撥款登記，{len(items)} 筆改回等原廠撥款",
                                 "items": [advances.item_state(item) for item in items]}, fallback)
