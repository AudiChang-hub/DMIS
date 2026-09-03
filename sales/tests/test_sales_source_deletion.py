from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from sales.models import (
    DealerVolumeBonusRule,
    PriceListDistributionItem,
    PriceListDistributionMonth,
    SalesSource,
    SalesSourceBrandPolicy,
    SalesSourceCategory,
)


class SalesSourceDeletionTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            "dealer-maintainer",
            password="pass12345",
        )
        self.client.force_login(self.user)
        self.category = SalesSourceCategory.objects.create(
            name="測試合作車行",
            system_behavior=SalesSource.SourceType.DEALER,
        )
        self.dealer = SalesSource.objects.create(
            name="誤建測試車行",
            source_type=SalesSource.SourceType.DEALER,
            category=self.category,
            code="N26090399",
            address="基隆市七堵區明德一路1號",
        )

    def test_edit_page_links_to_safe_delete_preflight(self):
        response = self.client.get(reverse("sales_source_edit", args=[self.dealer.pk]))

        self.assertContains(response, "車行資料管理")
        self.assertContains(
            response,
            reverse("sales_source_delete", args=[self.dealer.pk]),
        )

    def test_delete_requires_exact_dealer_name(self):
        response = self.client.post(
            reverse("sales_source_delete", args=[self.dealer.pk]),
            {"confirm_name": "錯誤名稱"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "車行名稱不一致")
        self.assertTrue(SalesSource.objects.filter(pk=self.dealer.pk).exists())

    def test_unused_dealer_can_be_deleted_and_distribution_snapshot_is_kept(self):
        SalesSourceBrandPolicy.objects.create(
            source=self.dealer,
            cooperation_scope=SalesSourceBrandPolicy.CooperationScope.SYM,
            effective_from=date(2026, 9, 1),
        )
        distribution = PriceListDistributionMonth.objects.create(
            month=date(2026, 9, 1),
        )
        item = PriceListDistributionItem.objects.create(
            distribution=distribution,
            dealer=self.dealer,
            dealer_code=self.dealer.code,
            dealer_name=self.dealer.name,
            city=self.dealer.city,
            district=self.dealer.district,
            address=self.dealer.address,
        )

        response = self.client.post(
            reverse("sales_source_delete", args=[self.dealer.pk]),
            {"confirm_name": self.dealer.name},
        )

        self.assertRedirects(response, reverse("sales_source_list"))
        self.assertFalse(SalesSource.objects.filter(pk=self.dealer.pk).exists())
        item.refresh_from_db()
        self.assertIsNone(item.dealer)
        self.assertEqual(item.dealer_name, "誤建測試車行")
        self.assertEqual(item.address, "基隆市七堵區明德一路1號")

    def test_dealer_with_business_reference_is_blocked_with_count(self):
        DealerVolumeBonusRule.objects.create(
            dealer=self.dealer,
            brand="SYM",
            starts_on=date(2026, 9, 1),
            ends_on=date(2026, 9, 30),
        )

        response = self.client.get(
            reverse("sales_source_delete", args=[self.dealer.pk])
        )

        self.assertContains(response, "目前不能永久刪除")
        self.assertContains(response, "台數獎金規則")
        self.assertContains(response, "1 筆")
        self.assertNotContains(response, "永久刪除車行</button>")

        post_response = self.client.post(
            reverse("sales_source_delete", args=[self.dealer.pk]),
            {"confirm_name": self.dealer.name},
        )
        self.assertEqual(post_response.status_code, 200)
        self.assertTrue(SalesSource.objects.filter(pk=self.dealer.pk).exists())

    def test_non_dealer_cannot_use_dealer_delete_route(self):
        platform = SalesSource.objects.create(
            name="測試平台",
            source_type=SalesSource.SourceType.PLATFORM,
            code="PLATFORM-DELETE-TEST",
        )

        response = self.client.get(reverse("sales_source_delete", args=[platform.pk]))

        self.assertEqual(response.status_code, 404)

    def test_dealer_list_provides_google_maps_navigation_only_with_address(self):
        no_address = SalesSource.objects.create(
            name="未填地址車行",
            source_type=SalesSource.SourceType.DEALER,
            category=self.category,
        )

        response = self.client.get(reverse("sales_source_list"), {"q": "誤建測試"})

        self.assertContains(response, "Google Maps")
        self.assertContains(response, "導航")
        self.assertContains(response, 'target="_blank"')
        listed_dealer = next(
            source for source in response.context["sources"] if source.pk == self.dealer.pk
        )
        self.assertIn("google.com/maps/dir/", listed_dealer.google_maps_url)
        self.assertIn("%E8%AA%A4%E5%BB%BA%E6%B8%AC%E8%A9%A6%E8%BB%8A%E8%A1%8C", listed_dealer.google_maps_url)

        no_address_response = self.client.get(
            reverse("sales_source_list"),
            {"q": no_address.name},
        )
        self.assertNotContains(no_address_response, "Google Maps")
