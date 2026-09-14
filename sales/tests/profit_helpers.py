"""既有財務功能測試的明確授權／已驗證 session fixture。

密碼驗證、逾期及撤權本身由 test_profit_privacy_ux 獨立驗收。
"""
from django.utils import timezone
from sales.access.models import ScreenAccessGrant, UserAccessState
from sales.access.services import AccessPolicy, snapshot
from sales.services.profit_access import SESSION_KEY


def unlock_profit(testcase, user):
    policy = AccessPolicy(user)
    if not policy.root:
        if not policy.configured:
            for key, grant in snapshot(user, [])['screens'].items():
                ScreenAccessGrant.objects.update_or_create(user=user, screen_key=key, defaults=grant)
            UserAccessState.objects.update_or_create(user=user, defaults={'configured': True})
        ScreenAccessGrant.objects.update_or_create(user=user, screen_key='profit',
            defaults={'view': True, 'export': True})
    session = testcase.client.session
    session[SESSION_KEY] = {'user': user.pk, 'version': AccessPolicy(user).version,
        'auth': user.get_session_auth_hash(), 'until': timezone.now().timestamp() + 300}
    session.save()
