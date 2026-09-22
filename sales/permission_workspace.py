"""admin 的單一帳號權限工作區；沿用既有驗證／稽核服務。"""
from urllib.parse import urlencode

from django import forms
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from sales.access.services import AccessPolicy, is_root
from sales.access.views import root_required
from sales.models import OrderAccountProfile, OrderCustomerAccessGrant, OrderEvent, SalesOrder
from sales.services.order_customer_access import customer_orders, set_customer_access


def workspace_url(pk, tab="account", **query):
    return reverse("permission_workspace", args=[pk]) + "?" + urlencode({"tab": tab, **query})


def workspace_redirect(request, pk, tab):
    if request.method == "GET" and not getattr(request, "permission_account", None):
        return redirect(workspace_url(pk, tab))


@root_required
@require_http_methods(["GET"])
def create_dealer_entry(request):
    from sales.models import SalesSource
    source = request.GET.get("source", "")
    if not source.isascii() or not source.isdigit() or len(source) > 18:
        messages.error(request, "請先選擇合作車行。")
        return redirect("user_management")
    source = get_object_or_404(SalesSource, pk=source, source_type="dealer", active=True)
    return redirect("dealer_account_create", source_pk=source.pk)


class OrderPermissionForm(forms.Form):
    mode = forms.ChoiceField(label="設定方式", choices=(("inherit", "沿用一般設定"), ("custom", "本筆自訂")), widget=forms.RadioSelect)
    can_view = forms.BooleanField(label="可以查看這筆訂單", required=False)
    can_print = forms.BooleanField(label="可以列印訂購單與客戶簽署文件", required=False)
    expected_revision = forms.IntegerField(min_value=0, widget=forms.HiddenInput)
    expected_identity_epoch = forms.IntegerField(min_value=0, widget=forms.HiddenInput)
    reason = forms.CharField(label="修改原因", max_length=500, widget=forms.Textarea(attrs={"rows": 3, "class": "form-control", "placeholder": "請說明開放、禁止或恢復一般設定的原因"}))


@root_required
@require_http_methods(["GET", "POST"])
def workspace(request, pk):
    account = get_object_or_404(get_user_model(), pk=pk)
    tab = request.GET.get("tab", "account")
    if tab not in {"account", "features", "scope", "orders"}:
        tab = "account"
    request.permission_account = account
    request.permission_tab = tab
    profile = OrderAccountProfile.objects.select_related("source").filter(user=account).first()
    request.permission_profile = profile
    if tab in {"features", "orders"} and is_root(account):
        return render(request, "sales/permissions/fixed.html")
    if tab == "orders":
        return order_permissions(request, account, profile)
    if tab == "scope":
        from sales.intake_views import order_account_scope
        response = order_account_scope(request, pk)
    elif profile and profile.kind == "dealer":
        from sales.dealer_account_views import dealer_account_edit
        response = dealer_account_edit(request, pk)
    elif tab == "features":
        from sales.access.views import edit
        response = edit(request, pk)
    else:
        from sales.views import user_account_edit
        response = user_account_edit(request, pk)
    if response.status_code == 302:
        return redirect(workspace_url(pk, tab))
    return response


def order_permissions(request, account, profile):
    policy = AccessPolicy(account)
    query = request.GET.get("q", "").strip()[:100]
    orders = SalesOrder.objects.filter(deleted_at__isnull=True).order_by("-pk")
    if query:
        orders = orders.filter(Q(number__icontains=query) | Q(owner_name__icontains=query))
    else:
        orders = orders.none()
    selected = request.GET.get("order", "")
    order = get_object_or_404(SalesOrder, pk=selected, deleted_at__isnull=True) if selected.isascii() and selected.isdigit() and len(selected) < 19 else None
    grant = OrderCustomerAccessGrant.objects.filter(account=profile, order=order).first() if profile and order else None
    valid = bool(grant and grant.active and grant.identity_epoch == profile.identity_epoch)
    can_view = bool(order and policy.screen("orders") and customer_orders(account).filter(pk=order.pk).exists())
    can_print = bool(order and policy.screen("order_documents", "export") and customer_orders(account, printing=True).filter(pk=order.pk).exists())
    form = None
    if order and profile:
        form = OrderPermissionForm(request.POST or None, initial={
            "mode": "custom" if valid else "inherit", "can_view": can_view, "can_print": can_print,
            "expected_revision": grant.revision if grant else 0, "expected_identity_epoch": profile.identity_epoch,
        })
        if request.method == "POST" and form.is_valid():
            data = form.cleaned_data
            try:
                set_customer_access(actor=request.user, order_id=order.pk, account_id=profile.pk,
                    expected_revision=data["expected_revision"], expected_identity_epoch=data["expected_identity_epoch"],
                    can_view=data["can_view"], can_print=data["can_print"], active=data["mode"] == "custom",
                    is_override=True, reason=data["reason"])
            except ValidationError as exc:
                form.add_error(None, exc)
            else:
                messages.success(request, "本筆權限已儲存，下次存取立即生效。" if data["mode"] == "custom" else "已恢復一般設定；實際結果如下。")
                return redirect(workspace_url(account.pk, "orders", order=order.pk))
    elif request.method == "POST":
        messages.error(request, "請先設定人員身分與訂單範圍，再選擇有效訂單。")
    return render(request, "sales/permissions/orders.html", {
        "query": query, "page_obj": Paginator(orders, 20).get_page(request.GET.get("page")),
        "selected_order": order, "form": form, "grant": grant, "grant_valid": valid,
        "effective_view": can_view, "effective_print": can_print,
        "feature_view": policy.screen("orders"), "feature_print": policy.screen("order_documents", "export"),
        "saved_grants": OrderCustomerAccessGrant.objects.filter(account=profile).select_related("order").order_by("-updated_at")[:20] if profile else [],
        "events": OrderEvent.objects.filter(order=order, event_type="customer_access_updated").order_by("-pk")[:10] if order else [],
    })


@root_required
@require_http_methods(["GET"])
def order_entry(request, pk):
    """訂單頁只導向中央工作區，不再維護另一份設定表單。"""
    order = get_object_or_404(SalesOrder, pk=pk)
    selected = request.GET.get("account", "")
    if selected.isascii() and selected.isdigit() and len(selected) < 19:
        profile = get_object_or_404(OrderAccountProfile, pk=selected)
        return redirect(workspace_url(profile.user_id, "orders", order=pk))
    return render(request, "sales/permissions/select_account.html", {
        "order": order, "accounts": OrderAccountProfile.objects.select_related("user", "source").exclude(user__username="admin").order_by("user__username"),
    })
