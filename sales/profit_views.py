"""本人密碼重新驗證及立即鎖定；不代替畫面本身的授權。"""
from django import forms
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST
from sales.access.services import policy_for
from sales.models import UserAccountAuditLog
from sales.services.profit_access import SESSION_KEY, UNLOCK_SECONDS, can_view_profit


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
            request.session[SESSION_KEY] = {"user": request.user.pk,
                "version": policy_for(request).version, "auth": request.user.get_session_auth_hash(),
                "until": timezone.now().timestamp() + UNLOCK_SECONDS}
            UserAccountAuditLog.objects.create(actor=request.user, target=request.user,
                target_username=request.user.username, action="update", description="本人密碼驗證成功，淨利解鎖 5 分鐘")
            return redirect(return_url(request))
    return render(request, "sales/profit_unlock.html", {"form": form, "next_url": return_url(request)}, status=status)


@login_required
@never_cache
@require_POST
def profit_lock(request):
    request.session.pop(SESSION_KEY, None)
    return redirect(return_url(request))
