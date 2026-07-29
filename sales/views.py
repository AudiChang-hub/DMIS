import json
import logging
from datetime import timedelta
from io import BytesIO

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from PIL import Image, UnidentifiedImageError

from .services.order_contract_pdf import build_order_contract_pdf

from .forms import (
    AccessoryFormSet,
    AllocationForm,
    OtherFeeFormSet,
    SalesOrderForm,
    SignedContractForm,
    VehicleInventoryForm,
)
from .models import (
    OrderEvent,
    OrderDraft,
    SalesOrder,
    SalesSource,
    VehicleColor,
    VehicleInventory,
)
from .services.id_ocr import IdOcrError, recognize_id_card


logger = logging.getLogger(__name__)
DRAFT_PRESENCE_TIMEOUT = timedelta(seconds=90)


def _editing_name(user):
    return user.get_full_name() or user.get_username()


def app_version(request):
    from config.app_version import get_app_version

    response = JsonResponse({"version": get_app_version()})
    response["Cache-Control"] = "no-store, no-cache, must-revalidate"
    response["Pragma"] = "no-cache"
    return response


@login_required
def dashboard(request):
    query = request.GET.get("q", "").strip()
    orders = SalesOrder.objects.select_related(
        "source", "vehicle_model", "color", "allocated_vehicle"
    )
    if query:
        normalized = query.replace("-", "").replace(" ", "")
        orders = orders.filter(
            Q(number__icontains=query)
            | Q(owner_name__icontains=query)
            | Q(owner_phone__icontains=query)
            | Q(owner_id_number__icontains=normalized)
            | Q(source__name__icontains=query)
            | Q(vehicle_model__brand__icontains=query)
            | Q(vehicle_model__name__icontains=query)
            | Q(color__name__icontains=query)
            | Q(final_plate_number__icontains=normalized)
            | Q(allocated_vehicle__engine_number__icontains=normalized)
            | Q(allocated_vehicle__frame_number__icontains=normalized)
            | Q(note__icontains=query)
        ).distinct()

    active = orders.exclude(
        status__in=[SalesOrder.Status.COMPLETED, SalesOrder.Status.CANCELLED]
    )
    context = {
        "query": query,
        "search_results": orders[:50] if query else None,
        "urgent_orders": active.filter(
            status__in=[
                SalesOrder.Status.CANCEL_REFUND_PENDING,
                SalesOrder.Status.DELIVERED_DOCS_PENDING,
            ]
        )[:12],
        "contract_pending": active.filter(
            status=SalesOrder.Status.CONTRACT_PENDING
        )[:12],
        "allocation_pending": active.filter(
            status=SalesOrder.Status.ALLOCATION_PENDING
        )[:12],
        "in_progress": active.exclude(
            status__in=[
                SalesOrder.Status.CONTRACT_PENDING,
                SalesOrder.Status.ALLOCATION_PENDING,
                SalesOrder.Status.CANCEL_REFUND_PENDING,
                SalesOrder.Status.DELIVERED_DOCS_PENDING,
            ]
        )[:12],
        "counts": {
            "urgent": active.filter(
                status__in=[
                    SalesOrder.Status.CANCEL_REFUND_PENDING,
                    SalesOrder.Status.DELIVERED_DOCS_PENDING,
                ]
            ).count(),
            "contract": active.filter(
                status=SalesOrder.Status.CONTRACT_PENDING
            ).count(),
            "allocation": active.filter(
                status=SalesOrder.Status.ALLOCATION_PENDING
            ).count(),
            "inventory": VehicleInventory.objects.filter(
                status=VehicleInventory.Status.AVAILABLE
            ).count(),
        },
        "drafts": OrderDraft.objects.all()[:12],
    }
    return render(request, "sales/dashboard.html", context)


@login_required
def order_list(request):
    orders = SalesOrder.objects.select_related("source", "vehicle_model", "color")
    status = request.GET.get("status")
    if status:
        orders = orders.filter(status=status)
    return render(
        request,
        "sales/order_list.html",
        {"orders": orders[:200], "statuses": SalesOrder.Status.choices},
    )


@login_required
@transaction.atomic
def order_create(request):
    draft_id = request.POST.get("_draft_id") or request.GET.get("draft")
    draft = get_object_or_404(OrderDraft, pk=draft_id) if draft_id else None
    existing_documents = {
        "id_front": bool(draft and draft.id_front),
        "id_back": bool(draft and draft.id_back),
    }
    if request.method == "POST":
        post_data = _reconcile_collaborative_post(draft, request.POST)
        form = SalesOrderForm(
            post_data,
            request.FILES,
            existing_documents=existing_documents,
        )
        formset = AccessoryFormSet(post_data)
        fee_formset = OtherFeeFormSet(post_data, prefix="other_fees")
        if form.is_valid() and formset.is_valid() and fee_formset.is_valid():
            order = form.save(commit=False)
            if draft:
                if not form.cleaned_data.get("id_front") and draft.id_front:
                    order.id_front = draft.id_front.name
                    draft.id_front = ""
                if not form.cleaned_data.get("id_back") and draft.id_back:
                    order.id_back = draft.id_back.name
                    draft.id_back = ""
            order.status = SalesOrder.Status.CONTRACT_PENDING
            order.save()
            formset.instance = order
            formset.save()
            fee_formset.instance = order
            fee_formset.save()
            order.calculated_balance = order.calculate_balance()
            order.actual_balance = order.calculated_balance
            order.save(
                update_fields=["calculated_balance", "actual_balance", "updated_at"]
            )
            OrderEvent.objects.create(
                order=order,
                event_type="created",
                description="建立訂單，等待列印並上傳已簽署合約。",
                actor_name=request.user.get_username(),
            )
            if draft:
                draft.delete_with_files()
            messages.success(request, "訂單已建立。請列印一式兩份並上傳簽署合約。")
            return redirect(f"{reverse('order_detail', kwargs={'pk': order.pk})}?created=1")
    else:
        initial = _draft_form_initial(draft.data) if draft else None
        form = SalesOrderForm(initial=initial)
        formset = AccessoryFormSet(
            initial=_draft_lines(
                draft.data, "accessories", ("name", "quantity", "line_type", "amount", "installed_on", "note")
            )
            if draft
            else None
        )
        fee_formset = OtherFeeFormSet(
            initial=_draft_lines(draft.data, "other_fees", ("name", "amount"))
            if draft
            else None,
            prefix="other_fees",
        )
    return render(
        request,
        "sales/order_form.html",
        {
            "form": form,
            "formset": formset,
            "fee_formset": fee_formset,
            "draft": draft,
        },
    )


def _draft_form_initial(data):
    return {
        key: (value[-1] if isinstance(value, list) and value else value)
        for key, value in data.items()
        if not key.startswith("accessories-")
    }


def _field_versions(post_data):
    try:
        versions = json.loads(post_data.get("_field_versions", "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    if not isinstance(versions, dict):
        return {}
    result = {}
    for key, version in versions.items():
        try:
            result[str(key)] = max(0, int(version))
        except (TypeError, ValueError):
            continue
    return result


def _reconcile_collaborative_post(draft, post_data):
    if not draft:
        return post_data
    reconciled = post_data.copy()
    client_versions = _field_versions(post_data)
    for state in draft.field_states.all():
        if client_versions.get(state.field_key, 0) < state.version:
            reconciled.setlist(
                state.field_key,
                state.value if isinstance(state.value, list) else [str(state.value)],
            )
    return reconciled


def _draft_lines(data, prefix, fields):
    try:
        total = int(data.get(f"{prefix}-TOTAL_FORMS", 0))
    except (TypeError, ValueError):
        total = 0
    rows = []
    for index in range(min(total, 50)):
        if data.get(f"{prefix}-{index}-DELETE"):
            continue
        row = {
            field: data.get(f"{prefix}-{index}-{field}", "")
            for field in fields
        }
        if any(str(value).strip() for value in row.values()):
            rows.append(row)
    return rows


def _validate_draft_image(upload):
    if upload.size > 10 * 1024 * 1024:
        raise ValidationError("單張證件照片不可超過 10 MB。")
    if upload.content_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise ValidationError("證件照片僅支援 JPEG、PNG 或 WebP。")
    try:
        Image.open(upload).verify()
        upload.seek(0)
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ValidationError("上傳的檔案不是有效圖片。") from exc


@login_required
@transaction.atomic
def draft_save(request):
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "僅接受 POST。"}, status=405)
    draft_id = request.POST.get("_draft_id")
    is_new = not draft_id
    if draft_id:
        draft = get_object_or_404(OrderDraft.objects.select_for_update(), pk=draft_id)
        try:
            client_revision = int(request.POST.get("_draft_revision", 0))
        except (TypeError, ValueError):
            client_revision = 0
        if client_revision != draft.revision:
            return JsonResponse(
                {
                    "ok": False,
                    "conflict": True,
                    "error": "此草稿已被其他人更新，請重新載入後再編輯。",
                    "revision": draft.revision,
                },
                status=409,
            )
    else:
        draft = OrderDraft(created_by=request.user.get_username())

    excluded = {
        "csrfmiddlewaretoken",
        "_draft_id",
        "_draft_revision",
        "_remove_id_front",
        "_remove_id_back",
        "_field_versions",
    }
    reconciled_post = _reconcile_collaborative_post(
        draft if not is_new else None, request.POST
    )
    draft.data = {
        key: values if len(values) > 1 else values[0]
        for key, values in reconciled_post.lists()
        if key not in excluded
    }
    for field_name in ("id_front", "id_back"):
        if request.POST.get(f"_remove_{field_name}") == "1":
            current = getattr(draft, field_name)
            if current:
                current.delete(save=False)
            setattr(draft, field_name, "")
        upload = request.FILES.get(field_name)
        if upload:
            try:
                _validate_draft_image(upload)
            except ValidationError as exc:
                return JsonResponse(
                    {"ok": False, "error": " ".join(exc.messages)}, status=400
                )
            current = getattr(draft, field_name)
            if current:
                current.delete(save=False)
            setattr(draft, field_name, upload)
    if not is_new:
        draft.revision += 1
    draft.updated_by = request.user.get_username()
    draft.save()
    photo_urls = {
        field_name: (
            reverse(
                "protected_media",
                args=["draft", str(draft.pk), field_name],
            )
            if getattr(draft, field_name)
            else ""
        )
        for field_name in ("id_front", "id_back")
    }
    return JsonResponse(
        {
            "ok": True,
            "id": str(draft.pk),
            "revision": draft.revision,
            "updated_at": timezone.localtime(draft.updated_at).strftime("%H:%M"),
            "edit_url": f"{reverse('order_create')}?draft={draft.pk}",
            "photos": photo_urls,
        }
    )


@login_required
def draft_delete(request, pk):
    if request.method != "POST":
        return redirect(f"{reverse('order_create')}?draft={pk}")
    draft = get_object_or_404(OrderDraft, pk=pk)
    draft.delete_with_files()
    messages.success(request, "草稿與暫存證件照片已刪除。")
    return redirect("dashboard")


@login_required
@transaction.atomic
def draft_presence(request, pk):
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "僅接受 POST。"}, status=405)

    if not request.session.session_key:
        request.session.create()
    session_key = request.session.session_key
    draft = get_object_or_404(OrderDraft.objects.select_for_update(), pk=pk)
    now = timezone.now()
    is_active = bool(
        draft.editing_session
        and draft.editing_at
        and draft.editing_at >= now - DRAFT_PRESENCE_TIMEOUT
    )
    is_current_session = draft.editing_session == session_key

    if request.POST.get("action") == "release":
        if is_current_session:
            draft.editing_session = ""
            draft.editing_by = ""
            draft.editing_at = None
            draft.save(
                update_fields=[
                    "editing_session",
                    "editing_by",
                    "editing_at",
                ]
            )
        return JsonResponse({"ok": True, "active": False})

    if is_active and not is_current_session:
        return JsonResponse(
            {
                "ok": True,
                "active": True,
                "mine": False,
                "editing_by": draft.editing_by or "其他人員",
            }
        )

    draft.editing_session = session_key
    draft.editing_by = _editing_name(request.user)
    draft.editing_at = now
    draft.save(
        update_fields=[
            "editing_session",
            "editing_by",
            "editing_at",
        ]
    )
    return JsonResponse(
        {
            "ok": True,
            "active": True,
            "mine": True,
            "editing_by": draft.editing_by,
        }
    )


@login_required
def order_detail(request, pk):
    order = get_object_or_404(
        SalesOrder.objects.select_related(
            "source",
            "vehicle_model",
            "color",
            "allocated_vehicle",
            "allocated_vehicle__location_store",
        ).prefetch_related("accessories", "other_fees", "events"),
        pk=pk,
    )
    return render(
        request,
        "sales/order_detail.html",
        {
            "order": order,
            "contract_form": SignedContractForm(instance=order),
            "allocation_form": AllocationForm(order),
        },
    )


@login_required
def contract_print(request, pk):
    order = get_object_or_404(
        SalesOrder.objects.select_related(
            "source", "vehicle_model", "color"
        ).prefetch_related("accessories", "other_fees"),
        pk=pk,
    )
    pdf = build_order_contract_pdf(order)
    response = FileResponse(
        BytesIO(pdf),
        content_type="application/pdf",
        filename=f"{order.number}.pdf",
    )
    response["Content-Disposition"] = (
        f'inline; filename="{order.number}.pdf"; '
        f"filename*=UTF-8''{order.number}%E8%A8%82%E8%B3%BC%E5%96%AE.pdf"
    )
    return response


@login_required
def contract_upload(request, pk):
    order = get_object_or_404(SalesOrder, pk=pk)
    if request.method != "POST":
        return redirect("order_detail", pk=pk)
    form = SignedContractForm(request.POST, request.FILES, instance=order)
    if form.is_valid():
        order = form.save(commit=False)
        order.status = SalesOrder.Status.ALLOCATION_PENDING
        order.save()
        OrderEvent.objects.create(
            order=order,
            event_type="contract_uploaded",
            description="已上傳簽署合約，訂單進入待配車。",
            actor_name=request.user.get_username(),
        )
        messages.success(request, "已上傳簽署合約，現在可以進行配車。")
    else:
        messages.error(request, "合約上傳失敗，請確認檔案格式。")
    return redirect("order_detail", pk=pk)


@login_required
def allocate_vehicle(request, pk):
    order = get_object_or_404(SalesOrder, pk=pk)
    if request.method != "POST":
        return redirect("order_detail", pk=pk)
    form = AllocationForm(order, request.POST)
    if form.is_valid():
        try:
            order.allocate(form.cleaned_data["vehicle"])
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
        else:
            OrderEvent.objects.create(
                order=order,
                event_type="allocated",
                description=f"已配車：{order.allocated_vehicle}",
                actor_name=request.user.get_username(),
            )
            messages.success(request, "配車完成，實體車輛已鎖定。")
    else:
        messages.error(request, "請選擇可用的實體車輛。")
    return redirect("order_detail", pk=pk)


@login_required
def inventory_list(request):
    vehicles = VehicleInventory.objects.select_related(
        "vehicle_model", "color", "ownership_store", "location_store"
    )
    return render(
        request,
        "sales/inventory_list.html",
        {"vehicles": vehicles[:300], "statuses": VehicleInventory.Status.choices},
    )


@login_required
def inventory_create(request):
    if request.method == "POST":
        form = VehicleInventoryForm(request.POST, request.FILES)
        if form.is_valid():
            vehicle = form.save()
            messages.success(request, f"已建立庫存車輛：{vehicle.identifier}")
            return redirect("inventory_list")
    else:
        form = VehicleInventoryForm()
    return render(request, "sales/inventory_form.html", {"form": form})


@login_required
def vehicle_colors(request):
    model_id = request.GET.get("model")
    colors = VehicleColor.objects.filter(
        vehicle_model_id=model_id, active=True
    ).values("id", "name")
    return JsonResponse({"results": list(colors)})


@login_required
def sales_sources(request):
    source_type = request.GET.get("type")
    sources = SalesSource.objects.filter(
        source_type=source_type, active=True
    ).values("id", "name")
    return JsonResponse({"results": list(sources)})


@login_required
def id_card_ocr(request):
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "僅接受 POST。"}, status=405)
    front = request.FILES.get("front")
    back = request.FILES.get("back")
    if not front or not back:
        return JsonResponse(
            {"ok": False, "error": "請先拍攝身分證正面與反面。"},
            status=400,
        )
    allowed_content_types = {"image/jpeg", "image/png", "image/webp"}
    if (
        front.content_type not in allowed_content_types
        or back.content_type not in allowed_content_types
    ):
        return JsonResponse(
            {"ok": False, "error": "照片僅支援 JPEG、PNG 或 WebP。"},
            status=400,
        )
    try:
        result = recognize_id_card(front.read(), back.read())
    except IdOcrError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=422)
    except Exception:
        logger.exception("身分證 OCR 發生未預期錯誤")
        return JsonResponse(
            {"ok": False, "error": "辨識服務暫時無法使用，請稍後再試。"},
            status=503,
        )
    return JsonResponse({"ok": True, **result})


@login_required
def protected_media(request, model_name, pk, field_name):
    allowed = {
        "order": (SalesOrder, {"id_front", "id_back", "signed_contract"}),
        "draft": (OrderDraft, {"id_front", "id_back"}),
        "vehicle": (VehicleInventory, {"condition_photo"}),
    }
    if model_name not in allowed or field_name not in allowed[model_name][1]:
        raise Http404
    model = allowed[model_name][0]
    instance = get_object_or_404(model, pk=pk)
    file_field = getattr(instance, field_name)
    if not file_field:
        raise Http404
    response = FileResponse(file_field.open("rb"))
    response["Content-Disposition"] = f'inline; filename="{file_field.name.split("/")[-1]}"'
    response["Cache-Control"] = "private, no-store"
    return response
