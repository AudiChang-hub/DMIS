"""顯示被遮罩資料（匯款帳戶、車控與電池密碼）前，要求輸入本人登入密碼。

每次顯示都要重新輸入；不保存密碼、不建立解鎖 session。錯誤次數過多會暫停嘗試。
"""
from django.core.cache import cache
from django.http import JsonResponse

from sales.models import UserAccountAuditLog

ATTEMPT_LIMIT = 5
ATTEMPT_WINDOW_SECONDS = 300


def reveal_password_denied(request, what):
    """密碼正確回傳 None；否則回傳可直接送出的 JSON 錯誤回應。"""
    password = request.POST.get("password", "")
    if not password:
        return JsonResponse({"ok": False, "error": "請輸入你的登入密碼。"}, status=400)
    key = f"reveal-password-attempts:{request.user.pk}"
    cache.add(key, 0, timeout=ATTEMPT_WINDOW_SECONDS)
    try:
        attempts = cache.incr(key)
    except ValueError:
        cache.add(key, 1, timeout=ATTEMPT_WINDOW_SECONDS)
        attempts = 1
    if attempts > ATTEMPT_LIMIT:
        return JsonResponse({"ok": False, "error": "嘗試次數過多，請 5 分鐘後再試。"}, status=429)
    if not request.user.check_password(password):
        UserAccountAuditLog.objects.create(
            actor=request.user, target=request.user, target_username=request.user.username,
            action="update", description=f"查看{what}的密碼驗證失敗",
        )
        return JsonResponse({"ok": False, "error": "密碼不正確。請輸入你自己的登入密碼。"}, status=400)
    cache.delete(key)
    return None
