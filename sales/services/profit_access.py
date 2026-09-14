"""淨利二次驗證；只在伺服器 session 保存短期驗證，不保存密碼。"""
import math
from django.utils import timezone
from sales.access.services import policy_for

SESSION_KEY = "profit_unlock"
UNLOCK_SECONDS = 300


def can_view_profit(request):
    return policy_for(request).screen("profit")


def profit_is_unlocked(request):
    if not can_view_profit(request):
        return False
    token = request.session.get(SESSION_KEY, {})
    if not isinstance(token, dict):
        return False
    until = token.get("until", 0)
    return bool(isinstance(until, (int, float)) and math.isfinite(until)
        and timezone.now().timestamp() < until
        and token.get("user") == request.user.pk
        and token.get("version") == policy_for(request).version
        and token.get("auth") == request.user.get_session_auth_hash())


def profit_context(request):
    unlocked = profit_is_unlocked(request)
    return {"profit_allowed": can_view_profit(request), "profit_unlocked": unlocked,
            "profit_unlock_until": int(request.session[SESSION_KEY]["until"] * 1000) if unlocked else 0}
