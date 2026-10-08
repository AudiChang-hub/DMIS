"""本人近期驗證（淨利解鎖、顯示被遮罩資料共用）；只在伺服器 session 保存短期驗證，不保存密碼。

規則：輸入本人密碼後，閒置 IDLE_SECONDS 才失效；畫面偵測到真人操作時由 `extend_unlock`
往後延長，但從驗證起算最長 MAX_SECONDS，到了一定要重新輸入密碼。已過期的驗證不能被延長復活。
"""
import math

from django.urls import reverse
from django.utils import timezone

from sales.access.services import policy_for

SESSION_KEY = "profit_unlock"
IDLE_SECONDS = 10 * 60
MAX_SECONDS = 8 * 60 * 60
UNLOCK_SECONDS = IDLE_SECONDS  # 舊名稱：第一次解鎖的有效秒數


def can_view_profit(request):
    return policy_for(request).screen("profit")


def _token(request):
    session = getattr(request, "session", None)
    token = session.get(SESSION_KEY, {}) if session is not None else {}
    return token if isinstance(token, dict) else {}


def _token_is_valid(request):
    token = _token(request)
    until = token.get("until", 0)
    return bool(
        isinstance(until, (int, float)) and math.isfinite(until)
        and timezone.now().timestamp() < until
        and token.get("user") == request.user.pk
        and token.get("version") == policy_for(request).version
        and token.get("auth") == request.user.get_session_auth_hash()
    )


def reauth_is_valid(request):
    """本人近期（閒置未逾時、未過上限）輸入過密碼；不代表有淨利權限。"""
    return bool(request.user.is_authenticated and _token_is_valid(request))


def profit_is_unlocked(request):
    return can_view_profit(request) and _token_is_valid(request)


def start_unlock(request):
    """密碼驗證成功後建立（或重設）驗證；回傳到期時間（秒）。"""
    now = timezone.now().timestamp()
    request.session[SESSION_KEY] = {
        "user": request.user.pk,
        "version": policy_for(request).version,
        "auth": request.user.get_session_auth_hash(),
        "until": now + IDLE_SECONDS,
        "max_until": now + MAX_SECONDS,
    }
    return request.session[SESSION_KEY]["until"]


def current_until(request):
    return _token(request)["until"] if reauth_is_valid(request) else None


def extend_unlock(request):
    """真人操作時延長閒置期限；已過期、身分或權限版本不符、或舊式無上限的驗證都不延長。"""
    if not reauth_is_valid(request):
        return None
    token = dict(_token(request))
    cap = token.get("max_until")
    if not isinstance(cap, (int, float)) or not math.isfinite(cap):
        return token["until"]
    new_until = min(timezone.now().timestamp() + IDLE_SECONDS, cap)
    if new_until > token["until"]:
        token["until"] = new_until
        request.session[SESSION_KEY] = token
    return token["until"]


def profit_context(request):
    unlocked = profit_is_unlocked(request)
    until = current_until(request) if request.user.is_authenticated else None
    return {"profit_allowed": can_view_profit(request), "profit_unlocked": unlocked,
            "profit_unlock_until": int(_token(request)["until"] * 1000) if unlocked else 0,
            "unlock_until": int(until * 1000) if until else 0,
            "unlock_touch_url": reverse("unlock_touch") if until else "",
            "unlock_idle_minutes": IDLE_SECONDS // 60, "unlock_max_hours": MAX_SECONDS // 3600}
