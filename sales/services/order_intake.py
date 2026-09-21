"""共用下訂與接單；資料範圍的唯一判斷入口。"""
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import Http404
from django.utils import timezone

from sales.models import OrderAccountProfile, OrderDraft, OrderEvent, SalesOrder


def account_profile(user):
    return OrderAccountProfile.objects.select_related("source").filter(user=user).first() if user.is_authenticated else None


def dealer_source(user):
    profile = account_profile(user)
    return profile.source if profile and profile.kind == "dealer" else None


def is_dealer(user):
    profile = account_profile(user)
    return bool(profile and profile.kind == "dealer")


def can_receive(user):
    from sales.access.services import AccessPolicy
    return not is_dealer(user) and AccessPolicy(user).screen("work", "operate")


def can_edit_finance(user):
    from sales.access.services import AccessPolicy
    return not is_dealer(user) and AccessPolicy(user).screen("order_finance", "operate")


def scoped_orders(user, queryset=None):
    queryset = queryset if queryset is not None else SalesOrder.objects.all()
    profile = account_profile(user)
    if profile and profile.kind == "dealer":
        if not profile.source_id or not profile.source.active:
            return queryset.none()
        return queryset.filter(source_id=profile.source_id, source_type=SalesOrder.SourceType.DEALER)
    return queryset


def scoped_drafts(user, queryset=None, *, reception=False):
    queryset = queryset if queryset is not None else OrderDraft.objects.all()
    profile = account_profile(user)
    if profile and profile.kind == "dealer":
        return queryset.filter(owner_account=user) if profile.can_submit_orders else queryset.none()
    from sales.access.services import AccessPolicy
    if reception or not AccessPolicy(user).screen("orders"):
        return queryset.filter(owner_account=user)
    return queryset


@transaction.atomic
def receive_order(user, pk):
    if not can_receive(user):
        raise PermissionDenied("沒有接單權限。")
    order = SalesOrder.objects.select_for_update().get(pk=pk)
    if order.status != SalesOrder.Status.INTAKE_PENDING:
        raise ValidationError("此訂單已由其他人接單或狀態已變更，請重新整理。")
    order.accepted_by = user
    order.accepted_name = (user.get_full_name() or user.get_username())[:160]
    order.accepted_at = timezone.now()
    order.status = SalesOrder.Status.ALLOCATION_PENDING
    order.revision += 1
    order.save(update_fields=["accepted_by", "accepted_name", "accepted_at", "status", "revision", "updated_at"])
    OrderEvent.objects.create(order=order, event_type="accepted", description=f"{order.accepted_name} 已接單，進入待配車。", actor_name=user.get_username())
    return order


DEALER_ROUTES = {
    "dashboard", "home_favorites", "order_list", "order_detail", "order_create",
    "draft_save", "draft_presence", "draft_delete", "protected_media",
    "id_card_ocr", "id_card_ocr_status", "id_card_ocr_invalidate",
    "vehicle_colors", "installment_plan_options", "vehicle_price_options", "sales_sources",
    "order_intake_attachment", "appearance_theme_update", "mobile_quick_links_update",
    "app_version", "system_health", "user_guide", "password_change_required", "password_change",
    "login", "logout", "access_home",
}
DEALER_ACCOUNT_ROUTES = {"login", "logout", "password_change_required", "password_change"}
DEALER_ACCOUNT_ROUTES.update({"announcement_detail", "announcement_image", "announcement_attachment", "release_history"})
DEALER_ROUTES.update({"catalog", "catalog_detail", "catalog_image", "catalog_color_image"})
DEALER_ROUTES.update({"order_start", "intake_draft_save", "order_submitted", "intake_installment_options", "intake_price_options"})
DEALER_SUBMIT_ROUTES = {"order_create", "draft_save", "draft_presence", "draft_delete", "id_card_ocr", "id_card_ocr_status", "id_card_ocr_invalidate"}
DEALER_SUBMIT_ROUTES.update({"order_start", "intake_draft_save", "order_submitted", "intake_installment_options", "intake_price_options", "intake_drafts"})


def dealer_route_allowed(profile, name):
    if name in {"catalog", "catalog_detail", "catalog_image", "catalog_color_image"}:
        return bool(profile.source_id and profile.source.active and profile.can_browse_catalog)
    if name in DEALER_SUBMIT_ROUTES:
        return bool(profile.source_id and profile.source.active and profile.can_submit_orders)
    if name in {"vehicle_colors", "sales_sources", "installment_plan_options", "vehicle_price_options", "protected_media", "order_intake_attachment"}:
        return bool(profile.source_id and profile.source.active and (profile.can_submit_orders or profile.can_view_orders))
    if name not in {"dashboard", "user_guide", "access_home", "app_version", "system_health", "appearance_theme_update", "mobile_quick_links_update"} and not profile.can_view_orders:
        return False
    return bool(profile.source_id and profile.source.active and name in DEALER_ROUTES
        and (profile.can_submit_orders or name not in DEALER_SUBMIT_ROUTES))


def prepare_intake_uploads(uploads, *, order=None, draft=None, remove_ids=()):
    import hashlib
    from sales.models import OrderIntakeAttachment
    existing = OrderIntakeAttachment.objects.filter(order=order) if order else OrderIntakeAttachment.objects.filter(draft=draft) if draft and draft.pk else OrderIntakeAttachment.objects.none()
    existing = existing.exclude(pk__in=[value for value in remove_ids if str(value).isdigit()])
    seen = set(existing.values_list("kind", "checksum"))
    prepared = []
    for kind, upload in uploads:
        checksum = hashlib.sha256()
        for chunk in upload.chunks():
            checksum.update(chunk)
        upload.seek(0)
        digest = checksum.hexdigest()
        if (kind, digest) not in seen:
            prepared.append((kind, upload, digest))
            seen.add((kind, digest))
    if sum(kind == "installment" for kind, _ in seen) > 1 or sum(kind == "supplement" for kind, _ in seen) > 10:
        raise ValidationError("分期表限 1 個、補充附件最多 10 個；請先勾選移除不需要的已存附件。")
    if any(sum(kind == wanted for kind, _ in seen) > 1 for wanted in ("owner_bankbook", "old_id_front", "old_id_back", "old_bankbook")):
        raise ValidationError("同類證件或存摺限一份，請先移除要替換的已存附件。")
    return prepared


def save_intake_uploads(user, uploads, *, order=None, draft=None, remove_ids=()):
    from pathlib import Path
    from sales.models import OrderIntakeAttachment
    parent = {"order": order} if order else {"draft": draft}
    prepared = prepare_intake_uploads(uploads, order=order, draft=draft, remove_ids=remove_ids)
    written = []
    try:
        for kind, upload, digest in prepared:
            attachment = OrderIntakeAttachment(**parent, kind=kind, checksum=digest, name=Path(upload.name).name[:200], uploaded_by=user)
            attachment.file.save(attachment.name, upload, save=False)
            written.append((attachment.file.storage, attachment.file.name))
            attachment.save()
    except Exception:
        for storage, name in written:
            storage.delete(name)
        raise
    OrderIntakeAttachment.objects.filter(**parent, pk__in=[value for value in remove_ids if str(value).isdigit()]).delete()


def intake_context(user):
    profile = account_profile(user)
    return {"intake_dealer": bool(profile and profile.kind == "dealer"), "intake_source": profile.source if profile else None,
            "intake_can_receive": can_receive(user), "intake_finance_editable": can_edit_finance(user)}


def guard_dealer_request(request, name, kwargs):
    """ScreenAccessMiddleware 在一般權限判斷前呼叫；不受 root/configured shortcut 繞過。"""
    profile = account_profile(request.user)
    if not profile or profile.kind != "dealer":
        return
    if name in DEALER_ACCOUNT_ROUTES:
        return
    if not dealer_route_allowed(profile, name):
        raise PermissionDenied("此車行帳號無法使用這項功能。")
    if name == "order_detail" and not scoped_orders(request.user).filter(pk=kwargs.get("pk")).exists():
        raise Http404
    draft_id = request.POST.get("_draft_id") or request.GET.get("draft")
    if name in {"draft_presence", "draft_delete"}:
        draft_id = kwargs.get("pk")
    if draft_id:
        submitted_key = request.POST.get("_submission_key")
        try:
            already_submitted = bool(name in {"order_create", "order_start"} and submitted_key and SalesOrder.objects.filter(submission_key=submitted_key, submitted_by=request.user).exists())
        except (ValidationError, ValueError):
            already_submitted = False
        try:
            exists = already_submitted or scoped_drafts(request.user).filter(pk=draft_id).exists()
        except (ValidationError, ValueError):
            raise Http404 from None
        if not exists:
            raise Http404
    if name in {"vehicle_price_options", "installment_plan_options"} and request.GET.get("order_id"):
        raise PermissionDenied("車行選車僅能查詢公開方案。")
    if name == "protected_media":
        kind, pk, field = kwargs.get("model_name"), kwargs.get("pk"), kwargs.get("field_name")
        if kind == "order" and not profile.can_view_orders:
            raise PermissionDenied("沒有查詢訂單權限。")
        if field not in {"id_front", "id_back"}:
            raise PermissionDenied
        qs = scoped_orders(request.user) if kind == "order" else scoped_drafts(request.user) if kind == "draft" else None
        if qs is None or not qs.filter(pk=pk).exists():
            raise Http404
