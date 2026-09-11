from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.utils.cache import patch_cache_control, patch_vary_headers
from django.utils.deprecation import MiddlewareMixin

from .registry import LOOKUPS, PERSONAL, REPORT_ROUTES, ROOT_ONLY, ROUTES, SPECIAL
from .services import is_root, policy_for


class ScreenAccessMiddleware(MiddlewareMixin):
    def process_view(self, request, view_func, view_args, view_kwargs):
        if not request.user.is_authenticated:
            return None  # 沿用原登入 redirect 與公開健康檢查。
        match = request.resolver_match
        name = match.url_name
        target = getattr(view_func, "view_initkwargs", {}).get("pattern_name")
        if target:
            name = target
        # 即使尚未套用新制，其他管理者也不能接管 root 帳號。
        if name in {"user_account_edit", "user_account_status", "user_account_reset_password"}:
            target_user = get_user_model().objects.filter(pk=view_kwargs.get("pk")).first()
            if target_user and target_user.get_username() == "admin":
                if not is_root(request.user) or name == "user_account_status":
                    raise PermissionDenied
                if name == "user_account_edit" and request.method == "POST" and (
                    request.POST.get("username") != "admin" or not request.POST.get("is_superuser") or not request.POST.get("is_active")
                ):
                    raise PermissionDenied
        if name in {"user_account_create", "user_account_edit"} and request.method == "POST" and request.POST.get("username") == "admin" and not is_root(request.user):
            raise PermissionDenied
        policy = policy_for(request)
        if policy.root or not policy.configured:
            # 舊制與 root 交回原 view 的資格與 404／400 語意；上方帳號防接管仍執行。
            return None
        if match.app_name == "admin":
            if policy.configured and not policy.root:
                raise PermissionDenied
            return None
        known = name in (set(ROUTES) | PERSONAL | ROOT_ONLY | set(REPORT_ROUTES) | set(LOOKUPS) | SPECIAL)
        allowed = policy.route(name, request.method, view_kwargs)
        if policy.configured and not policy.root and not known:
            allowed = False
        if not allowed:
            if name == "dashboard" and request.method in {"GET", "HEAD"}:
                return redirect("access_home")
            raise PermissionDenied("尚未獲授權使用此功能，請洽 admin 調整畫面權限。")

    def process_response(self, request, response):
        if getattr(request, "user", None) and request.user.is_authenticated:
            patch_cache_control(response, private=True, no_store=True)
            patch_vary_headers(response, ("Cookie",))
        return response
