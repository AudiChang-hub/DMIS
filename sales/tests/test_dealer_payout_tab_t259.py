"""T-259（使用者 2026-11-20 選 A）：車行傭金／獎金給付從報表中心移到資料維護區「車行傭金與獎勵」的〈給付〉頁籤。

沿用 dealer_payouts 權限，頁籤只對有權限的人顯示；報表中心完全拿掉這張；舊網址連同篩選與匯出條件導到新位置。
給付頁本身的計算、勾選、結算、匯出不變（既有測試 test_dealer_payouts_t150、test_volume_bonus_settle_t203）。
"""
import re
from urllib.parse import parse_qs, urlsplit

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from sales.access.models import ScreenAccessGrant, UserAccessState

TAB_NAV = re.compile(r'<nav class="account-tabs dealer-reward-tabs" aria-label="車行傭金與獎勵">(.*?)</nav>', re.S)


class DealerPayoutTabTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        users = get_user_model().objects
        cls.root = users.create_superuser("admin", password="Test-Only-123")
        cls.payout_only = users.create_user("payout-only", password="Test-Only-123")
        cls.commission_only = users.create_user("commission-only", password="Test-Only-123")
        cls.viewer = users.create_user("payout-viewer", password="Test-Only-123")
        for user, grants in ((cls.payout_only, {"dealer_payouts": dict(view=True, operate=True, export=True)}),
                             (cls.commission_only, {"commissions": dict(view=True, operate=True)}),
                             (cls.viewer, {"dealer_payouts": dict(view=True), "commissions": dict(view=True)})):
            UserAccessState.objects.create(user=user, configured=True)
            for key, flags in grants.items():
                ScreenAccessGrant.objects.create(user=user, screen_key=key, **flags)

    def tabs(self, response):
        nav = TAB_NAV.search(response.content.decode())
        self.assertIsNotNone(nav)
        return re.findall(r'<a href="([^"]+)"( aria-current="page")?>([^<]+)</a>', nav[1])

    def test_payout_page_lives_under_data_maintenance_as_a_tab(self):
        self.client.force_login(self.root)
        response = self.client.get(reverse("dealer_payout_list"))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(reverse("dealer_payout_list").startswith("/data/"))
        self.assertIn((reverse("dealer_payout_list"), ' aria-current="page"', "給付"), self.tabs(response))
        html = response.content.decode()
        self.assertIn("車行傭金與獎勵", html)
        self.assertIn(reverse("data_maintenance"), html)  # 返回資料維護區
        self.assertNotIn("report-page-nav", html)
        self.assertNotIn("報表中心 · 給付追蹤", html)
        self.assertTrue(response.context["is_data_maintenance_section"])  # 頂部選單亮「資料維護區」，不是報表中心

    def test_tab_shows_only_with_payout_permission(self):
        self.client.force_login(self.commission_only)
        tabs = self.tabs(self.client.get(reverse("dealer_sales_program_list")))
        self.assertNotIn("給付", [text for _, _, text in tabs])
        self.assertEqual(self.client.get(reverse("dealer_payout_list")).status_code, 403)
        self.client.force_login(self.viewer)
        tabs = self.tabs(self.client.get(reverse("dealer_sales_program_list")))
        self.assertEqual([text for _, _, text in tabs], ["基礎傭金", "獎勵活動", "給付"])

    def test_payout_only_account_reaches_the_tab_from_data_maintenance(self):
        self.client.force_login(self.payout_only)
        page = self.client.get(reverse("data_maintenance"))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, f'<a class="maintenance-card" href="{reverse("dealer_payout_list")}">', html=False)
        response = self.client.get(reverse("dealer_payout_list"))
        self.assertEqual([text for _, _, text in self.tabs(response)], ["給付"])
        self.assertEqual(self.client.get(reverse("report_center")).status_code, 403)  # 報表中心不再因給付權限開放

    def test_report_center_no_longer_lists_or_redirects_to_payouts(self):
        self.client.force_login(self.root)
        center = self.client.get(reverse("report_center"), follow=True)
        self.assertEqual(center.status_code, 200)
        html = center.content.decode()
        self.assertNotIn(reverse("dealer_payout_list"), html)
        self.assertNotIn("給付追蹤", html)

    def test_old_urls_redirect_with_filters_and_export_params(self):
        self.client.force_login(self.root)
        query = {"dealer": "7", "status": "unpaid", "start": "2026-10-01", "estimate": "1"}
        response = self.client.get("/reports/dealer-payouts/", query)
        self.assertEqual(response.status_code, 302)
        target = urlsplit(response["Location"])
        self.assertEqual(target.path, reverse("dealer_payout_list"))
        self.assertEqual({key: values[0] for key, values in parse_qs(target.query).items()}, query)
        bare = self.client.get("/reports/dealer-payouts/")
        self.assertRedirects(bare, reverse("dealer_payout_list"))
        export = self.client.get("/reports/dealer-payouts/export/", {"status": "paid", "kind": "commission"})
        self.assertEqual(export.status_code, 302)
        target = urlsplit(export["Location"])
        self.assertEqual(target.path, reverse("dealer_payout_export"))
        self.assertEqual(parse_qs(target.query), {"status": ["paid"], "kind": ["commission"]})
        followed = self.client.get(export["Location"])
        self.assertEqual(followed.status_code, 200)
        self.assertIn("text/csv", followed["Content-Type"])

    def test_old_urls_keep_the_payout_permission(self):
        self.client.force_login(self.commission_only)
        self.assertEqual(self.client.get("/reports/dealer-payouts/").status_code, 403)
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get("/reports/dealer-payouts/").status_code, 302)
        self.assertEqual(self.client.get("/reports/dealer-payouts/export/").status_code, 403)  # 沒有匯出權限
        self.assertEqual(self.client.post("/reports/dealer-payouts/update/", {"action": "paid", "key": "x"}).status_code, 403)

    def test_old_update_url_still_accepts_posts_from_open_pages(self):
        self.client.force_login(self.root)
        response = self.client.post("/reports/dealer-payouts/update/", {"action": "paid", "key": "missing:0"})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith(reverse("dealer_payout_list")))

    def test_permission_page_groups_payouts_with_dealer_rules(self):
        from sales.access.registry import BY_KEY, SCREEN_GROUPS
        self.assertEqual(BY_KEY["dealer_payouts"].label, "車行傭金／獎金給付")
        groups = {key: [item for _, keys in sections for item in keys] for key, _, sections in SCREEN_GROUPS}
        self.assertIn("dealer_payouts", groups["data"])
        self.assertNotIn("dealer_payouts", groups["reports"])
