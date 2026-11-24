"""調出（T-310）、調車紀錄與進車紀錄。

調出在庫存列表勾車後一步完成，不簽名、不產生 PDF、沒有預備調車（使用者 2026-11-24）。
舊的調車簽收頁網址轉到庫存列表；2026-11-24 以前已簽名的紀錄照常可看簽名與簽收單 PDF。
"""
from io import BytesIO

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.dateparse import parse_date
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from sales.access.services import is_root
from sales.models import VehicleColor, VehicleInventory, VehicleModel, VehicleTransferSignoff
from sales.services.transfer_signoff import STATEMENT, transfer_out, void_signoff
from sales.views import _protect_private_response

# 調出完成後回到庫存列表，列表底部顯示「已調出 N 台給 X｜看調車紀錄」。
TRANSFER_DONE_SESSION_KEY = "inventory_transfer_out_done"


def _inventory_url():
    return f"{reverse('inventory_list')}?scope=current"


@login_required
def transfer_signoff_create(request):
    """舊的「調車簽收」頁已移除（T-310）：調出改在庫存列表勾車完成，舊書籤轉到庫存列表。"""
    return redirect(_inventory_url())


def _next_url(request):
    next_url = request.POST.get("next", "")
    if not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        next_url = _inventory_url()
    return next_url


@login_required
@require_POST
def inventory_transfer_out(request):
    """調出：勾好的車＋「調給哪一家」＋備註（選填），確認後一次完成。"""
    next_url = _next_url(request)
    ajax = request.headers.get("x-requested-with") == "XMLHttpRequest"
    try:
        signoff = transfer_out(
            vehicle_ids=request.POST.getlist("vehicles"), name=request.POST.get("name", ""),
            note=request.POST.get("note", ""), user=request.user,
        )
    except ValidationError as exc:
        message = "未調出：" + "；".join(exc.messages)
        if ajax:
            return JsonResponse({"ok": False, "message": message}, status=400)
        messages.error(request, message)
        return redirect(next_url)
    count = len(signoff.vehicles_snapshot)
    request.session[TRANSFER_DONE_SESSION_KEY] = {"pk": signoff.pk, "count": count, "name": signoff.dealer_name}
    if ajax:
        return JsonResponse({"ok": True, "redirect": next_url, "message": f"已調出 {count} 台給 {signoff.dealer_name}"})
    return redirect(next_url)


def pop_transfer_done(request):
    """庫存列表讀一次就清掉的調出完成提示。"""
    done = request.session.pop(TRANSFER_DONE_SESSION_KEY, None)
    if not isinstance(done, dict) or not str(done.get("pk", "")).isdigit():
        return None
    return {**done, "url": reverse("transfer_signoff_detail", args=[done["pk"]])}


@login_required
def transfer_signoff_list(request):
    """調車紀錄：已調出（含作廢）的調車，可依日期、對象或車號篩選；預備調車不列。"""
    signoffs = VehicleTransferSignoff.objects.filter(status=VehicleTransferSignoff.Status.SIGNED).select_related("dealer")
    date_from = parse_date(request.GET.get("from", "") or "")
    date_to = parse_date(request.GET.get("to", "") or "")
    keyword = request.GET.get("q", "").strip()
    if date_from:
        signoffs = signoffs.filter(signed_at__date__gte=date_from)
    if date_to:
        signoffs = signoffs.filter(signed_at__date__lte=date_to)
    if keyword:
        signoffs = signoffs.filter(Q(dealer_name__icontains=keyword) | Q(note__icontains=keyword)
                                   | Q(vehicles__engine_number__icontains=keyword)
                                   | Q(vehicles__frame_number__icontains=keyword)).distinct()
    signoffs = signoffs.annotate(vehicle_count=Count("vehicles", distinct=True)).order_by("-signed_at", "-id")
    page = Paginator(signoffs, 30).get_page(request.GET.get("page"))
    query = request.GET.copy()
    query.pop("page", None)
    return render(request, "sales/transfer_signoff_list.html", {
        "page_obj": page, "signoffs": page.object_list,
        "selected": {"from": request.GET.get("from", ""), "to": request.GET.get("to", ""), "q": keyword},
        "filter_query": query.urlencode(),
    })


def _receipt_color_choices():
    """進車紀錄的車色篩選：仍以名稱篩選，選項文字比照列表顯示「名稱 色碼」（T-229）。"""
    codes = {}
    rows = VehicleColor.objects.filter(vehicleinventory__isnull=False).values_list("name", "code").order_by().distinct()
    for name, code in rows:
        codes.setdefault(name, set())
        if (code or "").strip():
            codes[name].add(code.strip())
    return [
        {"value": name, "label": f"{name} {'／'.join(sorted(codes[name]))}" if codes[name] else name}
        for name in sorted(codes)
    ]


@login_required
def inventory_receipt_list(request):
    """進車紀錄：依進車日期區間、車型、車色與來源篩選，查某段時間進了哪幾台車。"""
    vehicles = VehicleInventory.objects.select_related("vehicle_model", "color", "current_dealer")
    date_from = parse_date(request.GET.get("from", "") or "")
    date_to = parse_date(request.GET.get("to", "") or "")
    model_name = request.GET.get("model", "").strip()
    color_name = request.GET.get("color", "").strip()
    acquisition = request.GET.get("acquisition", "")
    if date_from:
        vehicles = vehicles.filter(received_on__gte=date_from)
    if date_to:
        vehicles = vehicles.filter(received_on__lte=date_to)
    if model_name:
        vehicles = vehicles.filter(vehicle_model__name=model_name)
    if color_name:
        vehicles = vehicles.filter(color__name=color_name)
    if acquisition in VehicleInventory.AcquisitionType.values:
        vehicles = vehicles.filter(acquisition_type=acquisition)
    else:
        acquisition = ""
    vehicles = vehicles.order_by("-received_on", "-id")
    daily_counts = list(vehicles.order_by().values("received_on").annotate(count=Count("id")).order_by("-received_on")[:31])
    page = Paginator(vehicles, 100).get_page(request.GET.get("page"))
    query = request.GET.copy()
    query.pop("page", None)
    return render(request, "sales/inventory_receipt_list.html", {
        "page_obj": page, "vehicles": page.object_list, "daily_counts": daily_counts,
        "models": VehicleModel.objects.filter(vehicleinventory__isnull=False).values_list("name", flat=True).distinct().order_by("name"),
        "colors": _receipt_color_choices(),
        "acquisition_choices": VehicleInventory.AcquisitionType.choices,
        "selected": {"from": request.GET.get("from", ""), "to": request.GET.get("to", ""), "model": model_name,
                     "color": color_name, "acquisition": acquisition},
        "filter_query": query.urlencode(),
    })


@login_required
def transfer_signoff_detail(request, pk):
    signoff = get_object_or_404(VehicleTransferSignoff.objects.select_related("dealer"), pk=pk)
    if signoff.is_pending:
        return redirect(_inventory_url())
    current = {vehicle.pk: vehicle for vehicle in signoff.vehicles.all()}
    rows = [{**item, "vehicle": current.get(item["id"])} for item in signoff.vehicles_snapshot]
    response = render(
        request,
        "sales/transfer_signoff_detail.html",
        {
            "signoff": signoff,
            "rows": rows,
            "can_void": is_root(request.user) and not signoff.is_voided,
            # 2026-11-24 以前在店內簽名的紀錄才有簽名與 PDF；依檔案是否存在判斷，不看日期。
            "has_signature": bool(signoff.signature_image),
            "has_pdf": bool(signoff.signed_pdf),
            "signature_url": reverse("protected_media", args=["transfer_signoff", signoff.pk, "signature_image"]),
            "statement": STATEMENT,
        },
    )
    return _protect_private_response(response)


@login_required
def transfer_signoff_pdf(request, pk):
    signoff = get_object_or_404(VehicleTransferSignoff, pk=pk)
    if not signoff.signed_pdf:
        raise Http404
    with signoff.signed_pdf.open("rb") as handle:
        content = handle.read()
    response = FileResponse(BytesIO(content), content_type="application/pdf")
    response["Content-Disposition"] = (
        f'inline; filename="{signoff.number}.pdf"; '
        f"filename*=UTF-8''{signoff.number}%E8%AA%BF%E8%BB%8A%E7%B0%BD%E6%94%B6%E5%96%AE.pdf"
    )
    return _protect_private_response(response, preview=True)


@login_required
@require_POST
def transfer_signoff_void(request, pk):
    signoff = get_object_or_404(VehicleTransferSignoff, pk=pk)
    actor = request.user.get_full_name() or request.user.get_username()
    try:
        restored, kept = void_signoff(signoff, actor_name=actor, reason=request.POST.get("reason", ""))
    except ValidationError as exc:
        messages.error(request, "未作廢：" + "；".join(exc.messages))
    else:
        message = f"已作廢 {signoff.number}，{len(restored)} 台車改回庫存。"
        if kept:
            message += f"{'、'.join(kept)} 之後已有其他異動，維持目前狀態。"
        messages.success(request, message)
    return redirect("transfer_signoff_detail", pk=pk)
