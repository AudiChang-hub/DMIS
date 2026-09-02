from datetime import date
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

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
            first_name="分發人員",
            password="test-password",
        )
        self.colleague = get_user_model().objects.create_user(
            username="distribution-colleague",
            first_name="協作同事",
            password="test-password",
        )
        self.client.force_login(self.user)

    def create_dealer(
        self,
        name,
        *,
        sym=False,
        suzuki=False,
        suzuki_electric_only=False,
        exclusive=False,
        active=True,
        city="新北市",
        district="汐止區",
        phone="",
        phone_secondary="",
        mobile="",
    ):
        dealer = SalesSource.objects.create(
            source_type=SalesSource.SourceType.DEALER,
            name=name,
            code=f"CODE-{name}",
            city=city,
            district=district,
            address=f"{city}{district}測試路1號",
            phone=phone,
            phone_secondary=phone_secondary,
            mobile=mobile,
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
        if suzuki or suzuki_electric_only:
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

    def test_month_snapshot_excludes_suzuki_electric_only_dealers(self):
        electric_only = self.create_dealer(
            "只有台鈴電車",
            suzuki_electric_only=True,
        )
        sym_and_electric = self.create_dealer(
            "三陽加台鈴電車",
            sym=True,
            suzuki_electric_only=True,
        )

        distribution, _ = ensure_distribution_month(date(2026, 9, 1))

        self.assertFalse(distribution.items.filter(dealer=electric_only).exists())
        included = distribution.items.get(dealer=sym_and_electric)
        self.assertTrue(included.requires_sym)
        self.assertTrue(included.requires_suzuki)

    def test_phone_snapshot_adds_area_code_and_renders_click_to_call_link(self):
        dealer = self.create_dealer(
            "可撥號車行",
            sym=True,
            city="基隆市",
            district="七堵區",
            phone="24562660",
        )

        distribution, _ = ensure_distribution_month(date(2026, 9, 1))
        item = distribution.items.get(dealer=dealer)
        response = self.client.get(
            reverse("price_list_distribution"),
            {"month": "2026-09"},
        )

        self.assertEqual(item.contact_phone, "02-24562660")
        self.assertContains(response, 'href="tel:02-24562660"')
        self.assertContains(response, "02-24562660")
        self.assertContains(response, 'class="master-filters price-distribution-filters"')
        self.assertContains(response, 'class="inventory-filter master-search"')
        self.assertContains(response, "清除條件")
        self.assertContains(response, "套用篩選")

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
        with patch("sales.management.commands.generate_price_list_distribution.timezone.localdate", return_value=date(2026, 9, 30)):
            call_command("generate_price_list_distribution")

        self.assertTrue(PriceListDistributionMonth.objects.filter(month=date(2026, 9, 1)).exists())
        self.assertTrue(PriceListDistributionMonth.objects.filter(month=date(2026, 10, 1)).exists())

    def test_keelung_dealers_and_filter_follow_requested_district_order(self):
        requested_order = (
            "七堵區",
            "暖暖區",
            "仁愛區",
            "信義區",
            "中正區",
            "中山區",
            "安樂區",
        )
        for district in reversed(requested_order):
            self.create_dealer(
                f"{district}車行",
                sym=True,
                city="基隆市",
                district=district,
            )

        response = self.client.get(
            reverse("price_list_distribution"),
            {"month": "2026-09", "city": "基隆市"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["districts"], list(requested_order))
        dealer_names = [item.dealer_name for item in response.context["items"]]
        self.assertEqual(
            dealer_names,
            [f"{district}車行" for district in requested_order],
        )

    def test_new_month_copies_active_previous_assignee_and_visit_order(self):
        dealer = self.create_dealer("沿用分工車行", sym=True)
        september, _ = ensure_distribution_month(date(2026, 9, 1))
        september_item = september.items.get(dealer=dealer)
        september_item.assigned_to = self.user
        september_item.assigned_to_name = "分發人員"
        september_item.visit_order = 7
        september_item.save()

        october, created = ensure_distribution_month(date(2026, 10, 1))
        october_item = october.items.get(dealer=dealer)

        self.assertTrue(created)
        self.assertEqual(october_item.assigned_to, self.user)
        self.assertEqual(october_item.assigned_to_name, "分發人員")
        self.assertEqual(october_item.visit_order, 7)

    def test_new_month_does_not_copy_inactive_assignee(self):
        dealer = self.create_dealer("重新分配車行", sym=True)
        september, _ = ensure_distribution_month(date(2026, 9, 1))
        item = september.items.get(dealer=dealer)
        item.assigned_to = self.colleague
        item.assigned_to_name = "協作同事"
        item.visit_order = 2
        item.save()
        self.colleague.is_active = False
        self.colleague.save(update_fields=["is_active"])

        october, _ = ensure_distribution_month(date(2026, 10, 1))
        october_item = october.items.get(dealer=dealer)

        self.assertIsNone(october_item.assigned_to)
        self.assertEqual(october_item.assigned_to_name, "")
        self.assertEqual(october_item.visit_order, 0)

    def test_main_page_filters_by_owner_and_uses_personal_visit_order(self):
        first = self.create_dealer("第二站", sym=True, district="板橋區")
        second = self.create_dealer("第一站", sym=True, district="汐止區")
        other = self.create_dealer("同事車行", sym=True, district="新店區")
        distribution, _ = ensure_distribution_month(date(2026, 9, 1))
        distribution.items.filter(dealer=first).update(
            assigned_to=self.user, assigned_to_name="分發人員", visit_order=2
        )
        distribution.items.filter(dealer=second).update(
            assigned_to=self.user, assigned_to_name="分發人員", visit_order=1
        )
        distribution.items.filter(dealer=other).update(
            assigned_to=self.colleague, assigned_to_name="協作同事", visit_order=1
        )

        response = self.client.get(reverse("price_list_distribution"), {"month": "2026-09"})

        self.assertEqual(response.context["selected_owner"], "me")
        self.assertEqual(
            [item.dealer_name for item in response.context["items"]],
            ["第一站", "第二站"],
        )
        self.assertContains(response, "我的車行")
        self.assertContains(response, "協作同事")
        self.assertContains(response, 'id="distribution-owner"')
        self.assertNotContains(response, "price-assignment-overview")
        self.assertContains(response, "第 1 站")
        self.assertNotContains(response, "同事車行")

    @patch("sales.views.timezone.localdate", return_value=date(2026, 9, 2))
    def test_selected_assignment_appends_order_and_leaves_unchecked_dealer_unassigned(self, _mock_localdate):
        first = self.create_dealer("汐止甲", sym=True, district="汐止區")
        second = self.create_dealer("汐止乙", sym=True, district="汐止區")
        unchecked = self.create_dealer("例外車行", sym=True, district="汐止區")
        distribution, _ = ensure_distribution_month(date(2026, 9, 1))
        selected_ids = [
            distribution.items.get(dealer=first).pk,
            distribution.items.get(dealer=second).pk,
        ]

        response = self.client.post(
            reverse("price_list_distribution_assignments", args=[distribution.pk]),
            {
                "action": "assign_selected",
                "selected_item_id": [str(item_id) for item_id in selected_ids],
                "selected_assignee": str(self.user.pk),
            },
        )

        self.assertEqual(response.status_code, 302)
        assigned = list(
            distribution.items.filter(pk__in=selected_ids).order_by("visit_order")
        )
        self.assertEqual([item.assigned_to for item in assigned], [self.user, self.user])
        self.assertEqual([item.visit_order for item in assigned], [1, 2])
        self.assertIsNone(distribution.items.get(dealer=unchecked).assigned_to)

    @patch("sales.views.timezone.localdate", return_value=date(2026, 9, 2))
    def test_assignment_page_explains_region_workflow_and_mobile_controls(self, _mock_localdate):
        self.create_dealer("分工畫面車行", sym=True)
        distribution, _ = ensure_distribution_month(date(2026, 9, 1))

        response = self.client.get(
            reverse("price_list_distribution_assignments", args=[distribution.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "先縮小範圍，再勾選例外")
        self.assertContains(response, "分工與拜訪順序")
        self.assertContains(response, "確認本月分工")
        self.assertContains(response, "data-select-all")
        self.assertContains(response, "data-drag-handle")
        self.assertNotContains(response, 'type="number"')
        self.assertContains(response, "price-list-distribution-assignments.js")
        self.assertContains(response, f'{reverse("user_guide")}#price-list-distribution')

    @patch("sales.views.timezone.localdate", return_value=date(2026, 9, 2))
    def test_row_adjustment_normalizes_each_assignee_order_and_clears_confirmation(self, _mock_localdate):
        dealers = [self.create_dealer(f"排序車行{index}", sym=True) for index in range(1, 4)]
        distribution, _ = ensure_distribution_month(date(2026, 9, 1))
        items = list(distribution.items.order_by("pk"))
        distribution.assignment_confirmed_at = timezone.now()
        distribution.assignment_confirmed_by = "先前確認人"
        distribution.save()

        response = self.client.post(
            reverse("price_list_distribution_assignments", args=[distribution.pk]),
            {
                "action": "save_rows",
                "item_id": [str(item.pk) for item in items],
                f"assignee_{items[0].pk}": str(self.user.pk),
                f"order_{items[0].pk}": "20",
                f"assignee_{items[1].pk}": str(self.user.pk),
                f"order_{items[1].pk}": "10",
                f"assignee_{items[2].pk}": str(self.colleague.pk),
                f"order_{items[2].pk}": "8",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            list(
                distribution.items.filter(assigned_to=self.user)
                .order_by("visit_order")
                .values_list("dealer_name", "visit_order")
            ),
            [(dealers[1].name, 1), (dealers[0].name, 2)],
        )
        self.assertEqual(
            distribution.items.get(assigned_to=self.colleague).visit_order,
            1,
        )
        distribution.refresh_from_db()
        self.assertIsNone(distribution.assignment_confirmed_at)
        self.assertEqual(distribution.assignment_confirmed_by, "")

    @patch("sales.views.timezone.localdate", return_value=date(2026, 9, 2))
    def test_confirmation_requires_every_dealer_to_have_an_assignee(self, _mock_localdate):
        self.create_dealer("待分配車行", sym=True)
        distribution, _ = ensure_distribution_month(date(2026, 9, 1))
        url = reverse("price_list_distribution_assignments", args=[distribution.pk])

        blocked = self.client.post(url, {"action": "confirm"}, follow=True)
        self.assertContains(blocked, "尚有 1 家車行未分配")
        distribution.refresh_from_db()
        self.assertIsNone(distribution.assignment_confirmed_at)

        item = distribution.items.get()
        item.assigned_to = self.user
        item.assigned_to_name = "分發人員"
        item.visit_order = 1
        item.save()
        confirmed = self.client.post(url, {"action": "confirm"}, follow=True)

        self.assertContains(confirmed, "本月分工已確認")
        distribution.refresh_from_db()
        self.assertIsNotNone(distribution.assignment_confirmed_at)
        self.assertEqual(distribution.assignment_confirmed_by, "分發人員")

    def test_historical_month_assignment_page_is_read_only(self):
        self.create_dealer("歷史車行", sym=True)
        distribution, _ = ensure_distribution_month(date(2026, 8, 1))
        item = distribution.items.get()
        url = reverse("price_list_distribution_assignments", args=[distribution.pk])

        with patch("sales.views.timezone.localdate", return_value=date(2026, 9, 2)):
            page = self.client.get(url)
            response = self.client.post(
                url,
                {
                    "action": "save_rows",
                    "item_id": [str(item.pk)],
                    f"assignee_{item.pk}": str(self.user.pk),
                    f"order_{item.pk}": "1",
                },
                follow=True,
            )

        self.assertFalse(page.context["editable"])
        self.assertContains(response, "歷史月份已保存")
        item.refresh_from_db()
        self.assertIsNone(item.assigned_to)

    def test_sync_preserves_assignment_order_completion_and_note(self):
        dealer = self.create_dealer("同步保留車行", sym=True)
        distribution, _ = ensure_distribution_month(date(2026, 9, 1))
        item = distribution.items.get(dealer=dealer)
        item.assigned_to = self.user
        item.assigned_to_name = "分發人員"
        item.visit_order = 3
        item.completed = True
        item.note = "保留這段備註"
        item.save()

        ensure_distribution_month(date(2026, 9, 1), sync=True)
        item.refresh_from_db()

        self.assertEqual(item.assigned_to, self.user)
        self.assertEqual(item.visit_order, 3)
        self.assertTrue(item.completed)
        self.assertEqual(item.note, "保留這段備註")
