"""顯示被遮罩資料（匯款帳戶、車控與電池密碼）前的本人驗證。

與淨利解鎖共用同一個「本人近期驗證」（sales.services.profit_access）：驗證有效期間（閒置 10 分鐘、
最長 8 小時）內免再輸入；沒有有效驗證就要求輸入本人登入密碼，通過後建立驗證。不保存密碼。
錯誤次數過多會暫停嘗試。
"""
from django.core.cache import cache
from django.http import JsonResponse

from sales.models import UserAccountAuditLog
from sales.services.profit_access import IDLE_SECONDS, reauth_is_valid, start_unlock

ATTEMPT_LIMIT = 5
ATTEMPT_WINDOW_SECONDS = 300


def reveal_password_denied(request, what):
    """可以顯示就回傳 None；否則回傳可直接送出的 JSON 回應。

    沒有有效驗證且沒給密碼時回 401＋need_password，讓畫面跳出密碼視窗再重送。
    """
    if reauth_is_valid(request):
        return None
    password = request.POST.get("password", "")
    if not password:
        return JsonResponse(
            {"ok": False, "need_password": True, "error": "請輸入你的登入密碼。"}, status=401)
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
    start_unlock(request)
    UserAccountAuditLog.objects.create(
        actor=request.user, target=request.user, target_username=request.user.username,
        action="update", description=f"本人密碼驗證成功，解鎖（閒置 {IDLE_SECONDS // 60} 分鐘才鎖）：{what}",
    )
    return None
