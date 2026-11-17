"""T-210：已有頁籤的頁改用共用狀態頁籤（_status_tabs.html），結算成本總表窄寬度每格整列。"""
import re
from datetime import date
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from sales.models import DealerRewardCatalogItem, IncentiveCampaign, SalesSource
from sales.tests.test_status_tabs_t209 import nav_html, tab_counts, tab_hrefs

APP_CSS = Path(settings.BASE_DIR) / "static" / "css" / "app.css"


class SharedStatusTabsOnExistingPagesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.root = get_user_model().objects.create_superuser("t210-root", password="Test-Only-123")
        Type = SalesSource.SourceType
        for source_type, prefix in ((Type.DEALER, "T210車行"), (Type.STORE, "T210人員"), (Type.PLATFORM, "T210平台")):
            SalesSource.objects.create(name=f"{prefix}甲", source_type=source_type, active=True)
            SalesSource.objects.create(name=f"{prefix}乙", source_type=source_type, active=False)
        for active, mark in ((True, "甲"), (False, "乙")):
            DealerRewardCatalogItem.objects.create(name=f"T210品項{mark}", reward_type="physical", unit="罐", active=active)
            IncentiveCampaign.objects.create(name=f"T210活動{mark}", effective_from=date(2026, 1, 1), active=active)

    def setUp(self):
        self.client.force_login(self.root)

    def counts(self, model, **scope):
        queryset = model.objects.filter(**scope)
        return {"active": queryset.filter(active=True).count(), "inactive": queryset.filter(active=False).count()}

    def cases(self):
        Type = SalesSource.SourceType
        return [
            ("車行", reverse("sales_source_list"), "status", "T210車行", self.counts(SalesSource, source_type=Type.DEALER), False),
            ("本店人員", reverse("sales_source_staff_list"), "status", "T210人員", self.counts(SalesSource, source_type=Type.STORE), True),
            ("網路平台", reverse("sales_source_platform_list"), "status", "T210平台", self.counts(SalesSource, source_type=Type.PLATFORM), True),
            ("車行獎勵品項", reverse("dealer_reward_catalog_list"), "status", "T210品項", self.counts(DealerRewardCatalogItem), True),
            ("原廠獎勵", reverse("incentive_rule_list"), "tab", "T210活動", self.counts(IncentiveCampaign), True),
        ]

    def test_pages_use_the_shared_partial_with_live_counts(self):
        for name, url, param, prefix, expected, has_scope in self.cases():
            with self.subTest(page=name):
                html = self.client.get(url).content.decode()
                nav = nav_html(html)
                self.assertIn("<span>目前使用</span>", nav)
                self.assertEqual(tab_counts(html), expected)  # data-status-count 讓 Switch 後的筆數即時更新
                self.assertRegex(nav, r'class="is-active" aria-current="page">')
                self.assertEqual('data-status-tab="active"' in html, has_scope)
                self.assertIn(f"{prefix}甲", html)
                self.assertNotIn(f"{prefix}乙", html)

    def test_inactive_tab_and_old_parameters_still_work(self):
        for name, url, param, prefix, expected, has_scope in self.cases():
            with self.subTest(page=name):
                response = self.client.get(url, {param: "inactive"})
                self.assertEqual(response.status_code, 200)
                html = response.content.decode()
                self.assertIn('class="is-active is-inactive" aria-current="page"', nav_html(html))
                self.assertIn(f"{prefix}乙", html)
                self.assertNotIn(f"{prefix}甲", html)
        legacy = self.client.get(reverse("incentive_rule_list"), {"status": "inactive"}).content.decode()
        self.assertIn("T210活動乙", legacy)
        self.assertIn('class="is-active is-inactive" aria-current="page"', nav_html(legacy))

    def test_tab_links_keep_filters(self):
        html = self.client.get(reverse("dealer_reward_catalog_list"), {"q": "T210", "reward_type": "physical", "page": "1"}).content.decode()
        for href in tab_hrefs(html):
            self.assertIn("q=T210", href)
            self.assertIn("reward_type=physical", href)
            self.assertNotIn("page=", href)
        html = self.client.get(reverse("sales_source_staff_list"), {"q": "T210"}).content.decode()
        self.assertTrue(all("q=T210" in href for href in tab_hrefs(html)))

    def test_channel_toggle_counts_follow_the_record_type(self):
        staff = SalesSource.objects.get(name="T210人員甲")
        response = self.client.post(reverse("master_record_set_active", args=["sales-source", staff.pk]), {"active": "0"},
                                    HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        expected = self.counts(SalesSource, source_type=SalesSource.SourceType.STORE)
        self.assertEqual(response.json()["status_counts"], expected)
        # 車行照舊只算車行（另有人員、平台資料也不混入），結果和改版前一樣。
        dealer = SalesSource.objects.get(name="T210車行甲")
        response = self.client.post(reverse("master_record_set_active", args=["sales-source", dealer.pk]), {"active": "0"},
                                    HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(response.json()["status_counts"], {"active": 0, "inactive": 2})
        self.assertEqual(response.json()["status_counts"],
                         self.counts(SalesSource, source_type=SalesSource.SourceType.DEALER))

    def test_dealer_list_keeps_row_removal_and_updates_shared_counts(self):
        html = self.client.get(reverse("sales_source_list")).content.decode()
        self.assertIn("removeMovedSourceRow(form, payload.status_counts);", html)
        self.assertIn('document.querySelector(`[data-status-count="${status}"]`)', html)
        self.assertNotIn("data-source-status-count", html)


class SettlementCostNarrowRowsTests(TestCase):
    def test_narrow_layout_gives_each_cell_a_full_row(self):
        css = APP_CSS.read_text(encoding="utf-8")
        rules = (".settlement-cost-table tr > td { grid-column: 1 / -1; }",
                 ".settlement-cost-table td:not(.inventory-row-action) > * { grid-column: 2; }")
        for rule in rules:
            position = css.index(rule)
            media = css[:position].rindex("@media")
            self.assertTrue(css[media:].startswith("@media (max-width: 600px)"), "只在窄寬度生效")
            self.assertNotIn("\n}\n", css[media:position], "規則仍在同一個 @media 區塊內")
        self.assertEqual(css.count(".settlement-cost-table"), 2)  # 寬版（1440）沒有其他規則
        self.assertIsNotNone(re.search(r'class="inventory-table settlement-cost-table"',
                                       (Path(settings.BASE_DIR) / "templates/sales/settlement_cost_rule_list.html").read_text(encoding="utf-8")))
