import hashlib
from django.contrib.auth import views as auth_views
from django.contrib.admin.forms import AdminAuthenticationForm
from django.core.cache import cache


class ThrottledLoginView(auth_views.LoginView):
    """以帳號與來源位址限制連續登入失敗，避免密碼遭反覆嘗試。"""

    failure_limit = 5
    window_seconds = 15 * 60
    lock_seconds = 15 * 60

    def _attempt_digest(self):
        username = (self.request.POST.get("username") or "").strip().casefold()
        remote_address = self.request.META.get("REMOTE_ADDR", "unknown")
        return hashlib.sha256(f"{username}|{remote_address}".encode()).hexdigest()

    def _failure_key(self):
        return f"login-failures:{self._attempt_digest()}"

    def _lock_key(self):
        return f"login-lock:{self._attempt_digest()}"

    def _record_failure(self):
        failure_key = self._failure_key()
        if cache.add(failure_key, 1, timeout=self.window_seconds):
            failures = 1
        else:
            try:
                failures = cache.incr(failure_key)
            except ValueError:
                # The counter may expire between ``add`` and ``incr``.
                cache.set(failure_key, 1, timeout=self.window_seconds)
                failures = 1
        if failures >= self.failure_limit:
            cache.set(self._lock_key(), True, timeout=self.lock_seconds)
        return failures

    def post(self, request, *args, **kwargs):
        self._blocked_login = False
        if cache.get(self._lock_key()):
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
        cache.delete_many([self._failure_key(), self._lock_key()])
        return super().form_valid(form)


class ThrottledAdminLoginView(ThrottledLoginView):
    """Apply the same throttle to Django admin without admitting non-staff users."""

    form_class = AdminAuthenticationForm
