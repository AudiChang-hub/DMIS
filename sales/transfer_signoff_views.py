"""調車簽收：選車行與車輛 → 領車人在店內裝置確認並簽名 → 產生簽收單（不提供對外簽署連結）。"""
from io import BytesIO

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Count
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from sales.access.services import is_root
from sales.models import SalesSource, VehicleTransferSignoff
from sales.services.document_signing import decode_signature
from sales.services.inventory_location_note import FACTORY_LABEL
from sales.services.transfer_signoff import (
    STATEMENT,
    content_fingerprint,
    eligible_vehicles,
    selected_vehicles,
    sign_transfer,
    void_signoff,
)
from sales.views import _protect_private_response, _signing_client_ip


def _dealers():
    return SalesSource.objects.filter(active=True, source_type=SalesSource.SourceType.DEALER).order_by("name")


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
        "signer_name": post.get("signer_name", "").strip()[:60],
        "signer_phone": post.get("signer_phone", "").strip()[:30],
        "note": post.get("note", "").strip()[:200],
    }
    errors = []
    if not data["dealer_name"]:
        errors.append("請選擇調往的車行或原廠／總公司，主檔沒有的車行請填寫名稱。")
    if not data["signer_name"]:
        errors.append("請填寫領車人姓名。")
    return data, errors


def _fingerprint(data, vehicles):
    return content_fingerprint(
        dealer=data["dealer"], dealer_name=data["dealer_name"], signer_name=data["signer_name"],
        signer_phone=data["signer_phone"], note=data["note"], vehicles=vehicles,
    )


@login_required
def transfer_signoff_list(request):
    signoffs = VehicleTransferSignoff.objects.select_related("dealer").annotate(vehicle_count=Count("vehicles"))
    page = Paginator(signoffs, 30).get_page(request.GET.get("page"))
    return render(request, "sales/transfer_signoff_list.html", {"page_obj": page, "signoffs": page.object_list})


@login_required
def transfer_signoff_create(request):
    step, errors, vehicles, fingerprint = "select", [], [], ""
    data = {
        "dealer": None, "factory": False, "dealer_name": "", "signer_name": "", "signer_phone": "", "note": "",
        "vehicle_ids": [int(value) for value in request.GET.getlist("vehicle") if value.isdigit()],
    }
    if request.method == "POST":
        data, errors = _read_form(request)
        action = request.POST.get("step", "review")
        try:
            vehicles = selected_vehicles(data["vehicle_ids"])
        except ValidationError as exc:
            errors.extend(exc.messages)
        if action == "sign" and not errors:
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
                        signer_name=data["signer_name"], signer_phone=data["signer_phone"], note=data["note"],
                        expected_fingerprint=request.POST.get("fingerprint", ""), signature_png=signature_png,
                        user=request.user, client_ip=_signing_client_ip(request),
                        user_agent=request.META.get("HTTP_USER_AGENT", ""),
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
    selected_ids = set(data["vehicle_ids"])
    candidates = list(eligible_vehicles())
    response = render(
        request,
        # 選車與簽名分兩個模板：簽名頁只給領車人看（隱藏主選單）。
        "sales/transfer_signoff_sign.html" if step == "sign" else "sales/transfer_signoff_form.html",
        {
            "step": step,
            "errors": errors,
            "data": data,
            "dealers": _dealers(),
            "candidates": candidates,
            "selected_ids": selected_ids,
            "vehicles": vehicles,
            "fingerprint": fingerprint,
            "statement": STATEMENT,
        },
        status=400 if errors and request.method == "POST" else 200,
    )
    return _protect_private_response(response)


@login_required
def transfer_signoff_detail(request, pk):
    signoff = get_object_or_404(VehicleTransferSignoff.objects.select_related("dealer"), pk=pk)
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
