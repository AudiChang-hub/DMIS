"""2.35.6 版本說明受眾：基礎傭金移位那則給「車行傭金與銷售獎勵」權限的人看（T-286）。"""
from django.contrib.auth import get_user_model
from django.test import TestCase

from sales.access.models import ScreenAccessGrant, UserAccessState
from sales.access.services import AccessPolicy
from sales.services.audience_content import release_context

COMMISSION_ITEM = "車行基礎傭金改在「車行傭金與銷售獎勵」逐列設定"
WORKSPACE_ITEM = "機種工作區的「傭金與獎勵」「結算成本」「原廠獎勵與補助」三個分頁改成只能看"


def items_2356(user):
    for entry in release_context(AccessPolicy(user))["release_history"]:
        if entry["version"] == "2.35.6":
            return [item for group in entry["changes"] for item in group["items"]]
    return []


class Release2356AudienceTests(TestCase):
    def make_user(self, username, *screens):
        user = get_user_model().objects.create_user(username, password="Audience-test-2356!")
        UserAccessState.objects.create(user=user, configured=True)
        for key in screens:
            ScreenAccessGrant.objects.create(user=user, screen_key=key, view=True)
        return user

    def test_commission_only_user_sees_commission_item(self):
        items = items_2356(self.make_user("commission_only", "commissions"))
        self.assertTrue(any(COMMISSION_ITEM in item for item in items))
        self.assertFalse(any(WORKSPACE_ITEM in item for item in items))

    def test_user_without_commission_screen_does_not_see_it(self):
        items = items_2356(self.make_user("orders_only", "orders"))
        self.assertFalse(any(COMMISSION_ITEM in item for item in items))

    def test_root_sees_all_six_items(self):
        root = get_user_model().objects.create_superuser("root2356", password="Audience-test-2356!")
        items = items_2356(root)
        self.assertEqual(len(items), 6)
        self.assertTrue(any(COMMISSION_ITEM in item for item in items))
        self.assertTrue(any(WORKSPACE_ITEM in item for item in items))
