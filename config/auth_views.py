import hashlib
import logging

from django.contrib.auth import views as auth_views
from django.contrib.admin.forms import AdminAuthenticationForm
from django.core.cache import cache


security_logger = logging.getLogger("dmis.security")


def _increment(key, timeout):
    if cache.add(key, 1, timeout=timeout):
        return 1
    try:
        return cache.incr(key)
    except ValueError:
        # The counter may expire between ``add`` and ``incr``.
        cache.set(key, 1, timeout=timeout)
        return 1


def clear_account_login_lock(username):
    """維運用：解除某帳號的「每帳號」登入暫停（不影響各來源位址的計數）。"""
    digest = hashlib.sha256(username.strip().casefold().encode()).hexdigest()
    cache.delete_many([f"login-account-failures:{digest}", f"login-account-lock:{digest}"])


class ThrottledLoginView(auth_views.LoginView):
    """以帳號與來源位址限制連續登入失敗，避免密碼遭反覆嘗試。

    來源位址由 tunnel-proxy 以 Cloudflare 的 CF-Connecting-IP 覆寫，用戶端無法偽造；
    另加每帳號、不分來源的上限，換再多位址也只能猜有限次數。
    """

    failure_limit = 5
    window_seconds = 15 * 60
    lock_seconds = 15 * 60
    account_failure_limit = 20
    account_window_seconds = 60 * 60

    def _username(self):
        return (self.request.POST.get("username") or "").strip().casefold()

    def _attempt_digest(self):
        remote_address = self.request.META.get("REMOTE_ADDR", "unknown")
        return hashlib.sha256(f"{self._username()}|{remote_address}".encode()).hexdigest()

    def _account_digest(self):
        return hashlib.sha256(self._username().encode()).hexdigest()

    def _failure_key(self):
        return f"login-failures:{self._attempt_digest()}"

    def _lock_key(self):
        return f"login-lock:{self._attempt_digest()}"

    def _account_failure_key(self):
        return f"login-account-failures:{self._account_digest()}"

    def _account_lock_key(self):
        return f"login-account-lock:{self._account_digest()}"

    def _record_failure(self):
        failures = _increment(self._failure_key(), self.window_seconds)
        if failures >= self.failure_limit:
            cache.set(self._lock_key(), True, timeout=self.lock_seconds)
        account_failures = _increment(self._account_failure_key(), self.account_window_seconds)
        if account_failures >= self.account_failure_limit:
            if cache.add(self._account_lock_key(), True, timeout=self.lock_seconds):
                security_logger.warning(
                    "login_account_locked account=%s failures=%s",
                    self._account_digest()[:12],
                    account_failures,
                )
        return failures

    def post(self, request, *args, **kwargs):
        self._blocked_login = False
        if cache.get(self._lock_key()) or cache.get(self._account_lock_key()):
            self._blocked_login = True
            form = self.get_form()
            form.add_error(
                None,
                "登入失敗次數過多，請 15 分鐘後再試；若為急件，請聯絡系統管理人員。",
            )
            return self.form_invalid(form)
        return super().post(request, *args, **kwargs)

    def form_invalid(self, form):
        if not getattr(self, "_blocked_login", False):
            if self._record_failure() >= self.failure_limit:
                form.add_error(
                    None,
                    "登入失敗次數過多，帳號已暫停嘗試 15 分鐘。",
                )
        return super().form_invalid(form)

    def form_valid(self, form):
        # 只清本來源的計數；帳號計數留著，避免攻擊者夾雜一次成功登入就重置上限。
        cache.delete_many([self._failure_key(), self._lock_key()])
        return super().form_valid(form)


class ThrottledAdminLoginView(ThrottledLoginView):
    """Apply the same throttle to Django admin without admitting non-staff users."""

    form_class = AdminAuthenticationForm
