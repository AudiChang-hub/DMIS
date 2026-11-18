"""T-238（使用者 2026-11-18 同意刪除）：來源代碼取消。2.27.0 起程式不讀寫；0219 起欄位從 model 移除，
下一版 0220 刪資料庫欄位。畫面不顯示代碼字樣、價格表快照沒有代碼。"""
from datetime import date

from django.contrib.auth import get_user_model
from django.core.exceptions import FieldDoesNotExist
from django.test import TestCase
from django.urls import reverse

from sales.models import PriceListDistributionItem, SalesSource, SalesSourceBrandPolicy, SalesSourceCooperationProfile
from sales.services.price_list_distribution import ensure_distribution_month


class SourceCodeRemovedTests(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_superuser("admin", password="Local-t238-901!"))
        self.dealer = SalesSource.objects.create(source_type=SalesSource.SourceType.DEALER, name="舊招牌車行",
                                                 address="新北市汐止區測試路1號", holiday_gift=True)
        SalesSourceCooperationProfile.objects.create(source=self.dealer, cooperates=True,
                                                     cooperation_scope=SalesSourceBrandPolicy.CooperationScope.SYM)
        self.platform = SalesSource.objects.create(source_type=SalesSource.SourceType.PLATFORM, name="舊招牌平台")

    def test_code_fields_are_gone_from_models(self):
        for model, name in ((SalesSource, "code"), (PriceListDistributionItem, "dealer_code")):
            with self.subTest(field=name), self.assertRaises(FieldDoesNotExist):
                model._meta.get_field(name)
        self.assertFalse(hasattr(SalesSource, "next_general_source_code"))

    def test_new_sources_and_snapshots_save_without_code(self):
        for source_type in SalesSource.SourceType.values:
            with self.subTest(source_type=source_type):
                SalesSource.objects.create(name=f"新來源-{source_type}", source_type=source_type)
        distribution, _ = ensure_distribution_month(date(2026, 9, 1))
        self.assertTrue(distribution.items.filter(dealer=self.dealer).exists())

    def test_pages_do_not_mention_code(self):
        distribution, _ = ensure_distribution_month(date(2026, 9, 1))
        for url in (reverse("price_list_distribution") + "?month=2026-09&owner=all",
                    reverse("price_list_distribution_assignments", args=[distribution.pk]),
                    reverse("sales_source_list"), reverse("sales_source_edit", args=[self.dealer.pk]),
                    reverse("sales_source_delete", args=[self.dealer.pk]), reverse("sales_source_holiday_gift_manage"),
                    reverse("sales_source_platform_list"), reverse("sales_source_edit", args=[self.platform.pk])):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertNotContains(response, "代碼")

    def test_search_by_name_still_works(self):
        ensure_distribution_month(date(2026, 9, 1))
        by_name = self.client.get(reverse("price_list_distribution"), {"month": "2026-09", "owner": "all", "q": "舊招牌"})
        self.assertEqual(len(by_name.context["items"]), 1)
