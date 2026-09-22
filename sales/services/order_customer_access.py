"""客戶視角的單筆授權；原訂單、帳務及既有畫面權限皆不變。"""
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q

from sales.models import OrderAccountProfile, OrderCustomerAccessGrant, OrderEvent, SalesOrder


def customer_orders(user, queryset=None, *, printing=False):
    from sales.services.order_intake import account_profile, scoped_orders
    queryset = queryset if queryset is not None else SalesOrder.objects.all()
    normal = scoped_orders(user, queryset, apply_overrides=False)
    profile = account_profile(user)
    from sales.access.services import is_root
    if is_root(user) or not user.is_active or not profile:
        return normal
    if profile.kind == "dealer" and (not profile.source_id or not profile.source.active):
        return queryset.none()
    grants = OrderCustomerAccessGrant.objects.filter(account=profile, identity_epoch=profile.identity_epoch, active=True)
    flag = "can_print" if printing else "can_view"
    allowed = grants.filter(**{flag: True})
    denied = grants.filter(is_override=True, **{flag: False})
    return queryset.filter(Q(pk__in=normal.values("pk")) | Q(pk__in=allowed.values("order_id"))).exclude(pk__in=denied.values("order_id"))


@transaction.atomic
def set_customer_access(*, actor, order_id, account_id, expected_revision, expected_identity_epoch, can_view, can_print, active, reason, is_override=False):
    from sales.access.services import is_root
    if not is_root(actor):
        raise PermissionDenied
    reason = (reason or "").strip()
    if not reason or len(reason) > 500:
        raise ValidationError("請填寫授權／撤銷原因，最多 500 字。")
    order = SalesOrder.objects.select_for_update().get(pk=order_id)
    account = OrderAccountProfile.objects.select_for_update(of=("self",)).select_related("user", "source").get(pk=account_id)
    if active and account.identity_epoch != expected_identity_epoch:
        raise ValidationError("帳號身分或所屬車行已變更，請重新載入後再授權。")
    grant = OrderCustomerAccessGrant.objects.select_for_update().filter(order=order, account=account).first()
    if expected_revision != (grant.revision if grant else 0):
        raise ValidationError("授權已被其他視窗更新，請重新整理後再操作。")
    if is_root(account.user):
        raise ValidationError("admin 為固定最高權限，不設定單筆例外。")
    if active and (not account.user.is_active or (account.kind == "dealer" and (not account.source_id or not account.source.active))):
        raise ValidationError("只能授權啟用中且有所屬車行的合作車行帳號。")
    if active and not is_override and not (can_view or can_print):
        raise ValidationError("請勾選查看或列印；若不再開放，請使用撤銷。")
    if active and is_override:
        from sales.access.services import AccessPolicy
        from sales.services.order_intake import scoped_orders
        policy = AccessPolicy(account.user)
        if can_view and not policy.screen("orders"):
            raise ValidationError("帳號尚未開放訂單查詢，請先到「畫面與操作」啟用。")
        if can_print and not policy.screen("order_documents", "export"):
            raise ValidationError("帳號尚未開放客戶文件列印，請先到「畫面與操作」啟用。")
        if account.kind != "dealer" and (can_view or can_print) and not scoped_orders(account.user, apply_overrides=False).filter(pk=order.pk).exists():
            raise ValidationError("內部人員請先調整訂單範圍；單筆設定不能繞過內部資料範圍。")
    def state(row):
        if not row:
            return "尚未授權"
        return (f"{'本筆自訂' if row.is_override else '舊版額外授權'}；查看：{'開放' if row.can_view else '不開放'}、列印：{'開放' if row.can_print else '不開放'}、"
                f"{'啟用' if row.active else '已撤銷'}（身分版本 {row.identity_epoch}）")
    before = state(grant)
    if not grant:
        grant = OrderCustomerAccessGrant(order=order, account=account, revision=0)
    grant.can_view, grant.can_print, grant.active = can_view, can_print, active
    grant.is_override = is_override
    grant.identity_epoch = account.identity_epoch
    grant.reason, grant.changed_by = reason, actor
    grant.revision += 1
    grant.save()
    OrderEvent.objects.create(order=order, event_type="customer_access_updated", actor_name=actor.get_username(),
        description=f"客戶文件授權：{account.user.get_username()}；{before} → {state(grant)}；原因：{reason}")
    return grant
