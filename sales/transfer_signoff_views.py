"""調車簽收（可先預備、等人來再簽）、調車紀錄與進車紀錄。

只在店內登入後的裝置簽署，不提供對外簽署連結；不記錄領車人姓名電話，直接簽名（使用者 2026-10-10）。
"""
from io import BytesIO

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from sales.access.services import is_root
from sales.models import SalesSource, VehicleColor, VehicleInventory, VehicleModel, VehicleTransferSignoff
from sales.services.document_signing import decode_signature
from sales.services.inventory_location_note import FACTORY_LABEL
from sales.services.transfer_signoff import (
    STATEMENT,
    cancel_pending,
    content_fingerprint,
    eligible_vehicles,
    prepare_transfer,
    selected_vehicles,
    sign_transfer,
    void_signoff,
)
from sales.views import _protect_private_response, _signing_client_ip


def _dealers():
    return SalesSource.objects.filter(active=True, source_type=SalesSource.SourceType.DEALER).order_by("name")


def _pending_or_none(value):
    if not str(value or "").isdigit():
        return None
    return VehicleTransferSignoff.objects.filter(pk=int(value), status=VehicleTransferSignoff.Status.PENDING).first()


def _read_form(request):
    post = request.POST
    dealer_id = post.get("dealer", "")
    dealer = _dealers().filter(pk=dealer_id).first() if dealer_id.isdigit() else None
    factory = dealer_id == "factory"  # 原廠或總公司調回
    data = {
        "dealer": dealer,
        "factory": factory,
        # 選了車行主檔（或原廠／總公司）就以選項名稱為準；主檔沒有的車行才用手填名稱。
        "dealer_name": (
            FACTORY_LABEL if factory else dealer.name if dealer else post.get("dealer_name", "").strip()
        )[:120],
        "vehicle_ids": [int(value) for value in post.getlist("vehicles") if value.isdigit()],
        "note": post.get("note", "").strip()[:200],
        "pending": _pending_or_none(post.get("pending")),
    }
    errors = []
    if not data["dealer_name"]:
        errors.append("請選擇調往的車行或原廠／總公司，主檔沒有的車行請填寫名稱。")
    return data, errors


def _data_from_pending(pending):
    return {
        "dealer": pending.dealer,
        "factory": not pending.dealer_id and pending.dealer_name == FACTORY_LABEL,
        "dealer_name": pending.dealer_name,
        "vehicle_ids": list(pending.vehicles.values_list("pk", flat=True)),
        "note": pending.note,
        "pending": pending,
    }


def _fingerprint(data, vehicles):
    return content_fingerprint(dealer=data["dealer"], dealer_name=data["dealer_name"], note=data["note"], vehicles=vehicles)


@login_required
def transfer_signoff_create(request):
    """調車簽收：上方列出待簽收的預備調車，下方選車行與車輛；可先存成預備，或直接交給領車人簽名。"""
    step, errors, vehicles, fingerprint = "select", [], [], ""
    pending = _pending_or_none(request.GET.get("pending"))
    data = _data_from_pending(pending) if pending else {
        "dealer": None, "factory": False, "dealer_name": "", "note": "", "pending": None,
        "vehicle_ids": [int(value) for value in request.GET.getlist("vehicle") if value.isdigit()],
    }
    if request.method == "POST":
        data, errors = _read_form(request)
        action = request.POST.get("step", "review")
        try:
            vehicles = selected_vehicles(data["vehicle_ids"])
        except ValidationError as exc:
            errors.extend(exc.messages)
        if action == "save" and not errors:
            try:
                saved = prepare_transfer(
                    dealer=data["dealer"], dealer_name=data["dealer_name"], vehicle_ids=data["vehicle_ids"],
                    note=data["note"], user=request.user, pending=data["pending"],
                )
            except ValidationError as exc:
                errors.extend(exc.messages)
            else:
                messages.success(request, f"已存成預備調車（{saved.dealer_name}，{len(saved.vehicles_snapshot)} 台）；等人來再按「開始簽收」。")
                return redirect("transfer_signoff_create")
        elif action == "sign" and not errors:
            step = "sign"
            if request.POST.get("agree") != "1":
                errors.append("請領車人先勾選「已當面點交無誤」。")
            signature_png = None
            if not errors:
                try:
                    signature_png = decode_signature(request.POST.get("signature", ""))
                except ValidationError as exc:
                    errors.extend(exc.messages)
            if not errors:
                try:
                    signoff = sign_transfer(
                        dealer=data["dealer"], dealer_name=data["dealer_name"], vehicle_ids=data["vehicle_ids"],
                        note=data["note"], expected_fingerprint=request.POST.get("fingerprint", ""),
                        signature_png=signature_png, user=request.user, client_ip=_signing_client_ip(request),
                        user_agent=request.META.get("HTTP_USER_AGENT", ""), pending=data["pending"],
                    )
                except ValidationError as exc:
                    errors.extend(exc.messages)
                else:
                    messages.success(request, f"已完成調車簽收 {signoff.number}，{len(signoff.vehicles_snapshot)} 台車改為已調出。")
                    return redirect("transfer_signoff_detail", pk=signoff.pk)
        elif action == "review" and not errors:
            step = "sign"
        if step == "sign":
            fingerprint = _fingerprint(data, vehicles)
    elif pending and request.GET.get("sign") == "1":
        # 預備調車「開始簽收」：直接進入簽名頁；車輛若已被配走等，回到選車並顯示原因。
        try:
            vehicles = selected_vehicles(data["vehicle_ids"])
        except ValidationError as exc:
            errors.extend(exc.messages)
        else:
            step = "sign"
            fingerprint = _fingerprint(data, vehicles)
    candidates = list(eligible_vehicles())
    response = render(
        request,
        "sales/transfer_signoff_sign.html" if step == "sign" else "sales/transfer_signoff_form.html",
        {
            "step": step,
            "errors": errors,
            "data": data,
            "dealers": _dealers(),
            "candidates": candidates,
            "selected_ids": set(data["vehicle_ids"]),
            "vehicles": vehicles,
            "fingerprint": fingerprint,
            "statement": STATEMENT,
            "pending_list": VehicleTransferSignoff.objects.filter(status=VehicleTransferSignoff.Status.PENDING)
            .annotate(vehicle_count=Count("vehicles")).order_by("-updated_at", "-id"),
            "filter_models": sorted({v.vehicle_model.name for v in candidates}),
            "filter_colors": sorted({v.color.name for v in candidates}),
            "filter_locations": sorted({v.actual_location_label for v in candidates}),
        },
        status=400 if errors and request.method == "POST" else 200,
    )
    return _protect_private_response(response)


@login_required
@require_POST
def transfer_signoff_cancel(request, pk):
    signoff = get_object_or_404(VehicleTransferSignoff, pk=pk)
    try:
        cancel_pending(signoff)
    except ValidationError as exc:
        messages.error(request, "未取消：" + "；".join(exc.messages))
    else:
        messages.success(request, f"已取消預備調車（{signoff.dealer_name}）。")
    return redirect("transfer_signoff_create")


@login_required
def transfer_signoff_list(request):
    """調車紀錄：已簽收（含作廢）的調車，可依日期、對象或車號篩選。"""
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
        "colors": VehicleColor.objects.filter(vehicleinventory__isnull=False).values_list("name", flat=True).distinct().order_by("name"),
        "acquisition_choices": VehicleInventory.AcquisitionType.choices,
        "selected": {"from": request.GET.get("from", ""), "to": request.GET.get("to", ""), "model": model_name,
                     "color": color_name, "acquisition": acquisition},
        "filter_query": query.urlencode(),
    })


@login_required
def transfer_signoff_detail(request, pk):
    signoff = get_object_or_404(VehicleTransferSignoff.objects.select_related("dealer"), pk=pk)
    if signoff.is_pending:
        return redirect(f"{reverse('transfer_signoff_create')}?pending={signoff.pk}")
    current = {vehicle.pk: vehicle for vehicle in signoff.vehicles.all()}
    rows = [{**item, "vehicle": current.get(item["id"])} for item in signoff.vehicles_snapshot]
    response = render(
        request,
        "sales/transfer_signoff_detail.html",
        {
            "signoff": signoff,
            "rows": rows,
            "can_void": is_root(request.user) and not signoff.is_voided,
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
