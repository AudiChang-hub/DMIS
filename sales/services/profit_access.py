"""淨利是否可見：只看 `profit` 畫面授權。

2026-10-15 起系統定調為只有店內人員使用，取消淨利解鎖／本人密碼重新驗證；
有授權就直接顯示，沒有授權仍不顯示。
"""
from sales.access.services import policy_for


def can_view_profit(request):
    return policy_for(request).screen("profit")


def profit_is_unlocked(request):
    """舊名稱保留給呼叫端；等同有沒有淨利畫面授權。"""
    return can_view_profit(request)


def profit_context(request):
    allowed = can_view_profit(request)
    return {"profit_allowed": allowed, "profit_unlocked": allowed}
