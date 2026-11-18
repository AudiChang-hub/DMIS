"""T-237：價格表分發的完成進度跟著「負責人」篩選計算（我的車行／未指派／指定某人／全部）。
搜尋、完成進度、縣市、行政區篩選不影響進度；勾「完成」後回傳的進度也一樣。"""
from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from sales.models import SalesSource, SalesSourceBrandPolicy, SalesSourceCooperationProfile
from sales.services.price_list_distribution import ensure_distribution_month


class PriceListProgressByOwnerTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="t237-me", first_name="我", password="test-password")
        self.colleague = User.objects.create_user(username="t237-colleague", first_name="同事", password="test-password")
        self.client.force_login(self.user)
        rows = [  # (名稱, 縣市, 負責人, 已完成)
            ("我的一", "新北市", self.user, True), ("我的二", "新北市", self.user, False), ("我的三", "臺北市", self.user, False),
            ("同事一", "新北市", self.colleague, True), ("同事二", "新北市", self.colleague, True),
            ("未指派", "新北市", None, False),
        ]
        dealers = []
        for name, city, _, _ in rows:
            dealer = SalesSource.objects.create(source_type=SalesSource.SourceType.DEALER, name=name, city=city,
                                                address=f"{city}測試路1號")
            SalesSourceCooperationProfile.objects.create(source=dealer, cooperates=True,
                                                         cooperation_scope=SalesSourceBrandPolicy.CooperationScope.SYM)
            dealers.append(dealer)
        self.distribution, _ = ensure_distribution_month(date(2026, 9, 1))
        for dealer, (_, _, owner, completed) in zip(dealers, rows):
            self.distribution.items.filter(dealer=dealer).update(
                assigned_to=owner, assigned_to_name=owner.first_name if owner else "", completed=completed)
        self.mine_pending = self.distribution.items.get(dealer_name="我的二")

    def progress(self, **params):
        context = self.client.get(reverse("price_list_distribution"), {"month": "2026-09", **params}).context
        return (context["completed_count"], context["total_count"], context["pending_count"], context["progress_percent"])

    def test_progress_follows_owner_filter(self):
        self.assertEqual(self.progress(), (1, 3, 2, 33), "預設「我的車行」只算自己負責的")
        self.assertEqual(self.progress(owner="me"), (1, 3, 2, 33))
        self.assertEqual(self.progress(owner="unassigned"), (0, 1, 1, 0))
        self.assertEqual(self.progress(owner=str(self.colleague.pk)), (2, 2, 0, 100))
        self.assertEqual(self.progress(owner="all"), (3, 6, 3, 50))

    def test_search_status_and_region_filters_do_not_change_progress(self):
        for params in ({"status": "completed"}, {"status": "pending"}, {"q": "我的一"},
                       {"city": "臺北市"}, {"city": "新北市", "district": "汐止區"}):
            with self.subTest(params=params):
                self.assertEqual(self.progress(owner="me", **params), (1, 3, 2, 33))

    def test_rendered_progress_shows_owner_scope(self):
        response = self.client.get(reverse("price_list_distribution"), {"month": "2026-09", "owner": "me"})
        self.assertContains(response, '<strong data-progress-count>1／3 家</strong>', html=False)
        self.assertContains(response, '<span data-progress-label>尚有 2 家未完成</span>', html=False)
        self.assertContains(response, f'<input type="hidden" name="owner" value="me">', html=False)

    def test_completion_response_keeps_owner_scope(self):
        url = reverse("price_list_distribution_item_update", args=[self.mine_pending.pk])
        payload = self.client.post(url, {"completed": "1", "owner": "me"}, HTTP_X_REQUESTED_WITH="XMLHttpRequest").json()
        self.assertEqual((payload["completed_count"], payload["total_count"], payload["pending_count"], payload["progress_percent"]),
                         (2, 3, 1, 67))
        payload = self.client.post(url, {"completed": "0", "owner": "all"}, HTTP_X_REQUESTED_WITH="XMLHttpRequest").json()
        self.assertEqual((payload["completed_count"], payload["total_count"]), (3, 6))
        payload = self.client.post(url, {"completed": "1"}, HTTP_X_REQUESTED_WITH="XMLHttpRequest").json()
        self.assertEqual((payload["completed_count"], payload["total_count"]), (4, 6), "沒帶負責人（舊頁面）維持全部")
