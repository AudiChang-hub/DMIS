"""T-238a（使用者 2026-11-18 選 A 分兩版刪）：來源代碼全面取消。畫面不再顯示、不能用代碼搜尋，價格表快照不寫入代碼。
欄位本身下一版（T-238b）才用 migration 刪除。"""
from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from sales.models import SalesSource, SalesSourceBrandPolicy, SalesSourceCooperationProfile
from sales.services.price_list_distribution import ensure_distribution_month

OLD_CODE = "S26111801"


class SourceCodeRemovedTests(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_superuser("admin", password="Local-t238-901!"))
        self.dealer = SalesSource.objects.create(source_type=SalesSource.SourceType.DEALER, name="舊招牌車行",
                                                 address="新北市汐止區測試路1號", holiday_gift=True)
        SalesSource.objects.filter(pk=self.dealer.pk).update(code=OLD_CODE)  # 正式站既有的舊代碼保留在資料庫
        SalesSourceCooperationProfile.objects.create(source=self.dealer, cooperates=True,
                                                     cooperation_scope=SalesSourceBrandPolicy.CooperationScope.SYM)
        self.platform = SalesSource.objects.create(source_type=SalesSource.SourceType.PLATFORM, name="舊招牌平台")
        SalesSource.objects.filter(pk=self.platform.pk).update(code="N26111801")

    def test_price_list_snapshot_has_no_code_and_pages_do_not_show_it(self):
        distribution, _ = ensure_distribution_month(date(2026, 9, 1))
        item = distribution.items.get(dealer=self.dealer)
        self.assertEqual(item.dealer_code, "")
        page = self.client.get(reverse("price_list_distribution"), {"month": "2026-09", "owner": "all"})
        self.assertContains(page, "舊招牌車行")
        self.assertNotContains(page, OLD_CODE)
        assignments = self.client.get(reverse("price_list_distribution_assignments", args=[distribution.pk]))
        self.assertNotContains(assignments, OLD_CODE)
        for response in (page, assignments):
            self.assertNotContains(response, "代碼", msg_prefix="搜尋提示也不再提代碼")

    def test_price_list_search_no_longer_matches_code(self):
        distribution, _ = ensure_distribution_month(date(2026, 9, 1))
        distribution.items.update(dealer_code=OLD_CODE)  # 舊快照仍有代碼
        by_code = self.client.get(reverse("price_list_distribution"), {"month": "2026-09", "owner": "all", "q": OLD_CODE})
        self.assertEqual(list(by_code.context["items"]), [])
        by_name = self.client.get(reverse("price_list_distribution"), {"month": "2026-09", "owner": "all", "q": "舊招牌"})
        self.assertEqual(len(by_name.context["items"]), 1)

    def test_source_pages_do_not_show_or_search_code(self):
        for url in (reverse("sales_source_list"), reverse("sales_source_edit", args=[self.dealer.pk]),
                    reverse("sales_source_delete", args=[self.dealer.pk]), reverse("sales_source_holiday_gift_manage"),
                    reverse("sales_source_platform_list"), reverse("sales_source_edit", args=[self.platform.pk])):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertNotContains(response, OLD_CODE)
                self.assertNotContains(response, "N26111801")
                self.assertNotContains(response, "代碼")
        found = self.client.get(reverse("sales_source_list"), {"q": OLD_CODE})
        self.assertNotContains(found, "舊招牌車行")
        platforms = self.client.get(reverse("sales_source_platform_list"), {"q": "N26111801"})
        self.assertNotContains(platforms, "舊招牌平台")
