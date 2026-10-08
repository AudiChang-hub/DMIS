"""本人密碼重新驗證及立即鎖定；不代替畫面本身的授權。"""
from django import forms
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse, resolve, Resolver404
from urllib.parse import urlsplit
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST
from sales.access.services import policy_for
from sales.models import UserAccountAuditLog
from sales.services.profit_access import (
    IDLE_SECONDS, SESSION_KEY, can_view_profit, current_until, extend_unlock, start_unlock,
)


class ProfitUnlockForm(forms.Form):
    password = forms.CharField(label="目前登入帳號的密碼", strip=False, max_length=256,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password", "class": "form-control", "autofocus": True}))


def return_url(request):
    target = request.POST.get("next") or request.GET.get("next") or reverse("order_list")
    return target if target.startswith("/") and url_has_allowed_host_and_scheme(target, {request.get_host()}, require_https=request.is_secure()) else reverse("order_list")


@login_required
@never_cache
@require_http_methods(["GET", "POST"])
def profit_unlock(request):
    if not can_view_profit(request):
        raise PermissionDenied("尚未取得查看淨利權限，請洽 admin。")
    form = ProfitUnlockForm(request.POST or None)
    status = 200
    if request.method == "POST" and form.is_valid():
        key = f"profit-password-attempts:{request.user.pk}"
        cache.add(key, 0, timeout=300)
        try:
            attempts = cache.incr(key)
        except ValueError:
            cache.add(key, 1, timeout=300)
            attempts = 1
        if attempts > 5:
            form.add_error(None, "嘗試次數過多，請 5 分鐘後再試。")
            status = 429
        elif not request.user.check_password(form.cleaned_data["password"]):
            form.add_error("password", "密碼不正確。請輸入你自己的登入密碼。")
            UserAccountAuditLog.objects.create(actor=request.user, target=request.user,
                target_username=request.user.username, action="update", description="淨利解鎖驗證失敗")
            status = 400
        else:
            cache.delete(key)
            start_unlock(request)
            UserAccountAuditLog.objects.create(actor=request.user, target=request.user,
                target_username=request.user.username, action="update",
                description=f"本人密碼驗證成功，淨利解鎖（閒置 {IDLE_SECONDS // 60} 分鐘才鎖）")
            target = return_url(request)
            try:
                route = resolve(urlsplit(target).path).url_name
            except Resolver404:
                route = ""
            if route in {"operations_report_export", "report_records_export", "report_export"}:
                # 先回傳正常 HTML 結束密碼送出，再由使用者下載；不讓附件回應卡住原表單。
                return render(request, "sales/profit_download.html", {"download_url": target})
            return redirect(target)
    return render(request, "sales/profit_unlock.html", {"form": form, "next_url": return_url(request)}, status=status)


@login_required
@never_cache
@require_http_methods(["GET", "POST"])
def unlock_touch(request):
    """POST：畫面偵測到真人操作時延長閒置期限；GET：只查目前期限（供多分頁到期前確認），不延長。

    已過期的驗證不能被延長復活，回 409 並由畫面重新要求輸入密碼。
    """
    until = extend_unlock(request) if request.method == "POST" else current_until(request)
    if until is None:
        return JsonResponse({"ok": False, "locked": True}, status=409)
    return JsonResponse({"ok": True, "until": int(until * 1000)})


@login_required
@never_cache
@require_POST
def profit_lock(request):
    request.session.pop(SESSION_KEY, None)
    return redirect(return_url(request))
