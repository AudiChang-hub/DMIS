"""合作車行與帳號中心共用的 admin 管理入口。"""

from django import forms
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.db import transaction, IntegrityError
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods
from sales.access.views import root_required
from sales.access.models import UserAccessState
from sales.forms import AdminUserCreateForm, AdminUserEditForm
from sales.models import (
    SalesSource,
    OrderAccountProfile,
    UserSecurityProfile,
    UserAccountAuditLog,
)


class DealerCreateForm(AdminUserCreateForm):
    can_submit_orders = forms.BooleanField(
        label="可建立訂單與使用自己的草稿", required=False, initial=True
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["is_superuser"].disabled = True
        self.fields["is_superuser"].initial = False
        self.fields["is_superuser"].widget = forms.HiddenInput()
        self.fields["must_change_password"].disabled = True
        self.fields["must_change_password"].initial = True


class DealerEditForm(AdminUserEditForm):
    can_submit_orders = forms.BooleanField(
        label="可建立訂單與使用自己的草稿", required=False
    )
    expected_revision = forms.IntegerField(widget=forms.HiddenInput, min_value=0)

    def __init__(self, *args, profile, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["is_superuser"].disabled = True
        self.fields["is_superuser"].initial = False
        self.fields["is_superuser"].widget = forms.HiddenInput()
        self.fields["can_submit_orders"].initial = profile.can_submit_orders
        self.fields["expected_revision"].initial = profile.revision


def dealer_source(pk):
    return get_object_or_404(
        SalesSource, pk=pk, source_type=SalesSource.SourceType.DEALER
    )


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
                    )
                    UserSecurityProfile.objects.create(
                        user=user, must_change_password=True
                    )
                    UserAccessState.objects.create(user=user, configured=True)
                    UserAccountAuditLog.objects.create(
                        actor=request.user,
                        target=user,
                        target_username=user.username,
                        action="create",
                        description=f"開通 {source.name} 車行帳號 {user.username}",
                        metadata={
                            "source_id": source.pk,
                            "can_submit_orders": form.cleaned_data["can_submit_orders"],
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
        request, "sales/dealer_account_form.html", {"source": source, "form": form}
    )


@root_required
@require_http_methods(["GET", "POST"])
def dealer_account_edit(request, pk):
    profile = get_object_or_404(
        OrderAccountProfile.objects.select_related("user", "source"),
        user_id=pk,
        kind="dealer",
    )
    form = DealerEditForm(request.POST or None, instance=profile.user, profile=profile)
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
                        "username": user.username,
                        "is_active": user.is_active,
                        "can_submit_orders": current.can_submit_orders,
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
                    current.revision += 1
                    current.save(
                        update_fields=["can_submit_orders", "revision", "updated_at"]
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
                                "username": user.username,
                                "is_active": user.is_active,
                                "can_submit_orders": current.can_submit_orders,
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
