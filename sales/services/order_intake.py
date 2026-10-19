"""店內人員下訂；資料範圍的唯一判斷入口。"""
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404
from django.utils import timezone

from sales.models import OrderAccountProfile, OrderDraft, SalesOrder


def account_profile(user):
    return OrderAccountProfile.objects.select_related("source").filter(user=user).first() if user.is_authenticated else None


def can_edit_finance(user):
    from sales.access.services import AccessPolicy
    return AccessPolicy(user).screen("order_finance", "operate")


def scoped_orders(user, queryset=None, *, apply_overrides=True):
    queryset = queryset if queryset is not None else SalesOrder.objects.all()
    if not user.is_authenticated or not user.is_active:
        return queryset.none()
    from sales.access.services import is_root
    if is_root(user):
        return queryset
    profile = account_profile(user)
    if apply_overrides and profile:
        from sales.models import OrderCustomerAccessGrant
        denied = OrderCustomerAccessGrant.objects.filter(account=profile, active=True,
            identity_epoch=profile.identity_epoch, is_override=True, can_view=False)
        queryset = queryset.exclude(pk__in=denied.values("order_id"))
    if profile and profile.order_scope == "own":
        return queryset.filter(submitted_by=user)
    return queryset


def order_scope_label(user):
    from sales.access.services import is_root
    profile = account_profile(user)
    if is_root(user) or not profile or profile.order_scope == "all":
        return "全部訂單"
    return "我的訂單"


CUSTOMER_DOCUMENT_ROUTES = {"contract_print", "privacy_consent_print", "order_documents_print"}
ORDER_PK_ROUTES = CUSTOMER_DOCUMENT_ROUTES | {
    "order_detail", "order_overview", "order_edit", "order_operations", "order_edit_presence", "historical_delivery_complete", "order_return",
    "order_secret_reveal", "order_payout_reveal", "order_commission_attribution_update", "order_discount_request", "order_discount_decide",
    "contract_upload", "privacy_consent_upload", "order_sign", "order_sign_done", "allocate_vehicle", "reallocate_vehicle",
    "registration_save", "registration_document_upload", "registration_document_delete", "registration_complete",
    "delivery_complete", "delivery_payment_update", "deposit_payment_update", "cancellation_request", "cancellation_withdraw", "refund_complete",
    "payment_reverse", "payment_overpayment_refund", "installment_decision_update", "order_exception_close", "order_close",
    "subsidy_toggle", "subsidy_document_upload", "subsidy_document_delete", "subsidy_data_update", "subsidy_ocr_decision",
    "registration_fee_variance_confirm", "identity_documents_print",
    "order_attachment_upload", "order_attachment_delete", "order_attachments_zip", "order_attachment_classify",
}


def guard_order_scope(request, name, kwargs):
    """資料範圍先於畫面授權判斷；不靠隱藏按鈕保護單筆資料。"""
    if name in ORDER_PK_ROUTES:
        from sales.services.order_customer_access import customer_orders
        visible = (customer_orders(request.user, printing=name in CUSTOMER_DOCUMENT_ROUTES)
                   if name in CUSTOMER_DOCUMENT_ROUTES | {"order_detail"} else scoped_orders(request.user))
        if not visible.filter(pk=kwargs.get("pk")).exists():
            raise Http404
    if name == "positioned_template_order_print":
        if not scoped_orders(request.user).filter(pk=kwargs.get("order_pk")).exists():
            raise Http404
    if name in {"vehicle_price_options", "installment_plan_options"} and request.GET.get("order_id"):
        from sales.access.services import policy_for
        if not policy_for(request).screen("orders"):
            raise PermissionDenied("沒有查詢訂單快照權限。")
        try:
            exists = scoped_orders(request.user).filter(pk=request.GET["order_id"]).exists()
        except (ValueError, ValidationError):
            return  # 格式錯誤交回原查詢端點，保留其 JSON 400／公開查價語意。
        if not exists:
            raise Http404


def scoped_drafts(user, queryset=None, *, reception=False):
    queryset = queryset if queryset is not None else OrderDraft.objects.all()
    profile = account_profile(user)
    from sales.access.services import AccessPolicy
    if reception or (profile and profile.order_scope != "all") or not AccessPolicy(user).screen("orders"):
        return queryset.filter(owner_account=user)
    return queryset


def mark_accepted(order, user):
    """開單者即接單人（使用者 2026-10-16：只有店內人員使用，不另走待接單）。"""
    order.accepted_by = user
    order.accepted_name = (user.get_full_name() or user.get_username())[:160]
    order.accepted_at = timezone.now()
    order.status = SalesOrder.Status.ALLOCATION_PENDING


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
    return {"intake_source": profile.source if profile else None, "intake_finance_editable": can_edit_finance(user)}
