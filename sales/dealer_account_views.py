"""合作車行與帳號中心共用的 admin 管理入口。"""

from django import forms
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.db import transaction, IntegrityError
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods
from sales.access.views import root_required
from sales.access.models import UserAccessState, ScreenAccessGrant
from sales.forms import AdminUserCreateForm, AdminUserEditForm
from sales.models import (
    SalesSource,
    OrderAccountProfile,
    UserSecurityProfile,
    UserAccountAuditLog,
)


class DealerFeatureMixin:
    def feature_fields(self, profile=None):
        self.fields["order_scope"] = forms.ChoiceField(label="訂單資料範圍", choices=(("own", "本人建立的訂單"), ("dealer", "所屬車行的訂單")), initial=profile.order_scope if profile else "own", widget=forms.Select(attrs={"class": "form-control"}))
        self.fields["can_gift_accessories"] = forms.BooleanField(label="可贈送配件（不代表可修改售價）", required=False)
        self.fields["can_print_documents"] = forms.BooleanField(label="可列印客戶簽署文件（不含內部財務）", required=False, initial=True)
        if profile:
            # 編輯停用帳號也顯示已儲存的授權，不把「目前無法登入」誤當撤權。
            self.fields["can_gift_accessories"].initial = ScreenAccessGrant.objects.filter(user=profile.user, screen_key="order_gift", view=True, operate=True).exists()
            self.fields["can_print_documents"].initial = ScreenAccessGrant.objects.filter(user=profile.user, screen_key="order_documents", view=True, export=True).exists()
        self.fields["can_adjust_pricing"].label = "下單金額調整（成交價、配件調價、自訂分期）"
        self.fields["can_view_orders"].label = "可查詢訂單（依下方資料範圍）"
        for key in ("can_view_orders", "can_browse_catalog", "can_submit_orders"):
            self.fields[key].widget.attrs["class"] = "form-check"
        self.fields["username"].widget.attrs.update({"autocomplete": "section-new-dealer username", "autocapitalize": "none", "spellcheck": "false", "data-dealer-username": ""})


class DealerCreateForm(DealerFeatureMixin, AdminUserCreateForm):
    can_adjust_pricing = forms.BooleanField(label="下單金額調整（成交價、配件贈送／調價、自訂分期）", required=False)
    can_view_orders = forms.BooleanField(label="查看本車行訂單進度", required=False, initial=True)
    can_browse_catalog = forms.BooleanField(label="選車下單入口", required=False, initial=True)
    can_submit_orders = forms.BooleanField(
        label="可建立訂單與使用自己的草稿", required=False, initial=True
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.feature_fields()
        self.fields["is_superuser"].disabled = True
        self.fields["is_superuser"].initial = False
        self.fields["is_superuser"].widget = forms.HiddenInput()
        self.fields["must_change_password"].disabled = True
        self.fields["must_change_password"].initial = True


class DealerEditForm(DealerFeatureMixin, AdminUserEditForm):
    can_adjust_pricing = forms.BooleanField(label="下單金額調整（成交價、配件贈送／調價、自訂分期）", required=False)
    can_view_orders = forms.BooleanField(label="查看本車行訂單進度", required=False)
    can_browse_catalog = forms.BooleanField(label="選車下單入口", required=False)
    can_submit_orders = forms.BooleanField(
        label="可建立訂單與使用自己的草稿", required=False
    )
    expected_revision = forms.IntegerField(widget=forms.HiddenInput, min_value=0)

    def __init__(self, *args, profile, section=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.feature_fields(profile)
        self.fields["can_view_orders"].initial = profile.can_view_orders
        self.fields["can_browse_catalog"].initial = profile.can_browse_catalog
        self.fields["is_superuser"].disabled = True
        self.fields["is_superuser"].initial = False
        self.fields["is_superuser"].widget = forms.HiddenInput()
        self.fields["can_submit_orders"].initial = profile.can_submit_orders
        self.fields["expected_revision"].initial = profile.revision
        self.fields["can_adjust_pricing"].initial = ScreenAccessGrant.objects.filter(user=profile.user, screen_key="order_pricing", view=True, operate=True).exists()
        if section:
            editable = {"username", "display_name", "is_active"} if section == "account" else {
                "can_submit_orders", "can_view_orders", "can_browse_catalog", "can_adjust_pricing",
                "can_gift_accessories", "can_print_documents"}
            for key, field in self.fields.items():
                if key not in editable and key != "expected_revision":
                    field.disabled = True
                    field.required = False
                    field.widget = forms.HiddenInput()


def dealer_source(pk):
    return get_object_or_404(
        SalesSource, pk=pk, source_type=SalesSource.SourceType.DEALER
    )


def save_customer_permissions(user, data):
    for key, field, action in (("order_gift", "can_gift_accessories", "operate"), ("order_documents", "can_print_documents", "export")):
        enabled = data[field]
        ScreenAccessGrant.objects.update_or_create(user=user, screen_key=key,
            defaults={"view": enabled, "operate": enabled if action == "operate" else False, "export": enabled if action == "export" else False})


def customer_permission_snapshot(user, scope):
    return {"order_scope": scope, "customer_permissions": list(ScreenAccessGrant.objects.filter(user=user, screen_key__in=["order_gift", "order_documents"]).order_by("screen_key").values("screen_key", "view", "operate", "export"))}


def suggested_username(source):
    import re
    prefix = re.sub(r"[^A-Za-z0-9_-]", "", source.code)[:40] or f"dealer-{source.pk}"
    used = set(get_user_model().objects.filter(username__istartswith=prefix + "-").values_list("username", flat=True))
    used = {name.casefold() for name in used}
    index = 1
    while f"{prefix}-{index:02d}".casefold() in used:
        index += 1
    return f"{prefix}-{index:02d}"


@root_required
@require_http_methods(["GET"])
def dealer_accounts(request, source_pk):
    source = dealer_source(source_pk)
    accounts = (
        get_user_model()
        .objects.filter(order_account__kind="dealer", order_account__source=source)
        .select_related("order_account")
    )
    page = Paginator(accounts.order_by("-is_active", "username"), 25).get_page(
        request.GET.get("page")
    )
    return render(
        request,
        "sales/dealer_accounts.html",
        {"source": source, "accounts": page, "page_obj": page},
    )


@root_required
@require_http_methods(["GET", "POST"])
def dealer_account_create(request, source_pk):
    source = dealer_source(source_pk)
    form = DealerCreateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                source = get_object_or_404(
                    SalesSource.objects.select_for_update(),
                    pk=source.pk,
                    source_type="dealer",
                )
                if not source.active:
                    form.add_error(None, "此車行已停用，不能開通帳號。")
                else:
                    user = get_user_model().objects.create_user(
                        username=form.cleaned_data["username"],
                        password=form.cleaned_data["password1"],
                        first_name=form.cleaned_data["display_name"].strip(),
                        is_active=form.cleaned_data["is_active"],
                        is_staff=False,
                        is_superuser=False,
                    )
                    OrderAccountProfile.objects.create(
                        user=user,
                        kind="dealer",
                        source=source,
                        can_submit_orders=form.cleaned_data["can_submit_orders"],
                        can_view_orders=form.cleaned_data["can_view_orders"],
                        can_browse_catalog=form.cleaned_data["can_browse_catalog"],
                        order_scope=form.cleaned_data["order_scope"],
                    )
                    UserSecurityProfile.objects.create(
                        user=user, must_change_password=True
                    )
                    UserAccessState.objects.create(user=user, configured=True)
                    ScreenAccessGrant.objects.create(user=user, screen_key="order_pricing", view=form.cleaned_data["can_adjust_pricing"], operate=form.cleaned_data["can_adjust_pricing"])
                    save_customer_permissions(user, form.cleaned_data)
                    UserAccountAuditLog.objects.create(
                        actor=request.user,
                        target=user,
                        target_username=user.username,
                        action="create",
                        description=f"開通 {source.name} 車行帳號 {user.username}",
                        metadata={
                            **customer_permission_snapshot(user, form.cleaned_data["order_scope"]),
                            "can_adjust_pricing": form.cleaned_data["can_adjust_pricing"],
                            "source_id": source.pk,
                            "can_submit_orders": form.cleaned_data["can_submit_orders"],
                            "can_view_orders": form.cleaned_data["can_view_orders"],
                            "can_browse_catalog": form.cleaned_data["can_browse_catalog"],
                        },
                    )
                    messages.success(
                        request,
                        "帳號已開通並綁定車行；請安全交付臨時密碼，首次登入必須更換。",
                    )
                    return redirect("dealer_accounts", source_pk=source.pk)
        except IntegrityError:
            form.add_error("username", "此帳號剛被建立，請換一個登入帳號。")
    return render(
        request, "sales/dealer_account_form.html", {"source": source, "form": form, "suggested_username": suggested_username(source)}
    )


@root_required
@require_http_methods(["GET", "POST"])
def dealer_account_edit(request, pk):
    from sales.permission_workspace import workspace_redirect
    destination = workspace_redirect(request, pk, "account")
    if destination:
        return destination
    profile = get_object_or_404(
        OrderAccountProfile.objects.select_related("user", "source"),
        user_id=pk,
        kind="dealer",
    )
    form = DealerEditForm(request.POST or None, instance=profile.user, profile=profile,
        section=getattr(request, "permission_tab", None))
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                user = get_user_model().objects.select_for_update().get(pk=pk)
                current = get_object_or_404(
                    OrderAccountProfile.objects.select_for_update(),
                    user=user,
                    kind="dealer",
                )
                if form.cleaned_data["expected_revision"] != current.revision:
                    form.add_error(None, "帳號設定已被其他視窗更新，請重新整理。")
                elif user.username == "admin" or user.is_superuser or user.is_staff:
                    form.add_error(None, "此帳號具有管理角色，請先確認身分設定。")
                elif form.cleaned_data["is_active"] and (
                    not current.source_id or not current.source.active
                ):
                    form.add_error(None, "所屬車行已停用，不能啟用帳號。")
                else:
                    before = {
                        **customer_permission_snapshot(user, current.order_scope),
                        "can_adjust_pricing": ScreenAccessGrant.objects.filter(user=user, screen_key="order_pricing", view=True, operate=True).exists(),
                        "username": user.username,
                        "is_active": user.is_active,
                        "can_submit_orders": current.can_submit_orders,
                        "can_view_orders": current.can_view_orders,
                        "can_browse_catalog": current.can_browse_catalog,
                    }
                    user.username = form.cleaned_data["username"]
                    user.first_name = form.cleaned_data["display_name"].strip()
                    user.last_name = ""
                    user.is_active = form.cleaned_data["is_active"]
                    user.save(
                        update_fields=[
                            "username",
                            "first_name",
                            "last_name",
                            "is_active",
                        ]
                    )
                    current.can_submit_orders = form.cleaned_data["can_submit_orders"]
                    current.can_view_orders = form.cleaned_data["can_view_orders"]
                    current.can_browse_catalog = form.cleaned_data["can_browse_catalog"]
                    current.order_scope = form.cleaned_data["order_scope"]
                    save_customer_permissions(user, form.cleaned_data)
                    current.revision += 1
                    ScreenAccessGrant.objects.update_or_create(user=user, screen_key="order_pricing", defaults={"view": form.cleaned_data["can_adjust_pricing"], "operate": form.cleaned_data["can_adjust_pricing"], "export": False})
                    access_state, _ = UserAccessState.objects.get_or_create(user=user)
                    access_state.configured = True
                    access_state.version += 1
                    access_state.save(update_fields=["configured", "version", "updated_at"])
                    current.save(
                        update_fields=["can_submit_orders", "can_view_orders", "can_browse_catalog", "order_scope", "revision", "updated_at"]
                    )
                    from sales.views import _invalidate_user_sessions

                    if not user.is_active:
                        _invalidate_user_sessions(user)
                    UserAccountAuditLog.objects.create(
                        actor=request.user,
                        target=user,
                        target_username=user.username,
                        action="update",
                        description=f"調整 {current.source.name} 車行帳號 {user.username}",
                        metadata={
                            "before": before,
                            "after": {
                                **customer_permission_snapshot(user, current.order_scope),
                                "can_adjust_pricing": form.cleaned_data["can_adjust_pricing"],
                                "username": user.username,
                                "is_active": user.is_active,
                                "can_submit_orders": current.can_submit_orders,
                                "can_view_orders": current.can_view_orders,
                                "can_browse_catalog": current.can_browse_catalog,
                            },
                        },
                    )
                    messages.success(request, "車行帳號與權限已同步更新。")
                    return redirect("dealer_accounts", source_pk=current.source_id)
        except IntegrityError:
            form.add_error("username", "登入帳號已被使用，請重新確認。")
    return render(
        request,
        "sales/dealer_account_form.html",
        {"source": profile.source, "form": form, "account": profile.user},
    )
