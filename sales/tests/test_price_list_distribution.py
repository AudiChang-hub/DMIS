from datetime import date

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from sales.models import (
    PriceListDistributionMonth,
    SalesSource,
    SalesSourceCooperationProfile,
    SalesSourceBrandPolicy,
)
from sales.services.price_list_distribution import ensure_distribution_month


class PriceListDistributionTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="distribution-user",
            password="test-password",
        )
        self.client.force_login(self.user)

    def create_dealer(self, name, *, sym=False, suzuki=False, exclusive=False, active=True):
        dealer = SalesSource.objects.create(
            source_type=SalesSource.SourceType.DEALER,
            name=name,
            code=f"CODE-{name}",
            city="新北市",
            district="汐止區",
            active=active,
        )
        if sym:
            SalesSourceCooperationProfile.objects.create(
                source=dealer,
                cooperation_scope=SalesSourceBrandPolicy.CooperationScope.SYM,
                cooperates=True,
                relationship_type=(
                    SalesSourceCooperationProfile.RelationshipType.EXCLUSIVE
                    if exclusive
                    else SalesSourceCooperationProfile.RelationshipType.GENERAL
                ),
            )
        if suzuki:
            SalesSourceCooperationProfile.objects.create(
                source=dealer,
                cooperation_scope=SalesSourceBrandPolicy.CooperationScope.SUZUKI_GAS,
                cooperates=True,
            )
            SalesSourceCooperationProfile.objects.create(
                source=dealer,
                cooperation_scope=SalesSourceBrandPolicy.CooperationScope.SUZUKI_ELECTRIC,
                cooperates=True,
            )
        return dealer

    def test_month_snapshot_combines_suzuki_and_marks_sym_exclusive(self):
        dealer = self.create_dealer("專銷雙品牌", sym=True, suzuki=True, exclusive=True)
        self.create_dealer("停用車行", sym=True, active=False)

        distribution, created = ensure_distribution_month(date(2026, 9, 1))

        self.assertTrue(created)
        self.assertEqual(distribution.items.count(), 1)
        item = distribution.items.get(dealer=dealer)
        self.assertTrue(item.requires_sym)
        self.assertTrue(item.requires_suzuki)
        self.assertTrue(item.sym_exclusive)

        dealer.name = "後來改名"
        dealer.save(update_fields=["name", "updated_at"])
        item.refresh_from_db()
        self.assertEqual(item.dealer_name, "專銷雙品牌")

    def test_page_auto_creates_month_and_ajax_updates_completion_and_note(self):
        self.create_dealer("九月車行", sym=True)
        response = self.client.get(reverse("price_list_distribution"), {"month": "2026-09"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "2026 年 9 月價格表分發")
        item = PriceListDistributionMonth.objects.get(month=date(2026, 9, 1)).items.get()

        completed = self.client.post(
            reverse("price_list_distribution_item_update", args=[item.pk]),
            {"completed": "1"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(completed.status_code, 200)
        self.assertTrue(completed.json()["completed"])

        noted = self.client.post(
            reverse("price_list_distribution_item_update", args=[item.pk]),
            {"note": "已確認價格表"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(noted.status_code, 200)
        item.refresh_from_db()
        self.assertTrue(item.completed)
        self.assertEqual(item.note, "已確認價格表")
        self.assertEqual(item.completed_by, self.user.username)

    def test_daily_command_builds_current_and_next_month_on_last_day(self):
        self.create_dealer("月底車行", suzuki=True)
        from unittest.mock import patch

        with patch("sales.management.commands.generate_price_list_distribution.timezone.localdate", return_value=date(2026, 9, 30)):
            call_command("generate_price_list_distribution")

        self.assertTrue(PriceListDistributionMonth.objects.filter(month=date(2026, 9, 1)).exists())
        self.assertTrue(PriceListDistributionMonth.objects.filter(month=date(2026, 10, 1)).exists())
