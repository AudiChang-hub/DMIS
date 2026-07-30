import json
import logging
import uuid
from datetime import timedelta
from io import BytesIO
from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.files.base import ContentFile
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.core.paginator import Paginator
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from PIL import Image, UnidentifiedImageError
import django_rq
from rq import Retry

from .services.order_contract_pdf import build_order_contract_pdf
from .services.privacy_consent_pdf import build_privacy_consent_pdf

from .forms import (
    AccessoryFormSet,
    AllocationForm,
    OtherFeeFormSet,
    OrderOperationsForm,
    OrderEditForm,
    PrivacyConsentForm,
    PaymentRecordFormSet,
    QuickInventoryEntryFormSet,
    ReallocationForm,
    RegistrationDocumentUploadForm,
    RegistrationStageForm,
    SalesOrderForm,
    SignedContractForm,
    SubsidyDataForm,
    SubsidyDocumentUploadForm,
    VehicleInventoryForm,
    VehicleColorMasterFormSet,
    VehicleModelMasterForm,
)
from .models import (
    OrderEvent,
    OrderOperationsProfile,
    PaymentRecord,
    OrderChange,
    OrderDraft,
    IdOcrJob,
    RegistrationDocument,
    SalesOrder,
    SalesSource,
    Store,
    SubsidyDocument,
    VehicleColor,
    VehicleInventory,
    VehicleInventoryHistory,
    VehicleModel,
)
from .jobs import delete_id_ocr_job_files, run_id_ocr_job
from .services.id_ocr import recognize_id_card
from .services.order_change_display import build_order_change_cards
from .services.order_search import (
    build_order_match_summary,
    build_order_search_query,
)
from .services.secret_fields import decrypt_secret, encrypt_secret


logger = logging.getLogger(__name__)
DRAFT_PRESENCE_TIMEOUT = timedelta(seconds=90)
ORDER_PRESENCE_TIMEOUT = timedelta(seconds=90)


def _editing_name(user):
    return user.get_full_name() or user.get_username()


INVENTORY_HISTORY_FIELDS = {
    "vehicle_model": "車型",
    "color": "車色",
    "engine_number": "引擎號碼",
    "frame_number": "車身號碼",
    "location_store": "實際位置",
    "received_on": "進車日期",
    "condition_note": "車況說明",
    "condition_photo": "車況照片",
    "condition_resolution": "處理結果",
    "acquisition_cost": "進貨成本",
}


def _inventory_values(vehicle):
    return {
        "vehicle_model": (vehicle.vehicle_model_id, str(vehicle.vehicle_model)),
        "color": (vehicle.color_id, vehicle.color.name),
        "engine_number": (vehicle.engine_number or "", vehicle.engine_number or "未填寫"),
        "frame_number": (vehicle.frame_number or "", vehicle.frame_number or "未填寫"),
        "location_store": (vehicle.location_store_id, str(vehicle.location_store)),
        "received_on": (str(vehicle.received_on), str(vehicle.received_on)),
        "condition_note": (vehicle.condition_note, vehicle.condition_note or "未填寫"),
        "condition_photo": (
            vehicle.condition_photo.name if vehicle.condition_photo else "",
            "有照片" if vehicle.condition_photo else "無照片",
        ),
        "condition_resolution": (
            vehicle.condition_resolution,
            vehicle.condition_resolution or "未填寫",
        ),
        "acquisition_cost": (
            vehicle.acquisition_cost,
            str(vehicle.acquisition_cost)
            if vehicle.acquisition_cost is not None
            else "未填寫",
        ),
    }


def _create_inventory_history(
    vehicle,
    *,
    actor_name,
    event_type,
    reason="",
    changes=None,
    from_location_id=None,
    to_location_id=None,
):
    history = VehicleInventoryHistory(
        vehicle=vehicle,
        event_type=event_type,
        actor_name=actor_name,
        reason=reason,
        changes=changes or {},
        status_snapshot=vehicle.status,
        location_store_snapshot_id=vehicle.location_store_id,
        condition_note_snapshot=vehicle.condition_note,
        condition_resolution_snapshot=vehicle.condition_resolution,
        from_location_id=from_location_id,
        to_location_id=to_location_id,
    )
    if vehicle.condition_photo:
        vehicle.condition_photo.open("rb")
        try:
            content = ContentFile(vehicle.condition_photo.read())
        finally:
            vehicle.condition_photo.close()
        suffix = Path(vehicle.condition_photo.name).suffix or ".jpg"
        history.condition_photo_snapshot.save(
            f"{uuid.uuid4().hex}{suffix}", content, save=False
        )
    history.save()
    return history


def _session_key(request):
    if not request.session.session_key:
        request.session.create()
    return request.session.session_key


def _claim_edit_lock(instance, request, timeout):
    session_key = _session_key(request)
    now = timezone.now()
    active_elsewhere = bool(
        instance.editing_session
        and instance.editing_session != session_key
        and instance.editing_at
        and instance.editing_at >= now - timeout
    )
    if active_elsewhere:
        return False
    instance.editing_session = session_key
    instance.editing_by = _editing_name(request.user)
    instance.editing_at = now
    instance.save(
        update_fields=["editing_session", "editing_by", "editing_at"]
    )
    return True


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
        "source",
        "vehicle_model",
        "color",
        "allocated_vehicle",
        "allocated_vehicle__ownership_store",
        "allocated_vehicle__location_store",
        "search_index",
    ).prefetch_related(
        "accessories",
        "other_fees",
        "subsidy_documents",
        "registration_documents",
        "events",
        "changes",
    )
    search_results = None
    search_result_count = 0
    if query:
        matched_orders = orders.filter(build_order_search_query(query)).distinct()
        paginator = Paginator(matched_orders, 50)
        search_results = paginator.get_page(request.GET.get("page"))
        search_result_count = paginator.count
        for order in search_results:
            order.search_matches = build_order_match_summary(order, query)

    active = SalesOrder.objects.select_related(
        "source", "vehicle_model", "color", "allocated_vehicle"
    ).exclude(
        status__in=[SalesOrder.Status.COMPLETED, SalesOrder.Status.CANCELLED]
    )
    urgent_statuses = [
        SalesOrder.Status.CANCEL_REFUND_PENDING,
        SalesOrder.Status.DELIVERED_DOCS_PENDING,
    ]
    in_progress_orders = active.exclude(
        status__in=[SalesOrder.Status.ALLOCATION_PENDING, *urgent_statuses]
    )
    context = {
        "query": query,
        "search_results": search_results,
        "search_result_count": search_result_count,
        "urgent_orders": active.filter(status__in=urgent_statuses)[:12],
        "allocation_pending": active.filter(
            status=SalesOrder.Status.ALLOCATION_PENDING
        )[:12],
        "in_progress": in_progress_orders[:12],
        "counts": {
            "urgent": active.filter(status__in=urgent_statuses).count(),
            "allocation": active.filter(
                status=SalesOrder.Status.ALLOCATION_PENDING
            ).count(),
            "in_progress": in_progress_orders.count(),
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
    if status == "in_progress":
        orders = orders.exclude(
            status__in=[
                SalesOrder.Status.ALLOCATION_PENDING,
                SalesOrder.Status.CANCEL_REFUND_PENDING,
                SalesOrder.Status.DELIVERED_DOCS_PENDING,
                SalesOrder.Status.COMPLETED,
                SalesOrder.Status.CANCELLED,
            ]
        )
    elif status == "urgent":
        orders = orders.filter(
            status__in=[
                SalesOrder.Status.CANCEL_REFUND_PENDING,
                SalesOrder.Status.DELIVERED_DOCS_PENDING,
            ]
        )
    elif status:
        orders = orders.filter(status=status)
    return render(
        request,
        "sales/order_list.html",
        {"orders": orders[:200], "statuses": SalesOrder.Status.choices},
    )


def _operations_report_queryset(request):
    rows = SalesOrder.objects.select_related(
        "vehicle_model", "color", "allocated_vehicle", "operations", "source"
    ).prefetch_related("payment_records")
    keyword = request.GET.get("q", "").strip()
    if keyword:
        rows = rows.filter(build_order_search_query(keyword)).distinct()
    energy_type = request.GET.get("energy_type", "")
    if energy_type in {value for value, _ in VehicleModel.EnergyType.choices}:
        rows = rows.filter(vehicle_model__energy_type=energy_type)
    payment_status = request.GET.get("payment_status", "")
    if payment_status == "confirmed":
        rows = rows.filter(operations__payment_confirmed=True)
    elif payment_status == "pending":
        rows = rows.exclude(operations__payment_confirmed=True)
    if request.GET.get("date_from"):
        rows = rows.filter(order_date__gte=request.GET["date_from"])
    if request.GET.get("date_to"):
        rows = rows.filter(order_date__lte=request.GET["date_to"])
    return rows.order_by("-order_date", "-id")


@login_required
def operations_report(request):
    paginator = Paginator(_operations_report_queryset(request), 100)
    page = paginator.get_page(request.GET.get("page"))
    for order in page.object_list:
        order.operation_data = getattr(order, "operations", None)
    return render(
        request,
        "sales/operations_report.html",
        {
            "orders": page.object_list,
            "page_obj": page,
            "energy_types": VehicleModel.EnergyType.choices,
            "selected": request.GET,
        },
    )


@login_required
def operations_report_export(request):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "營運總表"
    headers = [
        "訂單編號", "訂單日期", "車種", "型號", "型式", "顏色", "引擎／車身號碼",
        "車主名稱", "車牌號碼", "車款售價", "實際撥款", "成本",
        "總收款金額", "確認收款", "分期公司", "期數", "每期金額",
        "分期公司確認匯款", "身分證字號", "西元生日", "民國生日",
        "戶籍地址", "手機", "Email", "自送托運地點", "發票日期",
        "尾款發票號碼", "補助方案", "補助金額", "銀行", "匯款帳戶",
        "申請日", "工業局", "環境部", "縣市政府", "舊車車主",
        "舊車車主身分證", "舊車牌照號碼", "舊車引擎號碼", "舊車廠牌",
        "排氣量", "出廠日期", "報廢日期", "回收日期",
        "領牌稅金支出", "強制險支出", "選號支出", "贈品、運費支出",
        "車行傭金支出", "分期補貼息", "領牌稅金收入", "強制險收入",
        "代辦費收入", "選號收入", "分期手續費收入", "刷卡手續費收入",
        "其他收入", "實銷獎勵金", "促銷補助金", "強制險傭金",
        "信用卡傭金", "車控帳號", "電池合約方案", "電池合約啟用日期",
        "電池合約帳號", "安全帽", "公司禮券、匯款", "其他",
        "平台贈品", "客服電話", "分期資訊", "車行",
        "總收入", "總支出", "單筆淨利",
    ]
    sheet.append(headers)
    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="174C3C")
    for order in _operations_report_queryset(request):
        profile = getattr(order, "operations", None)
        roc_birth = ""
        if order.owner_birth_date:
            roc_birth = (
                f"{order.owner_birth_date.year - 1911}/"
                f"{order.owner_birth_date.month:02d}/{order.owner_birth_date.day:02d}"
            )
        def op(name, default=""):
            return getattr(profile, name, default) if profile else default
        sheet.append([
            order.number, order.order_date, order.vehicle_model.name,
            order.vehicle_model.model_number,
            order.vehicle_model.get_model_code_display()
            if order.vehicle_model.model_code else "",
            order.color.name,
            order.allocated_vehicle.identifier if order.allocated_vehicle else "",
            order.owner_name, order.final_plate_number, order.vehicle_price,
            op("actual_disbursement", 0), op("vehicle_cost", 0),
            profile.total_received if profile else 0,
            "是" if op("payment_confirmed", False) else "否",
            order.installment_company, order.installment_periods,
            order.installment_monthly,
            "是" if op("installment_transfer_confirmed", False) else "否",
            order.owner_id_number, order.owner_birth_date, roc_birth,
            order.owner_address, order.owner_phone, order.owner_email,
            order.delivery_destination, op("invoice_date"),
            op("balance_invoice_number"), order.subsidy_type,
            op("subsidy_amount", 0), op("bank_name"), op("remittance_account"),
            op("subsidy_applied_on"),
            profile.get_industry_bureau_status_display() if profile else "",
            profile.get_environment_ministry_status_display() if profile else "",
            profile.get_local_government_status_display() if profile else "",
            order.old_owner_name, order.old_owner_id_number, order.trade_in_plate,
            op("old_vehicle_engine_number"), op("old_vehicle_brand"),
            op("old_vehicle_displacement_cc"), op("old_vehicle_manufactured_on"),
            op("scrapped_on"), op("recycled_on"),
            op("registration_tax_expense", 0),
            op("compulsory_insurance_expense", 0),
            op("plate_selection_expense", 0),
            op("gift_shipping_expense", 0),
            op("dealer_commission_expense", 0),
            op("installment_interest_subsidy", 0),
            op("registration_tax_income", 0),
            op("compulsory_insurance_income", 0),
            op("agency_fee_income", 0),
            op("plate_selection_income", 0),
            op("installment_fee_income", 0),
            op("card_fee_income", 0),
            op("other_income", 0), op("sales_bonus", 0),
            op("promotion_subsidy", 0), op("insurance_commission", 0),
            op("credit_card_commission", 0), op("vehicle_control_account"),
            op("battery_plan"), op("battery_activated_on"),
            op("battery_account"), op("helmet"),
            op("company_gift_or_remittance"), op("other_fulfillment"),
            op("platform_gift"), op("customer_service_phone"),
            op("installment_info"), op("dealer_name"),
            profile.total_income if profile else order.vehicle_price,
            profile.total_expense if profile else 0,
            profile.net_profit if profile else order.vehicle_price,
        ])
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    for column in sheet.columns:
        sheet.column_dimensions[column[0].column_letter].width = min(
            max(len(str(cell.value or "")) for cell in column) + 2, 28
        )
    output = BytesIO()
    workbook.save(output)
    response = HttpResponse(
        output.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = 'attachment; filename="operations-report.xlsx"'
    return response


@login_required
@transaction.atomic
def order_create(request):
    draft_id = request.POST.get("_draft_id") or request.GET.get("draft")
    draft = (
        get_object_or_404(OrderDraft.objects.select_for_update(), pk=draft_id)
        if draft_id
        else None
    )
    if draft and not _claim_edit_lock(draft, request, DRAFT_PRESENCE_TIMEOUT):
        messages.error(
            request,
            f"此草稿目前由 {draft.editing_by or '其他人員'} 編輯，暫時無法進入。",
        )
        return redirect("dashboard")
    existing_documents = {
        "id_front": bool(draft and draft.id_front),
        "id_back": bool(draft and draft.id_back),
    }
    if request.method == "POST":
        post_data = request.POST
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
        if not _claim_edit_lock(draft, request, DRAFT_PRESENCE_TIMEOUT):
            return JsonResponse(
                {
                    "ok": False,
                    "locked": True,
                    "error": f"此草稿目前由 {draft.editing_by or '其他人員'} 編輯。",
                },
                status=423,
            )
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
        draft = OrderDraft(
            created_by=request.user.get_username(),
            editing_session=_session_key(request),
            editing_by=_editing_name(request.user),
            editing_at=timezone.now(),
        )

    excluded = {
        "csrfmiddlewaretoken",
        "_draft_id",
        "_draft_revision",
        "_remove_id_front",
        "_remove_id_back",
        "_field_versions",
    }
    draft.data = {
        key: values if len(values) > 1 else values[0]
        for key, values in request.POST.lists()
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
@transaction.atomic
def draft_delete(request, pk):
    if request.method != "POST":
        if request.headers.get("Accept") == "application/json":
            return JsonResponse(
                {"ok": False, "error": "刪除草稿僅接受 POST。"},
                status=405,
            )
        return redirect(f"{reverse('order_create')}?draft={pk}")
    draft = get_object_or_404(OrderDraft.objects.select_for_update(), pk=pk)
    if not _claim_edit_lock(draft, request, DRAFT_PRESENCE_TIMEOUT):
        error = f"此草稿目前由 {draft.editing_by or '其他人員'} 編輯，無法刪除。"
        if request.headers.get("Accept") == "application/json":
            return JsonResponse({"ok": False, "error": error}, status=423)
        messages.error(
            request,
            error,
        )
        return redirect("dashboard")
    draft.delete_with_files()
    if request.headers.get("Accept") == "application/json":
        messages.success(request, "草稿與暫存證件照片已刪除。")
        return JsonResponse({"ok": True, "redirect_url": reverse("dashboard")})
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
        if document_type != SubsidyDocument.DocumentType.OTHER
        and (
            document_type
            not in {
                SubsidyDocument.DocumentType.OWNER_DECLARATION,
                SubsidyDocument.DocumentType.OLD_OWNER_BANKBOOK,
            }
            or document_type in subsidy_required_types
            or document_type in subsidy_documents
        )
    ]
    operations_profile = getattr(order, "operations", None)
    return render(
        request,
        "sales/order_detail.html",
        {
            "order": order,
            "contract_form": SignedContractForm(instance=order),
            "privacy_consent_form": PrivacyConsentForm(instance=order),
            "allocation_form": AllocationForm(order),
            "reallocation_form": ReallocationForm(order),
            "registration_form": RegistrationStageForm(instance=order),
            "registration_document_rows": registration_document_rows,
            "other_insurance_documents": order.registration_documents.filter(
                document_type=RegistrationDocument.DocumentType.OTHER_INSURANCE
            ),
            "registration_missing": order.missing_registration_requirements(),
            "subsidy_document_rows": subsidy_document_rows,
            "other_subsidy_documents": order.subsidy_documents.filter(
                document_type=SubsidyDocument.DocumentType.OTHER
            ),
            "subsidy_missing": order.missing_subsidy_requirements(),
            "subsidy_form": SubsidyDataForm(instance=order),
            "change_cards": build_order_change_cards(order.changes.all()),
            "operations_profile": operations_profile,
        },
    )


def _operations_snapshot(profile):
    values = {}
    for field in profile._meta.fields:
        if field.name in {
            "id", "order", "created_at", "updated_at", "updated_by",
            "vehicle_control_password_encrypted", "battery_password_encrypted",
        }:
            continue
        value = getattr(profile, field.name)
        values[field.name] = "" if value is None else str(value)
    return values


@login_required
def order_operations(request, pk):
    order = get_object_or_404(
        SalesOrder.objects.select_related(
            "vehicle_model", "color", "allocated_vehicle"
        ),
        pk=pk,
    )
    profile, created = OrderOperationsProfile.objects.get_or_create(order=order)
    if created and order.allocated_vehicle and order.allocated_vehicle.acquisition_cost:
        profile.vehicle_cost = order.allocated_vehicle.acquisition_cost
        profile.save(update_fields=["vehicle_cost", "updated_at"])
    before = _operations_snapshot(profile)
    form = OrderOperationsForm(
        request.POST or None,
        instance=profile,
        prefix="operations",
    )
    payment_formset = PaymentRecordFormSet(
        request.POST or None,
        request.FILES or None,
        instance=order,
        prefix="payments",
    )
    if request.method == "POST" and form.is_valid() and payment_formset.is_valid():
        with transaction.atomic():
            profile = form.save(commit=False)
            vehicle_secret = form.cleaned_data.get("vehicle_control_password")
            battery_secret = form.cleaned_data.get("battery_password")
            if vehicle_secret:
                profile.vehicle_control_password_encrypted = encrypt_secret(
                    vehicle_secret
                )
            if battery_secret:
                profile.battery_password_encrypted = encrypt_secret(battery_secret)
            profile.updated_by = _editing_name(request.user)
            profile.save()
            payments = payment_formset.save()
            now = timezone.now()
            for payment in payments:
                if payment.confirmed and not payment.confirmed_at:
                    payment.confirmed_at = now
                    payment.confirmed_by = _editing_name(request.user)
                    payment.save(
                        update_fields=[
                            "confirmed_at", "confirmed_by", "updated_at"
                        ]
                    )
            after = _operations_snapshot(profile)
            changes = {
                key: {"before": before.get(key, ""), "after": value}
                for key, value in after.items()
                if before.get(key, "") != value
            }
            OrderChange.objects.create(
                order=order,
                reason=form.cleaned_data.get("change_reason")
                or "更新營運與對帳資料",
                changes=changes,
                actor_name=_editing_name(request.user),
            )
            OrderEvent.objects.create(
                order=order,
                event_type="operations_updated",
                description=f"更新營運與對帳資料（{len(changes)} 個欄位）",
                actor_name=_editing_name(request.user),
            )
        messages.success(request, "營運、收款及損益資料已更新。")
        return redirect("order_operations", pk=order.pk)
    return render(
        request,
        "sales/order_operations.html",
        {
            "order": order,
            "profile": profile,
            "form": form,
            "payment_formset": payment_formset,
            "is_electric": order.vehicle_model.energy_type
            != VehicleModel.EnergyType.GAS,
        },
    )


@login_required
def order_secret_reveal(request, pk):
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "僅接受 POST。"}, status=405)
    order = get_object_or_404(SalesOrder, pk=pk)
    profile = get_object_or_404(OrderOperationsProfile, order=order)
    field = request.POST.get("field")
    encrypted_fields = {
        "vehicle_control_password": profile.vehicle_control_password_encrypted,
        "battery_password": profile.battery_password_encrypted,
    }
    if field not in encrypted_fields:
        return JsonResponse({"ok": False, "error": "不支援的欄位。"}, status=400)
    value = decrypt_secret(encrypted_fields[field])
    OrderEvent.objects.create(
        order=order,
        event_type="secret_viewed",
        description=f"查看{'車控' if field == 'vehicle_control_password' else '電池合約'}密碼",
        actor_name=_editing_name(request.user),
    )
    return JsonResponse({"ok": True, "value": value})


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
        "old_owner_ocr_name",
        "old_owner_ocr_id_number",
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
    if not _claim_edit_lock(order, request, ORDER_PRESENCE_TIMEOUT):
        messages.error(
            request,
            f"此訂單目前由 {order.editing_by or '其他人員'} 編輯，暫時只能查看。",
        )
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
def reallocate_vehicle(request, pk):
    order = get_object_or_404(
        SalesOrder.objects.select_for_update(),
        pk=pk,
    )
    detail_url = f"{reverse('order_detail', args=[pk])}?tab=allocation"
    if request.method != "POST":
        return redirect(detail_url)
    if order.has_registration_started:
        messages.error(
            request,
            "已有車牌號碼、領牌完成紀錄或領牌文件，為避免車輛與文件對錯，無法直接改配。",
        )
        return redirect(detail_url)

    form = ReallocationForm(order, request.POST)
    if not form.is_valid():
        messages.error(
            request,
            "改配未完成：" + " ".join(
                error
                for errors in form.errors.values()
                for error in errors
            ),
        )
        return redirect(detail_url)
    try:
        original, replacement = order.reallocate(
            form.cleaned_data["vehicle"]
        )
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
        return redirect(detail_url)

    reason = form.cleaned_data["reason"]
    OrderChange.objects.create(
        order=order,
        reason=reason,
        changes={
            "已配車輛": {
                "before": str(original),
                "after": str(replacement),
            }
        },
        actor_name=_editing_name(request.user),
    )
    OrderEvent.objects.create(
        order=order,
        event_type="reallocated",
        description=f"改配車輛：{original} → {replacement}；原因：{reason}",
        actor_name=_editing_name(request.user),
    )
    messages.success(request, f"改配完成，新配車輛為 {replacement}。")
    return redirect(detail_url)


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


def _recognize_old_owner_documents(order, actor_name):
    documents = {
        document.document_type: document
        for document in order.subsidy_documents.filter(
            document_type__in={
                SubsidyDocument.DocumentType.OLD_OWNER_ID_FRONT,
                SubsidyDocument.DocumentType.OLD_OWNER_ID_BACK,
            }
        )
    }
    front = documents.get(SubsidyDocument.DocumentType.OLD_OWNER_ID_FRONT)
    back = documents.get(SubsidyDocument.DocumentType.OLD_OWNER_ID_BACK)
    if not front or not back:
        return None
    image_extensions = {".jpg", ".jpeg", ".png", ".webp"}
    if (
        Path(front.file.name).suffix.lower() not in image_extensions
        or Path(back.file.name).suffix.lower() not in image_extensions
    ):
        return "證件已保存；OCR 僅支援 JPG、PNG 或 WebP，請人工填寫舊車主資料。"

    try:
        with front.file.open("rb") as front_file, back.file.open("rb") as back_file:
            result = recognize_id_card(front_file.read(), back_file.read())
    except IdOcrError as exc:
        return f"證件已保存；OCR 未完成：{exc}"
    except Exception:
        logger.exception("舊車主身分證 OCR 發生未預期錯誤")
        return "證件已保存；辨識服務暫時無法使用，請稍後重傳或人工填寫。"

    fields = result.get("fields", {})
    recognized_name = (fields.get("name") or "").strip()
    recognized_id = (fields.get("id_number") or "").strip().upper()
    before = _order_snapshot(order)
    conflicts = []
    changed_fields = []
    for field_name, candidate_field, recognized_value in (
        ("old_owner_name", "old_owner_ocr_name", recognized_name),
        ("old_owner_id_number", "old_owner_ocr_id_number", recognized_id),
    ):
        current_value = getattr(order, field_name)
        if not recognized_value:
            continue
        if not current_value:
            setattr(order, field_name, recognized_value)
            setattr(order, candidate_field, "")
            changed_fields.extend([field_name, candidate_field])
        elif current_value != recognized_value:
            setattr(order, candidate_field, recognized_value)
            changed_fields.append(candidate_field)
            conflicts.append(field_name)
        elif getattr(order, candidate_field):
            setattr(order, candidate_field, "")
            changed_fields.append(candidate_field)

    if changed_fields:
        order.revision += 1
        order.save(
            update_fields=[*set(changed_fields), "revision", "updated_at"]
        )
        changes = _snapshot_changes(before, _order_snapshot(order))
        if changes:
            OrderChange.objects.create(
                order=order,
                reason="舊車主證件 OCR 自動辨識",
                changes=changes,
                actor_name=actor_name,
            )
    warning_text = " ".join(result.get("warnings", []))
    if conflicts:
        return "辨識完成，但結果與目前資料不同，請選擇要採用的內容。"
    if recognized_name or recognized_id:
        return f"已自動帶入舊車主姓名與身分證字號。{warning_text}".strip()
    return f"未辨識到舊車主姓名或身分證字號，請人工填寫。{warning_text}".strip()


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
    existing = None
    if document.document_type != SubsidyDocument.DocumentType.OTHER:
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
    ocr_message = None
    if document.document_type in {
        SubsidyDocument.DocumentType.OLD_OWNER_ID_FRONT,
        SubsidyDocument.DocumentType.OLD_OWNER_ID_BACK,
    }:
        ocr_message = _recognize_old_owner_documents(
            order, _editing_name(request.user)
        )
    OrderEvent.objects.create(
        order=order,
        event_type="subsidy_document_uploaded",
        description=(
            f"已上傳補助文件："
            f"{document.name or document.get_document_type_display()}"
        ),
        actor_name=_editing_name(request.user),
    )
    messages.success(
        request,
        ocr_message
        or f"{document.name or document.get_document_type_display()}已上傳。",
    )
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
    display_name = document.name or document.get_document_type_display()
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
@transaction.atomic
def subsidy_ocr_decision(request, pk):
    order = get_object_or_404(SalesOrder.objects.select_for_update(), pk=pk)
    detail_url = f"{reverse('order_detail', args=[pk])}?tab=subsidy"
    if request.method != "POST" or not order.is_editable:
        return redirect(detail_url)
    decision = request.POST.get("decision")
    if decision not in {"apply", "keep"}:
        messages.error(request, "無效的 OCR 資料處理方式。")
        return redirect(detail_url)

    before = _order_snapshot(order)
    if decision == "apply":
        if order.old_owner_ocr_name:
            order.old_owner_name = order.old_owner_ocr_name
        if order.old_owner_ocr_id_number:
            order.old_owner_id_number = order.old_owner_ocr_id_number
    order.old_owner_ocr_name = ""
    order.old_owner_ocr_id_number = ""
    order.revision += 1
    order.save(
        update_fields=[
            "old_owner_name",
            "old_owner_id_number",
            "old_owner_ocr_name",
            "old_owner_ocr_id_number",
            "revision",
            "updated_at",
        ]
    )
    changes = _snapshot_changes(before, _order_snapshot(order))
    reason = (
        "採用舊車主證件 OCR 結果"
        if decision == "apply"
        else "保留人工輸入的舊車主資料"
    )
    if changes:
        OrderChange.objects.create(
            order=order,
            reason=reason,
            changes=changes,
            actor_name=_editing_name(request.user),
        )
    OrderEvent.objects.create(
        order=order,
        event_type="old_owner_ocr_decided",
        description=reason,
        actor_name=_editing_name(request.user),
    )
    messages.success(
        request,
        "已採用辨識結果。" if decision == "apply" else "已保留目前內容。",
    )
    return redirect(detail_url)


@login_required
def inventory_list(request):
    vehicles = VehicleInventory.objects.select_related(
        "vehicle_model", "color", "location_store"
    )
    keyword = request.GET.get("q", "").strip()
    status = request.GET.get("status")
    vehicle_model = request.GET.get("vehicle_model")
    color = request.GET.get("color")
    location_store = request.GET.get("location_store")
    sort = request.GET.get("sort", "received_desc")
    valid_statuses = {value for value, _label in VehicleInventory.Status.choices}
    if status in valid_statuses:
        vehicles = vehicles.filter(status=status)
    if vehicle_model and vehicle_model.isdigit():
        vehicles = vehicles.filter(vehicle_model_id=vehicle_model)
    if color and color.isdigit():
        vehicles = vehicles.filter(color_id=color)
    if location_store and location_store.isdigit():
        vehicles = vehicles.filter(location_store_id=location_store)
    if keyword:
        matching_statuses = [
            value
            for value, label in VehicleInventory.Status.choices
            if keyword.casefold() in label.casefold()
        ]
        query = (
            Q(engine_number__icontains=keyword)
            | Q(frame_number__icontains=keyword)
            | Q(vehicle_model__brand__icontains=keyword)
            | Q(vehicle_model__name__icontains=keyword)
            | Q(color__name__icontains=keyword)
            | Q(location_store__name__icontains=keyword)
            | Q(condition_note__icontains=keyword)
        )
        if matching_statuses:
            query |= Q(status__in=matching_statuses)
        vehicles = vehicles.filter(query)
    sort_options = {
        "received_desc": ("-received_on", "-id"),
        "received_asc": ("received_on", "id"),
        "model": ("vehicle_model__name", "color__name", "-received_on"),
        "color": ("color__name", "vehicle_model__name", "-received_on"),
        "identifier": ("engine_number", "frame_number", "-received_on"),
        "status": ("status", "-received_on"),
        "location": ("location_store__name", "vehicle_model__name"),
    }
    if sort not in sort_options:
        sort = "received_desc"
    vehicles = vehicles.order_by(*sort_options[sort])
    paginator = Paginator(vehicles, 100)
    page = paginator.get_page(request.GET.get("page"))
    filter_params = request.GET.copy()
    filter_params.pop("page", None)
    return render(
        request,
        "sales/inventory_list.html",
        {
            "vehicles": page.object_list,
            "page_obj": page,
            "statuses": VehicleInventory.Status.choices,
            "vehicle_models": VehicleModel.objects.filter(active=True).order_by(
                "brand", "name"
            ),
            "colors": VehicleColor.objects.filter(active=True)
            .select_related("vehicle_model")
            .order_by("vehicle_model__name", "name"),
            "stores": Store.objects.filter(active=True).order_by("name"),
            "filter_query": filter_params.urlencode(),
            "selected": {
                "q": keyword,
                "status": status or "",
                "vehicle_model": vehicle_model or "",
                "color": color or "",
                "location_store": location_store or "",
                "sort": sort,
            },
        },
    )


@login_required
def vehicle_model_list(request):
    keyword = request.GET.get("q", "").strip()
    energy_type = request.GET.get("energy_type", "")
    active = request.GET.get("active", "")
    models = VehicleModel.objects.annotate(
        inventory_count=Count("vehicleinventory", distinct=True),
        available_count=Count(
            "vehicleinventory",
            filter=Q(vehicleinventory__status=VehicleInventory.Status.AVAILABLE),
            distinct=True,
        ),
        color_count=Count("colors", distinct=True),
    )
    if keyword:
        models = models.filter(
            Q(brand__icontains=keyword)
            | Q(name__icontains=keyword)
            | Q(model_number__icontains=keyword)
            | Q(model_code__icontains=keyword)
            | Q(colors__name__icontains=keyword)
        ).distinct()
    valid_energy_types = {
        value for value, _label in VehicleModel.EnergyType.choices
    }
    if energy_type in valid_energy_types:
        models = models.filter(energy_type=energy_type)
    if active == "yes":
        models = models.filter(active=True)
    elif active == "no":
        models = models.filter(active=False)
    models = models.order_by("brand", "name", "-model_year", "model_code")
    paginator = Paginator(models, 100)
    page = paginator.get_page(request.GET.get("page"))
    return render(
        request,
        "sales/vehicle_model_list.html",
        {
            "vehicle_models": page.object_list,
            "page_obj": page,
            "energy_types": VehicleModel.EnergyType.choices,
            "selected": {
                "q": keyword,
                "energy_type": energy_type,
                "active": active,
            },
        },
    )


def _vehicle_model_form_view(request, instance=None):
    is_editing = instance is not None
    form = VehicleModelMasterForm(request.POST or None, instance=instance)
    color_formset = VehicleColorMasterFormSet(
        request.POST or None,
        instance=instance,
        prefix="colors",
    )
    if request.method == "POST" and form.is_valid() and color_formset.is_valid():
        with transaction.atomic():
            vehicle_model = form.save()
            color_formset.instance = vehicle_model
            color_formset.save()
        messages.success(
            request,
            f"已{'更新' if is_editing else '建立'}車型：{vehicle_model}",
        )
        return redirect("vehicle_model_list")
    return render(
        request,
        "sales/vehicle_model_form.html",
        {
            "form": form,
            "color_formset": color_formset,
            "vehicle_model": instance,
            "is_editing": is_editing,
        },
    )


@login_required
def vehicle_model_create(request):
    return _vehicle_model_form_view(request)


@login_required
def vehicle_model_edit(request, pk):
    return _vehicle_model_form_view(
        request,
        get_object_or_404(VehicleModel, pk=pk),
    )


def server_error(request):
    return render(request, "errors/500.html", status=500)


@login_required
def inventory_create(request):
    if request.method == "POST":
        form = VehicleInventoryForm(request.POST, request.FILES)
        if form.is_valid():
            with transaction.atomic():
                vehicle = form.save()
                _create_inventory_history(
                    vehicle,
                    actor_name=_editing_name(request.user),
                    event_type=VehicleInventoryHistory.EventType.CREATED,
                )
            messages.success(request, f"已建立庫存車輛：{vehicle.identifier}")
            return redirect("inventory_list")
    else:
        form = VehicleInventoryForm()
    return render(
        request,
        "sales/inventory_form.html",
        {"form": form, "is_editing": False},
    )


@login_required
def inventory_quick_create(request):
    formset = QuickInventoryEntryFormSet(
        request.POST or None,
        prefix="vehicles",
    )
    if request.method == "POST" and formset.is_valid():
        store = (
            Store.objects.filter(active=True, code__iexact="HQ").first()
            or Store.objects.filter(active=True).order_by("id").first()
        )
        if not store:
            formset._non_form_errors = formset.error_class(
                ["目前沒有啟用中的存放地點，請先建立本店資料。"]
            )
        else:
            try:
                with transaction.atomic():
                    created = []
                    for form in formset:
                        if not form.cleaned_data or form.cleaned_data.get("DELETE"):
                            continue
                        model = form.cleaned_data["vehicle_model"]
                        identifier = form.cleaned_data["identifier"]
                        vehicle = VehicleInventory(
                            vehicle_model=model,
                            color=form.cleaned_data["color"],
                            ownership_store=store,
                            location_store=store,
                            received_on=form.cleaned_data["received_on"],
                            acquisition_cost=form.cleaned_data.get(
                                "acquisition_cost"
                            ),
                            condition_note=form.cleaned_data.get("condition_note", ""),
                        )
                        if model.energy_type == VehicleModel.EnergyType.GAS:
                            vehicle.engine_number = identifier
                        else:
                            vehicle.frame_number = identifier
                        vehicle.save()
                        _create_inventory_history(
                            vehicle,
                            actor_name=_editing_name(request.user),
                            event_type=VehicleInventoryHistory.EventType.CREATED,
                        )
                        created.append(vehicle)
            except (IntegrityError, ValidationError):
                formset._non_form_errors = formset.error_class(
                    ["資料在送出期間發生變動，可能已有相同號碼，請檢查標示內容後再試一次。"]
                )
            else:
                messages.success(request, f"已完成快速進車，共建立 {len(created)} 台車輛。")
                return redirect("inventory_list")
    return render(
        request,
        "sales/inventory_quick_form.html",
        {
            "formset": formset,
            "energy_types": {
                str(model.pk): model.energy_type
                for model in VehicleModel.objects.filter(active=True)
            },
        },
    )


@login_required
def inventory_edit(request, pk):
    vehicle = get_object_or_404(
        VehicleInventory.objects.select_related(
            "vehicle_model", "color", "ownership_store", "location_store"
        ),
        pk=pk,
    )
    if request.method == "POST":
        with transaction.atomic():
            vehicle = VehicleInventory.objects.select_for_update().select_related(
                "vehicle_model", "color", "location_store"
            ).get(pk=pk)
            before = _inventory_values(vehicle)
            before_location_id = vehicle.location_store_id
            form = VehicleInventoryForm(
                request.POST,
                request.FILES,
                instance=vehicle,
            )
            if form.is_valid():
                vehicle = form.save()
                after = _inventory_values(vehicle)
                changes = {
                    field_name: {
                        "label": INVENTORY_HISTORY_FIELDS[field_name],
                        "before": before[field_name][1],
                        "after": after[field_name][1],
                    }
                    for field_name in INVENTORY_HISTORY_FIELDS
                    if before[field_name][0] != after[field_name][0]
                }
                reason = form.cleaned_data.get("change_reason", "").strip()
                if changes or reason:
                    is_transfer = before_location_id != vehicle.location_store_id
                    _create_inventory_history(
                        vehicle,
                        actor_name=_editing_name(request.user),
                        event_type=(
                            VehicleInventoryHistory.EventType.TRANSFERRED
                            if is_transfer
                            else VehicleInventoryHistory.EventType.UPDATED
                        ),
                        reason=reason,
                        changes=changes,
                        from_location_id=before_location_id if is_transfer else None,
                        to_location_id=vehicle.location_store_id if is_transfer else None,
                    )
                messages.success(request, f"已更新庫存車輛：{vehicle.identifier}")
                return redirect("inventory_list")
    else:
        form = VehicleInventoryForm(instance=vehicle)
    inventory_history = vehicle.history_entries.select_related(
        "from_location", "to_location", "location_store_snapshot"
    )
    return render(
        request,
        "sales/inventory_form.html",
        {
            "form": form,
            "vehicle": vehicle,
            "is_editing": True,
            "core_fields_locked": form.core_fields_locked,
            "final_fields_locked": form.final_fields_locked,
            "inventory_history": inventory_history,
            "transfer_history": inventory_history.filter(
                event_type=VehicleInventoryHistory.EventType.TRANSFERRED
            ),
        },
    )


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
            {"ok": False, "error": "請先拍攝證件正面與反面。"},
            status=400,
        )
    document_type = request.POST.get(
        "document_type", IdOcrJob.DocumentType.NATIONAL_ID
    )
    valid_document_types = {value for value, _label in IdOcrJob.DocumentType.choices}
    if document_type not in valid_document_types:
        return JsonResponse(
            {"ok": False, "error": "不支援的證件類型。"},
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
    if front.size > 12 * 1024 * 1024 or back.size > 12 * 1024 * 1024:
        return JsonResponse(
            {"ok": False, "error": "單張照片不可超過 12MB。"},
            status=413,
        )
    queue = django_rq.get_queue("ocr")
    if queue.count >= 10:
        return JsonResponse(
            {"ok": False, "error": "目前辨識工作較多，請稍候再試。"},
            status=429,
        )
    photo_token = request.POST.get("photo_token") or uuid.uuid4().hex
    job = IdOcrJob.objects.create(
        created_by=request.user,
        front=front,
        back=back,
        document_type=document_type,
        photo_token=photo_token,
    )
    try:
        queue.enqueue(
            run_id_ocr_job,
            str(job.pk),
            job_timeout=45,
            retry=Retry(max=2, interval=[2, 5]),
            result_ttl=300,
            failure_ttl=86400,
        )
    except Exception:
        logger.exception("無法加入身分證 OCR 背景佇列")
        job.status = IdOcrJob.Status.FAILED
        job.error = "辨識工作無法排入佇列，請稍後再試。"
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "error", "finished_at", "updated_at"])
        return JsonResponse({"ok": False, "error": job.error}, status=503)
    return JsonResponse(
        {
            "ok": True,
            "job_id": str(job.pk),
            "photo_token": photo_token,
            "document_type": job.document_type,
            "status": job.status,
        },
        status=202,
    )


@login_required
def id_card_ocr_status(request, job_id):
    job = get_object_or_404(IdOcrJob, pk=job_id, created_by=request.user)
    payload = {
        "ok": True,
        "job_id": str(job.pk),
        "photo_token": job.photo_token,
        "status": job.status,
    }
    if job.status == IdOcrJob.Status.SUCCEEDED:
        payload.update(job.result)
    elif job.status == IdOcrJob.Status.FAILED:
        payload["error"] = job.error
    return JsonResponse(payload)


@login_required
def id_card_ocr_invalidate(request, job_id):
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "僅接受 POST。"}, status=405)
    job = get_object_or_404(IdOcrJob, pk=job_id, created_by=request.user)
    if job.status not in (IdOcrJob.Status.SUCCEEDED, IdOcrJob.Status.FAILED):
        job.status = IdOcrJob.Status.INVALIDATED
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "finished_at", "updated_at"])
        delete_id_ocr_job_files(job)
    return JsonResponse({"ok": True, "status": job.status})


@login_required
def protected_media(request, model_name, pk, field_name):
    allowed = {
        "order": (
            SalesOrder,
            {"id_front", "id_back", "signed_contract", "privacy_consent"},
        ),
        "draft": (OrderDraft, {"id_front", "id_back"}),
        "vehicle": (VehicleInventory, {"condition_photo"}),
        "vehicle_history": (
            VehicleInventoryHistory,
            {"condition_photo_snapshot"},
        ),
        "payment": (PaymentRecord, {"proof"}),
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
