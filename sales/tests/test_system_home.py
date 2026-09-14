from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from sales.access.models import ScreenAccessGrant, UserAccessState
from sales.models import SystemAnnouncement, SystemAnnouncementRevision
from . import test_command_center


class SystemHomeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser("admin", password="test-only")
        cls.staff = get_user_model().objects.create_user("home-reader", password="test-only")
        cls.manager = get_user_model().objects.create_superuser("other-admin", password="test-only")
        UserAccessState.objects.create(user=cls.staff, configured=True)

    def data(self, **changes):
        data = {"title": "系統維護通知", "body": "週日維護\n請先儲存內容。", "starts_at": "2026-01-01T08:00",
                "ends_at": "", "expected_version": 0, "action": "save"}
        data.update(changes)
        return data

    def test_home_is_personal_without_company_or_order_queries(self):
        self.client.force_login(self.staff)
        with patch("sales.views.build_dashboard_metrics", side_effect=AssertionError("首頁不應查詢營運指標")):
            response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "home-reader")
        self.assertContains(response, "目前執行版本")
        self.assertNotIn("dashboard", response.context)
        self.assertNotIn("orders", response.context)
        self.assertNotContains(response, 'href="/operations/"')
        self.assertNotContains(response, 'href="/orders/"')
        self.assertNotContains(response, "管理系統公告")
        self.assertEqual(self.client.get(reverse("dashboard"), {"q": "客戶"}).status_code, 403)

    def test_legacy_home_search_redirects_with_all_filters(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("dashboard"), {"q": "姓名", "page": 2})
        self.assertRedirects(response, reverse("order_list") + "?q=%E5%A7%93%E5%90%8D&page=2")

    def test_home_release_history_and_update_fingerprint_are_independent(self):
        from config.release_notes import CURRENT_VERSION, RELEASES
        self.client.force_login(self.staff)
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, f"版本 {CURRENT_VERSION}")
        self.assertContains(response, 'class="release-entry" open', count=1)
        self.assertContains(response, "正式編版前更新紀錄")
        self.assertContains(response, "並非正式發布日期")
        self.assertContains(response, "技術資訊")
        self.assertEqual(response.context["release_history"], RELEASES)
        fingerprint = response.context["app_version"]
        self.assertRegex(fingerprint, r"^[0-9a-f]{12}$")
        self.assertContains(response, f'data-app-version="{fingerprint}"')
        self.assertContains(self.client.get(reverse("user_guide")), f"系統版本 {CURRENT_VERSION}")

    def test_visibility_boundaries_order_and_escaping(self):
        now = timezone.now()
        first = SystemAnnouncement.objects.create(title="一般公告", body="一般", starts_at=now, published=True)
        pinned = SystemAnnouncement.objects.create(title="<script>測試</script>", body="<img onerror=alert(1)>",
            starts_at=now-timedelta(days=1), pinned=True, published=True)
        for name, attrs in [("草稿秘密", {"published": False}), ("未到時間", {"starts_at": now+timedelta(hours=1)}),
                            ("過期公告", {"ends_at": now})]:
            fields = {"title": name, "body": name, "published": True, "starts_at": now-timedelta(days=2), **attrs}
            SystemAnnouncement.objects.create(**fields)
        self.assertEqual(list(SystemAnnouncement.visible(now)), [pinned, first])
        self.client.force_login(self.staff)
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, "&lt;script&gt;測試&lt;/script&gt;")
        self.assertContains(response, "&lt;img onerror=alert(1)&gt;")
        for text in ("草稿秘密", "未到時間", "過期公告"):
            self.assertNotContains(response, text)

    def test_admin_only_including_direct_posts_and_csrf(self):
        url = reverse("announcement_manage")
        self.assertEqual(self.client.get(url).status_code, 302)
        for user in (self.staff, self.manager):
            self.client.force_login(user)
            for method in ("get", "post"):
                self.assertEqual(getattr(self.client, method)(url, self.data()).status_code, 403)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.admin)
        self.assertEqual(csrf_client.post(url, self.data()).status_code, 403)
        self.assertEqual(SystemAnnouncement.objects.count(), 0)

    def test_draft_publish_unpublish_and_audit(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.post(reverse("announcement_manage"), self.data()).status_code, 302)
        item = SystemAnnouncement.objects.get()
        self.assertFalse(item.published)
        self.assertEqual(item.version, 1)
        url = reverse("announcement_edit", args=[item.pk])
        self.assertEqual(self.client.post(url, self.data(expected_version=1, action="publish")).status_code, 302)
        item.refresh_from_db()
        self.assertTrue(item.published)
        self.assertEqual(self.client.post(url, self.data(expected_version=2, action="unpublish")).status_code, 302)
        item.refresh_from_db()
        self.assertFalse(item.published)
        self.assertEqual(item.version, 3)
        self.assertEqual(list(item.revisions.values_list("version", flat=True)), [3, 2, 1])
        self.assertEqual(item.revisions.first().actor_name, "admin")

    def test_stale_edit_is_not_overwritten_and_window_is_validated(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("announcement_manage"), self.data(action="publish"))
        item = SystemAnnouncement.objects.get()
        url = reverse("announcement_edit", args=[item.pk])
        stale = self.client.post(url, self.data(title="不能覆寫", expected_version=0))
        self.assertEqual(stale.status_code, 409)
        self.assertContains(stale, "本次未覆寫", status_code=409)
        item.refresh_from_db()
        self.assertEqual(item.title, "系統維護通知")
        self.assertEqual(SystemAnnouncementRevision.objects.count(), 1)
        response = self.client.post(url, self.data(expected_version=1, ends_at="2026-01-01T08:00"))
        self.assertContains(response, "結束時間必須晚於開始時間")
        self.assertEqual(SystemAnnouncementRevision.objects.count(), 1)

    def test_general_operations_grant_does_not_gain_company_workload(self):
        ScreenAccessGrant.objects.create(user=self.staff, screen_key="operations", view=True)
        self.client.force_login(self.staff)
        response = self.client.get(reverse("operations_report"))
        self.assertContains(response, "近 12 個月公司走勢")
        self.assertNotContains(response, "即時工作量")
        self.assertNotContains(response, "庫存概況")
        self.assertNotContains(response, 'href="/orders/')
        self.assertNotIn("orders", response.context)
        self.assertNotIn("page_obj", response.context)
        self.assertEqual(self.client.get(reverse("operations_report_export")).status_code, 403)

    def test_scheduled_publication_and_preserved_publish_state(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("announcement_manage"), self.data(action="publish", starts_at="2099-01-01T08:00"))
        item = SystemAnnouncement.objects.get()
        self.assertEqual(item.display_status, "預約發布")
        self.assertFalse(SystemAnnouncement.visible().exists())
        self.client.post(reverse("announcement_edit", args=[item.pk]), self.data(expected_version=1, title="維持發布狀態", starts_at="2099-01-01T08:00"))
        item.refresh_from_db()
        self.assertTrue(item.published)
        self.assertEqual(item.version, 2)


class OperationsNavigationTests(TestCase):
    make_order = test_command_center.CommandCenterTests.make_order

    @classmethod
    def setUpTestData(cls):
        test_command_center.CommandCenterTests.setUpTestData.__func__(cls)

    def setUp(self):
        self.client.force_login(self.user)

    def test_month_drilldown_and_legacy_redirect_match_counts(self):
        today = timezone.localdate()
        included = self.make_order(today)
        self.make_order(today, status="cancelled")
        self.make_order(today-timedelta(days=45))
        self.make_order()
        params = {"date_from": today.replace(day=1).isoformat(), "date_to": today.isoformat(), "business_only": "1"}
        page = self.client.get(reverse("order_list"), params)
        self.assertEqual([o.pk for o in page.context["orders"]], [included.pk])
        report = self.client.get(reverse("operations_report"))
        self.assertEqual(report.context["dashboard"]["performance"]["count"], page.context["page_obj"].paginator.count)
        self.assertNotContains(report, included.number)
        self.assertNotContains(report, included.owner_name)
        redirected = self.client.get(reverse("operations_report"), params, follow=True)
        self.assertEqual([o.pk for o in redirected.context["orders"]], [included.pk])

    def test_risks_share_same_order_set_and_preserve_sort_page_filters(self):
        from sales.models import PaymentRecord
        order = self.make_order(timezone.localdate())
        refund = self.make_order(status="cancel_refund_pending")
        for _ in range(2):
            PaymentRecord.objects.create(order=order, expected_amount=500, received_amount=100)
        for risk, target in (("outstanding", order), ("unconfirmed", order), ("refund", refund)):
            with self.subTest(risk=risk):
                response = self.client.get(reverse("order_list"), {"risk": risk, "sort": "-registration_date", "per_page": 25})
                self.assertEqual([o.pk for o in response.context["orders"]], [target.pk])
                self.assertContains(response, f'name="risk" value="{risk}"')
                self.assertContains(response, f"risk={risk}&amp;sort=")

    def test_blank_dates_keep_unregistered_but_invalid_dates_fail_closed(self):
        self.make_order()
        self.make_order(timezone.localdate())
        page = self.client.get(reverse("order_list"), {"date_from": "", "date_to": "", "sort": "-registration_date"})
        self.assertEqual(page.context["page_obj"].paginator.count, 2)
        self.assertIsNone(page.context["orders"][0].registration_date)
        for params in ({"date_from": "not-a-date"}, {"date_from": "2026-02-30"},
                       {"date_from": "2026-09-20", "date_to": "2026-09-01"}):
            with self.subTest(params=params):
                self.assertEqual(self.client.get(reverse("order_list"), params).status_code, 400)
                self.assertEqual(self.client.get(reverse("operations_report_export"), params).status_code, 400)

    def test_fee_variance_count_matches_drilldown_and_excludes_cancelled(self):
        from sales.models import SalesOrder
        from sales.services.order_filters import fee_variance_orders
        order = self.make_order(timezone.localdate())
        cancelled = self.make_order(timezone.localdate(), status="cancel_refund_pending")
        SalesOrder.objects.filter(pk__in=[order.pk, cancelled.pk]).update(registration_calculated_total=1000, plate_insurance_fee=2000)
        response = self.client.get(reverse("order_list"), {"attention": "fees"})
        self.assertEqual([o.pk for o in response.context["orders"]], [order.pk])
        self.assertEqual(self.client.get(reverse("operations_report")).context["fee_variance_count"], 1)
        self.assertEqual(fee_variance_orders(SalesOrder.objects.all()).count(), 1)
