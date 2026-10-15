"""既有財務功能測試的淨利授權 fixture。

2026-10-15 起淨利不再需要本人密碼解鎖，有 `profit` 畫面授權即可查看；函式名稱沿用。
"""
from sales.access.models import ScreenAccessGrant, UserAccessState
from sales.access.services import AccessPolicy, snapshot


def unlock_profit(testcase, user):
    policy = AccessPolicy(user)
    if not policy.root:
        if not policy.configured:
            for key, grant in snapshot(user, [])['screens'].items():
                ScreenAccessGrant.objects.update_or_create(user=user, screen_key=key, defaults=grant)
            UserAccessState.objects.update_or_create(user=user, defaults={'configured': True})
        ScreenAccessGrant.objects.update_or_create(user=user, screen_key='profit',
            defaults={'view': True, 'export': True})
