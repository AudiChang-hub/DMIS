import json
import logging
from datetime import timedelta
from io import BytesIO
from pathlib import Path

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
from .services.privacy_consent_pdf import build_privacy_consent_pdf

from .forms import (
    AccessoryFormSet,
    AllocationForm,
    OtherFeeFormSet,
    OrderEditForm,
    PrivacyConsentForm,
    RegistrationDocumentUploadForm,
    RegistrationStageForm,
    SalesOrderForm,
    SignedContractForm,
    SubsidyDataForm,
    SubsidyDocumentUploadForm,
    VehicleInventoryForm,
)
from .models import (
    OrderEvent,
    OrderChange,
    OrderDraft,
    RegistrationDocument,
    SalesOrder,
    SalesSource,
    SubsidyDocument,
    VehicleColor,
    VehicleInventory,
    VehicleModel,
)
from .services.id_ocr import IdOcrError, recognize_id_card
from .services.order_change_display import build_order_change_cards


logger = logging.getLogger(__name__)
DRAFT_PRESENCE_TIMEOUT = timedelta(seconds=90)
ORDER_PRESENCE_TIMEOUT = timedelta(seconds=90)


def _editing_name(user):
    return user.get_full_name() or user.get_username()


def _vehicle_rate_data():
    return {
        str(model.pk): {
            "energy_type": model.energy_type,
            "displacement_cc": model.displacement_cc,
        }
        for model in VehicleModel.objects.filter(active=True).only(
            "id", "energy_type", "displacement_cc"
        )
    }


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
        "allocation_pending": active.filter(
            status=SalesOrder.Status.ALLOCATION_PENDING
        )[:12],
        "in_progress": active.exclude(
            status__in=[
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
            order.status = SalesOrder.Status.ALLOCATION_PENDING
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
                description="建立訂單，進入待配車。",
                actor_name=request.user.get_username(),
            )
            if draft:
                draft.delete_with_files()
            messages.success(request, "訂單已建立並進入待配車。")
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
            "document_source": draft,
            "document_model": "draft",
            "vehicle_rate_data": _vehicle_rate_data(),
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
        ).prefetch_related(
            "accessories",
            "other_fees",
            "events",
            "changes",
            "registration_documents",
            "subsidy_documents",
        ),
        pk=pk,
    )
    registration_documents = {
        document.document_type: document
        for document in order.registration_documents.all()
        if document.document_type
        != RegistrationDocument.DocumentType.OTHER_INSURANCE
    }
    required_types = order.required_registration_document_types()
    registration_document_rows = [
        {
            "type": document_type,
            "label": label,
            "required": document_type in required_types,
            "document": registration_documents.get(document_type),
        }
        for document_type, label in RegistrationDocument.DocumentType.choices
        if document_type != RegistrationDocument.DocumentType.OTHER_INSURANCE
    ]
    subsidy_documents = {
        document.document_type: document
        for document in order.subsidy_documents.all()
    }
    subsidy_required_types = order.required_subsidy_document_types()
    subsidy_document_rows = [
        {
            "type": document_type,
            "label": label,
            "required": document_type in subsidy_required_types,
            "document": subsidy_documents.get(document_type),
        }
        for document_type, label in SubsidyDocument.DocumentType.choices
        if document_type != SubsidyDocument.DocumentType.OWNER_DECLARATION
        or document_type in subsidy_required_types
        or document_type in subsidy_documents
    ]
    return render(
        request,
        "sales/order_detail.html",
        {
            "order": order,
            "contract_form": SignedContractForm(instance=order),
            "privacy_consent_form": PrivacyConsentForm(instance=order),
            "allocation_form": AllocationForm(order),
            "registration_form": RegistrationStageForm(instance=order),
            "registration_document_rows": registration_document_rows,
            "other_insurance_documents": order.registration_documents.filter(
                document_type=RegistrationDocument.DocumentType.OTHER_INSURANCE
            ),
            "registration_missing": order.missing_registration_requirements(),
            "subsidy_document_rows": subsidy_document_rows,
            "subsidy_missing": order.missing_subsidy_requirements(),
            "subsidy_form": SubsidyDataForm(instance=order),
            "change_cards": build_order_change_cards(order.changes.all()),
        },
    )


def _order_snapshot(order):
    excluded = {
        "id",
        "created_at",
        "updated_at",
        "revision",
        "editing_session",
        "editing_by",
        "editing_at",
        "calculated_balance",
    }
    snapshot = {}
    for field in order._meta.concrete_fields:
        if field.name in excluded:
            continue
        value = field.value_from_object(order)
        snapshot[field.verbose_name] = str(value or "")
    snapshot["配件"] = [
        {
            "名稱": line.name,
            "數量": line.quantity,
            "類型": line.get_line_type_display(),
            "金額": str(line.amount),
            "安裝日期": str(line.installed_on or ""),
            "備註": line.note,
        }
        for line in order.accessories.all()
    ]
    snapshot["其他費用"] = [
        {"項目": line.name, "金額": str(line.amount)}
        for line in order.other_fees.all()
    ]
    return snapshot


def _snapshot_changes(before, after):
    return {
        key: {"before": before.get(key), "after": after.get(key)}
        for key in sorted(set(before) | set(after))
        if before.get(key) != after.get(key)
    }


@login_required
@transaction.atomic
def order_edit(request, pk):
    order = get_object_or_404(
        SalesOrder.objects.select_for_update(),
        pk=pk,
    )
    if not order.is_editable:
        messages.error(request, "此訂單已交車、完成或取消，內容已鎖定。")
        return redirect("order_detail", pk=pk)

    if request.method == "POST":
        try:
            submitted_revision = int(request.POST.get("_order_revision", 0))
        except (TypeError, ValueError):
            submitted_revision = 0
        if submitted_revision != order.revision:
            messages.error(request, "此訂單已被其他人更新，請重新載入後再修改。")
            return redirect("order_edit", pk=pk)

        before = _order_snapshot(order)
        balance_was_automatic = order.actual_balance == order.calculated_balance
        previous_actual_balance = order.actual_balance
        form = OrderEditForm(request.POST, request.FILES, instance=order)
        formset = AccessoryFormSet(request.POST, instance=order)
        fee_formset = OtherFeeFormSet(
            request.POST, instance=order, prefix="other_fees"
        )
        if form.is_valid() and formset.is_valid() and fee_formset.is_valid():
            order = form.save(commit=False)
            if (
                order.actual_balance != order.calculate_balance()
                and not order.balance_adjustment_reason
            ):
                order.balance_adjustment_reason = form.cleaned_data["change_reason"]
            order.revision += 1
            order.editing_session = ""
            order.editing_by = ""
            order.editing_at = None
            order.save()
            formset.save()
            fee_formset.save()
            order._prefetched_objects_cache = {}
            order.calculated_balance = order.calculate_balance()
            order.actual_balance = (
                order.calculated_balance
                if balance_was_automatic
                else previous_actual_balance
            )
            order.save(
                update_fields=[
                    "calculated_balance",
                    "actual_balance",
                    "revision",
                    "editing_session",
                    "editing_by",
                    "editing_at",
                    "updated_at",
                ]
            )
            after = _order_snapshot(order)
            changes = _snapshot_changes(before, after)
            reason = form.cleaned_data["change_reason"]
            OrderChange.objects.create(
                order=order,
                reason=reason,
                changes=changes,
                actor_name=_editing_name(request.user),
            )
            OrderEvent.objects.create(
                order=order,
                event_type="updated",
                description=f"修改訂單：{reason}（{len(changes)} 個項目）",
                actor_name=_editing_name(request.user),
            )
            messages.success(request, "訂單內容已更新，變更紀錄已保存。")
            return redirect("order_detail", pk=pk)
    else:
        form = OrderEditForm(instance=order)
        formset = AccessoryFormSet(instance=order)
        fee_formset = OtherFeeFormSet(instance=order, prefix="other_fees")

    return render(
        request,
        "sales/order_form.html",
        {
            "form": form,
            "formset": formset,
            "fee_formset": fee_formset,
            "editing_order": order,
            "document_source": order,
            "document_model": "order",
            "vehicle_rate_data": _vehicle_rate_data(),
        },
    )


@login_required
@transaction.atomic
def order_edit_presence(request, pk):
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "僅接受 POST。"}, status=405)
    if not request.session.session_key:
        request.session.create()
    order = get_object_or_404(SalesOrder.objects.select_for_update(), pk=pk)
    session_key = request.session.session_key
    now = timezone.now()
    mine = order.editing_session == session_key
    active = bool(
        order.editing_session
        and order.editing_at
        and order.editing_at >= now - ORDER_PRESENCE_TIMEOUT
    )
    if request.POST.get("action") == "release":
        if mine:
            order.editing_session = ""
            order.editing_by = ""
            order.editing_at = None
            order.save(
                update_fields=["editing_session", "editing_by", "editing_at"]
            )
        return JsonResponse({"ok": True, "active": False})
    if active and not mine:
        return JsonResponse(
            {
                "ok": True,
                "active": True,
                "mine": False,
                "editing_by": order.editing_by or "其他人員",
            }
        )
    order.editing_session = session_key
    order.editing_by = _editing_name(request.user)
    order.editing_at = now
    order.save(update_fields=["editing_session", "editing_by", "editing_at"])
    return JsonResponse(
        {"ok": True, "active": True, "mine": True, "editing_by": order.editing_by}
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
def privacy_consent_print(request, pk):
    order = get_object_or_404(SalesOrder, pk=pk)
    pdf = build_privacy_consent_pdf(order)
    response = FileResponse(
        BytesIO(pdf),
        content_type="application/pdf",
    )
    response["Content-Disposition"] = (
        f'inline; filename="{order.number}-privacy-consent.pdf"; '
        f"filename*=UTF-8''{order.number}%E5%80%8B%E8%B3%87%E5%90%8C%E6%84%8F%E6%9B%B8.pdf"
    )
    return response


@login_required
def order_documents_print(request, pk):
    from pypdf import PdfReader, PdfWriter

    order = get_object_or_404(
        SalesOrder.objects.select_related(
            "source", "vehicle_model", "color"
        ).prefetch_related("accessories", "other_fees"),
        pk=pk,
    )
    writer = PdfWriter()
    for content in (
        build_order_contract_pdf(order),
        build_privacy_consent_pdf(order),
    ):
        reader = PdfReader(BytesIO(content))
        for page in reader.pages:
            writer.add_page(page)
    output = BytesIO()
    writer.write(output)
    output.seek(0)
    response = FileResponse(output, content_type="application/pdf")
    response["Content-Disposition"] = (
        f'inline; filename="{order.number}-documents.pdf"; '
        f"filename*=UTF-8''{order.number}%E7%B0%BD%E7%BD%B2%E6%96%87%E4%BB%B6.pdf"
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
        order.signed_contract_uploaded_at = timezone.now()
        order.save()
        OrderEvent.objects.create(
            order=order,
            event_type="contract_uploaded",
            description="已上傳訂購合約附件歸檔。",
            actor_name=request.user.get_username(),
        )
        messages.success(request, "訂購合約附件已歸檔。")
    else:
        messages.error(request, "合約上傳失敗，請確認檔案格式。")
    return redirect("order_detail", pk=pk)


@login_required
def privacy_consent_upload(request, pk):
    order = get_object_or_404(SalesOrder, pk=pk)
    if request.method != "POST":
        return redirect("order_detail", pk=pk)
    form = PrivacyConsentForm(request.POST, request.FILES, instance=order)
    if form.is_valid():
        order = form.save(commit=False)
        order.privacy_consent_uploaded_at = timezone.now()
        order.save()
        OrderEvent.objects.create(
            order=order,
            event_type="privacy_consent_uploaded",
            description="已上傳個資同意書附件歸檔。",
            actor_name=request.user.get_username(),
        )
        messages.success(request, "個資同意書附件已歸檔。")
    else:
        messages.error(request, "個資同意書上傳失敗，請確認檔案格式。")
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
@transaction.atomic
def registration_save(request, pk):
    order = get_object_or_404(SalesOrder.objects.select_for_update(), pk=pk)
    if request.method != "POST":
        return redirect("order_detail", pk=pk)
    if order.is_registration_complete:
        messages.error(request, "此訂單已完成領牌，領牌資料已鎖定。")
        return redirect("order_detail", pk=pk)
    if not order.allocated_vehicle_id:
        messages.error(request, "請先完成配車，再填寫領牌資料。")
        return redirect("order_detail", pk=pk)
    form = RegistrationStageForm(request.POST, instance=order)
    if form.is_valid():
        order = form.save()
        OrderEvent.objects.create(
            order=order,
            event_type="registration_data_updated",
            description=(
                f"已更新領牌資料：{order.registration_date}／"
                f"{order.final_plate_number}"
            ),
            actor_name=_editing_name(request.user),
        )
        messages.success(request, "領牌日期與車牌號碼已保存。")
    else:
        messages.error(
            request,
            "領牌資料未保存：" + " ".join(
                error
                for errors in form.errors.values()
                for error in errors
            ),
        )
    return redirect("order_detail", pk=pk)


@login_required
@transaction.atomic
def registration_document_upload(request, pk):
    order = get_object_or_404(SalesOrder.objects.select_for_update(), pk=pk)
    if request.method != "POST":
        return redirect("order_detail", pk=pk)
    if not order.allocated_vehicle_id:
        messages.error(request, "請先完成配車，再上傳領牌文件。")
        return redirect("order_detail", pk=pk)
    if order.is_registration_complete or order.status in {
        SalesOrder.Status.COMPLETED,
        SalesOrder.Status.CANCELLED,
    }:
        messages.error(request, "此訂單的領牌階段已完成，無法修改文件。")
        return redirect("order_detail", pk=pk)
    form = RegistrationDocumentUploadForm(request.POST, request.FILES)
    if not form.is_valid():
        messages.error(
            request,
            "文件上傳失敗：" + " ".join(
                error
                for errors in form.errors.values()
                for error in errors
            ),
        )
        return redirect("order_detail", pk=pk)

    document = form.save(commit=False)
    document.order = order
    document.uploaded_by = _editing_name(request.user)
    if document.document_type != RegistrationDocument.DocumentType.OTHER_INSURANCE:
        existing = order.registration_documents.filter(
            document_type=document.document_type
        ).first()
        if existing:
            existing.delete_with_file()
    document.save()
    OrderEvent.objects.create(
        order=order,
        event_type="registration_document_uploaded",
        description=f"已上傳領牌文件：{document.display_name}",
        actor_name=_editing_name(request.user),
    )
    messages.success(request, f"{document.display_name}已上傳。")
    return redirect("order_detail", pk=pk)


@login_required
@transaction.atomic
def registration_document_delete(request, pk, document_pk):
    order = get_object_or_404(SalesOrder.objects.select_for_update(), pk=pk)
    if request.method != "POST":
        return redirect("order_detail", pk=pk)
    if order.is_registration_complete or order.status in {
        SalesOrder.Status.COMPLETED,
        SalesOrder.Status.CANCELLED,
    }:
        messages.error(request, "此訂單的領牌階段已完成，無法刪除文件。")
        return redirect("order_detail", pk=pk)
    document = get_object_or_404(
        RegistrationDocument,
        pk=document_pk,
        order=order,
    )
    display_name = document.display_name
    document.delete_with_file()
    OrderEvent.objects.create(
        order=order,
        event_type="registration_document_deleted",
        description=f"已刪除領牌文件：{display_name}",
        actor_name=_editing_name(request.user),
    )
    messages.success(request, f"{display_name}已刪除。")
    return redirect("order_detail", pk=pk)


@login_required
@transaction.atomic
def registration_complete(request, pk):
    order = get_object_or_404(SalesOrder.objects.select_for_update(), pk=pk)
    if request.method != "POST":
        return redirect("order_detail", pk=pk)
    if order.is_registration_complete:
        messages.info(request, "此訂單已完成領牌。")
        return redirect("order_detail", pk=pk)
    try:
        order.complete_registration(_editing_name(request.user))
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    else:
        OrderEvent.objects.create(
            order=order,
            event_type="registration_completed",
            description=(
                f"領牌完成：{order.registration_date}／"
                f"{order.final_plate_number}"
            ),
            actor_name=_editing_name(request.user),
        )
        messages.success(request, "領牌階段已完成，訂單進入待交付。")
    return redirect("order_detail", pk=pk)


@login_required
def registration_document_file(request, document_pk):
    document = get_object_or_404(RegistrationDocument, pk=document_pk)
    if not document.file:
        raise Http404
    response = FileResponse(
        document.file.open("rb"),
        as_attachment=False,
        filename=Path(document.file.name).name,
    )
    response["Cache-Control"] = "private, no-store"
    return response


@login_required
@transaction.atomic
def subsidy_document_upload(request, pk):
    order = get_object_or_404(SalesOrder.objects.select_for_update(), pk=pk)
    if request.method != "POST":
        return redirect("order_detail", pk=pk)
    if order.status == SalesOrder.Status.CANCELLED:
        messages.error(request, "已取消訂單無法修改補助文件。")
        return redirect("order_detail", pk=pk)
    if not order.is_trade_in_subsidy:
        messages.error(request, "此訂單未勾選汰舊／政府補助。")
        return redirect("order_detail", pk=pk)
    form = SubsidyDocumentUploadForm(request.POST, request.FILES)
    if not form.is_valid():
        messages.error(
            request,
            "補助文件上傳失敗：" + " ".join(
                error
                for errors in form.errors.values()
                for error in errors
            ),
        )
        return redirect("order_detail", pk=pk)

    document = form.save(commit=False)
    document.order = order
    document.uploaded_by = _editing_name(request.user)
    existing = order.subsidy_documents.filter(
        document_type=document.document_type
    ).first()
    if existing:
        old_file = existing.file
        existing.file = document.file
        existing.uploaded_by = document.uploaded_by
        existing.save(update_fields=["file", "uploaded_by", "updated_at"])
        if old_file:
            old_file.delete(save=False)
        document = existing
    else:
        document.save()
    OrderEvent.objects.create(
        order=order,
        event_type="subsidy_document_uploaded",
        description=f"已上傳補助文件：{document.get_document_type_display()}",
        actor_name=_editing_name(request.user),
    )
    messages.success(request, f"{document.get_document_type_display()}已上傳。")
    return redirect("order_detail", pk=pk)


@login_required
@transaction.atomic
def subsidy_document_delete(request, pk, document_pk):
    order = get_object_or_404(SalesOrder.objects.select_for_update(), pk=pk)
    if request.method != "POST":
        return redirect("order_detail", pk=pk)
    if order.status == SalesOrder.Status.CANCELLED:
        messages.error(request, "已取消訂單無法修改補助文件。")
        return redirect("order_detail", pk=pk)
    document = get_object_or_404(
        SubsidyDocument,
        pk=document_pk,
        order=order,
    )
    display_name = document.get_document_type_display()
    document.delete_with_file()
    OrderEvent.objects.create(
        order=order,
        event_type="subsidy_document_deleted",
        description=f"已刪除補助文件：{display_name}",
        actor_name=_editing_name(request.user),
    )
    messages.success(request, f"{display_name}已刪除。")
    return redirect("order_detail", pk=pk)


@login_required
def subsidy_document_file(request, document_pk):
    document = get_object_or_404(SubsidyDocument, pk=document_pk)
    if not document.file:
        raise Http404
    response = FileResponse(
        document.file.open("rb"),
        as_attachment=False,
        filename=Path(document.file.name).name,
    )
    response["Cache-Control"] = "private, no-store"
    return response


@login_required
@transaction.atomic
def subsidy_data_update(request, pk):
    order = get_object_or_404(SalesOrder.objects.select_for_update(), pk=pk)
    detail_url = f"{reverse('order_detail', args=[pk])}?tab=subsidy"
    if request.method != "POST":
        return redirect(detail_url)
    if not order.is_editable:
        messages.error(request, "此訂單已交車、完成或取消，補助資料已鎖定。")
        return redirect(detail_url)
    try:
        submitted_revision = int(request.POST.get("_order_revision", 0))
    except (TypeError, ValueError):
        submitted_revision = 0
    if submitted_revision != order.revision:
        messages.error(request, "此訂單已被其他人更新，請重新確認補助資料。")
        return redirect(detail_url)

    before = _order_snapshot(order)
    balance_was_automatic = order.actual_balance == order.calculated_balance
    previous_actual_balance = order.actual_balance
    form = SubsidyDataForm(request.POST, instance=order)
    if not form.is_valid():
        messages.error(
            request,
            "補助資料未保存：" + " ".join(
                error
                for errors in form.errors.values()
                for error in errors
            ),
        )
        return redirect(detail_url)

    order = form.save(commit=False)
    order.revision += 1
    order.calculated_balance = order.calculate_balance()
    if balance_was_automatic:
        order.actual_balance = order.calculated_balance
    else:
        order.actual_balance = previous_actual_balance
        if order.actual_balance != order.calculated_balance:
            order.balance_adjustment_reason = form.cleaned_data["change_reason"]
    order.save()

    after = _order_snapshot(order)
    changes = _snapshot_changes(before, after)
    reason = form.cleaned_data["change_reason"]
    OrderChange.objects.create(
        order=order,
        reason=reason,
        changes=changes,
        actor_name=_editing_name(request.user),
    )
    OrderEvent.objects.create(
        order=order,
        event_type="subsidy_data_updated",
        description=f"修改補助資料：{reason}（{len(changes)} 個項目）",
        actor_name=_editing_name(request.user),
    )
    messages.success(request, "補助資料已更新，尾款與變更紀錄已同步。")
    return redirect(detail_url)


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
        "order": (
            SalesOrder,
            {"id_front", "id_back", "signed_contract", "privacy_consent"},
        ),
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
