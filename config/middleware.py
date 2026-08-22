import logging
import uuid

from django.shortcuts import redirect
from django.urls import reverse


logger = logging.getLogger("dmis.request")


class RequestIdMiddleware:
    """為每個請求建立不含個資的查修編號。"""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.request_id = uuid.uuid4().hex[:12].upper()
        response = self.get_response(request)
        response["X-Request-ID"] = request.request_id
        if response.status_code >= 500:
            logger.error(
                "request_failed request_id=%s method=%s path=%s status=%s",
                request.request_id,
                request.method,
                request.path,
                response.status_code,
            )
        return response


class ForcePasswordChangeMiddleware:
    """將使用臨時密碼的帳號限制在變更密碼頁，避免繼續共用初始密碼。"""

    EXEMPT_PREFIXES = ("/static/", "/media/", "/health/")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated and not request.path.startswith(self.EXEMPT_PREFIXES):
            profile = getattr(request.user, "security_profile", None)
            if profile and profile.must_change_password:
                allowed_paths = {
                    reverse("password_change_required"),
                    reverse("logout"),
                }
                if request.path not in allowed_paths:
                    return redirect("password_change_required")
        return self.get_response(request)
