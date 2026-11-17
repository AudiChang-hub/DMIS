"""T-209：有啟用／停用 Switch 的清單都要有「啟用中／已停用」狀態頁籤（比照機種與售價）。

每頁驗：預設停在啟用中、頁籤筆數、依狀態篩選、頁籤網址保留其他條件、清單外層帶 data-status-tab
（停用後前端提示「重新整理後移到已停用」並更新筆數）。
"""
import re
from datetime import date
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.urls import reverse

from sales.models import VehicleModel
from sales.status_tabs import status_tabs

TEMPLATES = Path(settings.BASE_DIR) / "templates" / "sales"
SCRIPT = Path(settings.BASE_DIR) / "static" / "js" / "active-quick-toggle.js"


def nav_html(html):
    match = re.search(r'<nav class="source-status-switch".*?</nav>', html, re.S)
    return match.group(0) if match else ""


def tab_counts(html):
    nav = nav_html(html)
    return {
        key: int(value)
        for key, value in re.findall(r'data-status-count="(active|inactive)">(\d+)</b>', nav)
    }


def tab_hrefs(html):
    nav = nav_html(html)
    return [href.replace("&amp;", "&") for href in re.findall(r'<a href="([^"]*)"', nav)]


class StatusTabsHelperTests(TestCase):
    def test_tab_urls_keep_filters_and_drop_one_time_params(self):
        request = RequestFactory().get("/x/", {"q": "abc", "page": "3", "edit": "9", "status": "inactive"})
        tabs = status_tabs(request, "inactive", {"active": 2, "inactive": 1})
        self.assertEqual(tabs["urls"]["active"], "/x/?q=abc&status=active")
        self.assertEqual(tabs["urls"]["inactive"], "/x/?q=abc&status=inactive")
        self.assertEqual(tabs["status"], "inactive")

    def test_toggle_script_moves_counts_when_server_sends_none(self):
        script = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("adjustStatusCounts", script)
        self.assertIn("[data-status-count=", script)


class VehicleModelStatusTabsLockTests(TestCase):
    """機種與售價是基準頁：改用共用 partial 後，頁籤外觀與行為不變。"""

    @classmethod
    def setUpTestData(cls):
        cls.root = get_user_model().objects.create_superuser("t209-admin", password="Test-Only-123")
        for index, active in enumerate((True, True, False)):
            VehicleModel.objects.create(
                brand="SUZUKI", name=f"頁籤測試車{index}", model_number=f"TB{index}", model_year=2026,
                model_code=VehicleModel.ModelType.FRONT_DISC_REAR_DRUM,
                energy_type=VehicleModel.EnergyType.GAS, displacement_cc=124, active=active,
            )

    def setUp(self):
        self.client.force_login(self.root)

    def test_nav_markup_is_unchanged(self):
        html = self.client.get(reverse("vehicle_model_list"), {"q": "頁籤", "page": "2"}).content.decode()
        expected = (
            '<nav class="source-status-switch" aria-label="依使用狀態查看機種與售價">'
            '<a href="/data/vehicle-models/?q=%E9%A0%81%E7%B1%A4&amp;status=active" class="is-active" aria-current="page">'
            "<span>目前使用</span><strong>啟用中機種</strong>"
            '<b data-status-count="active">2</b></a>'
            '<a href="/data/vehicle-models/?q=%E9%A0%81%E7%B1%A4&amp;status=inactive" class="">'
            "<span>歷史收納</span><strong>已停用機種</strong>"
            '<b data-status-count="inactive">1</b></a></nav>'
        )
        self.assertHTMLEqual(nav_html(html), expected)

    def test_inactive_tab_marks_selected_and_keeps_scope(self):
        html = self.client.get(reverse("vehicle_model_list"), {"status": "inactive"}).content.decode()
        self.assertIn('class="is-active is-inactive" aria-current="page"', nav_html(html))
        self.assertIn("頁籤測試車2", html)
        self.assertNotIn("頁籤測試車0", html)
        self.assertIn('data-status-tab="inactive" data-status-tab-labels="啟用中機種,已停用機種"', html)


class StatusTabsPerPageTests(TestCase):
    """T-209 補上頁籤的各頁：預設、筆數、篩選、保留其他條件、清單外層帶 data-status-tab。"""

    @classmethod
    def setUpTestData(cls):
        from decimal import Decimal

        from sales.models import (
            AccessoryCategory, AccessoryProduct, BrandRegistrationFeeRule, DealerRewardCampaign,
            DealerVolumeBonusRule, InstallmentCompany, InstallmentPlanVersion, PositionedPrintTemplate,
            SubsidyProgram, VehicleBrand, VehiclePriceVersion, VehicleSettlementCostRule,
        )

        cls.root = get_user_model().objects.create_superuser("t209-pages", password="Test-Only-123")

        def model(name):
            return VehicleModel.objects.create(
                brand="SUZUKI", name=name, model_number=name[-2:], model_year=2026,
                model_code=VehicleModel.ModelType.FRONT_DISC_REAR_DRUM,
                energy_type=VehicleModel.EnergyType.GAS, displacement_cc=124,
            )

        cost_on, cost_off = model("T209成本甲車"), model("T209成本乙車")
        VehicleSettlementCostRule.objects.create(vehicle_model=cost_on, amount=Decimal("60000"), effective_from=date(2026, 1, 2))
        VehicleSettlementCostRule.objects.create(vehicle_model=cost_off, amount=Decimal("61000"), effective_from=date(2025, 3, 4), active=False)
        workspace = model("T209工作區車")
        VehiclePriceVersion.objects.create(vehicle_model=workspace, cash_price=70000, suggested_price=75000, effective_from=date(2026, 1, 2))
        VehiclePriceVersion.objects.create(vehicle_model=workspace, cash_price=69000, suggested_price=74000, effective_from=date(2025, 3, 4), active=False)
        InstallmentPlanVersion.objects.create(vehicle_model=workspace, effective_from=date(2026, 1, 2))
        InstallmentPlanVersion.objects.create(vehicle_model=workspace, effective_from=date(2025, 3, 4), active=False)
        VehicleSettlementCostRule.objects.create(vehicle_model=workspace, amount=Decimal("50000"), effective_from=date(2026, 1, 2))
        VehicleSettlementCostRule.objects.create(vehicle_model=workspace, amount=Decimal("51000"), effective_from=date(2025, 3, 4), active=False)

        for active, mark in ((True, "甲"), (False, "乙")):
            AccessoryCategory.objects.create(name=f"T209類別{mark}", active=active)
            AccessoryProduct.objects.create(name=f"T209配件{mark}", active=active)
            BrandRegistrationFeeRule.objects.create(
                brand=f"T209牌{mark}", calculation_type=BrandRegistrationFeeRule.CalculationType.FIXED_BUNDLE,
                min_cc=51, max_cc=125, fixed_total=1888, insurance_period_years=1, effective_from=date(2026, 8, 1),
                active=active,
            )
            DealerRewardCampaign.objects.create(name=f"T209活動{mark}", brands=["SUZUKI"], effective_from=date(2026, 1, 1), active=active)
            InstallmentCompany.objects.create(name=f"T209分期{mark}", active=active)
            DealerVolumeBonusRule.objects.create(
                name=f"T209台數{mark}", brand="SUZUKI", starts_on=date(2026, 1, 1), ends_on=date(2026, 1, 31), active=active)
            PositionedPrintTemplate.objects.create(
                name=f"T209範本{mark}", active=active, version=209 if active else 210,
                document_type=PositionedPrintTemplate._meta.get_field("document_type").choices[0][0])
            SubsidyProgram.objects.create(name=f"T209補助{mark}", active=active)
            VehicleBrand.objects.create(name=f"T209品牌{mark}", active=active)

        def counts(queryset):
            return {"active": queryset.filter(active=True).count(), "inactive": queryset.filter(active=False).count()}

        cls.cases = [
            # (名稱, 網址, 狀態參數, 額外參數, 啟用中標記, 已停用標記, 預期筆數)
            ("配件類別", reverse("accessory_category_list"), "status", {}, "T209類別甲", "T209類別乙",
             counts(AccessoryCategory.objects)),
            ("配件與工資", reverse("accessory_product_list"), "status", {"q": "T209"}, "T209配件甲", "T209配件乙",
             counts(AccessoryProduct.objects)),
            ("領牌與強制險", reverse("brand_registration_fee_rule_list"), "status", {}, "T209牌甲", "T209牌乙",
             counts(BrandRegistrationFeeRule.objects)),
            ("車行獎勵活動", reverse("dealer_reward_campaign_list"), "tab", {"q": "T209"}, "T209活動甲", "T209活動乙",
             counts(DealerRewardCampaign.objects)),
            ("分期公司", reverse("installment_company_list"), "status", {}, "T209分期甲", "T209分期乙",
             counts(InstallmentCompany.objects)),
            ("台數獎金規則", reverse("dealer_volume_bonus_list"), "status", {"tab": "rules"}, "T209台數甲", "T209台數乙",
             counts(DealerVolumeBonusRule.objects)),
            ("列印範本", reverse("positioned_template_list"), "status", {}, "T209範本甲", "T209範本乙",
             counts(PositionedPrintTemplate.objects)),
            ("結算成本總表", reverse("settlement_cost_rule_list"), "status", {"q": "T209成本"}, "T209成本甲車", "T209成本乙車",
             counts(VehicleSettlementCostRule.objects)),
            ("補助方案", reverse("subsidy_program_list"), "status", {}, "T209補助甲", "T209補助乙",
             counts(SubsidyProgram.objects)),
            ("車輛品牌", reverse("vehicle_brand_list"), "status", {}, "T209品牌甲", "T209品牌乙",
             counts(VehicleBrand.objects)),
            ("售價版本", reverse("vehicle_model_price_versions", args=[workspace.pk]), "status", {}, "2026/01/02 起", "2025/03/04 起",
             {"active": 1, "inactive": 1}),
            ("分期方案", reverse("vehicle_installment_plan_list", args=[workspace.pk]), "status", {}, "2026/01/02", "2025/03/04",
             {"active": 1, "inactive": 1}),
            ("機種結算成本", reverse("vehicle_model_settlement_costs", args=[workspace.pk]), "status", {}, "2026/01/02 起", "2025/03/04 起",
             {"active": 1, "inactive": 1}),
        ]

    def setUp(self):
        self.client.force_login(self.root)

    @staticmethod
    def listed(html):
        """清單區（data-status-tab 之後）；避開前面編輯表單的下拉選項。"""
        return html[html.index('data-status-tab="'):]

    def test_each_page_defaults_to_active_with_counts(self):
        for name, url, param, extra, on, off, expected in self.cases:
            with self.subTest(page=name):
                response = self.client.get(url, extra)
                self.assertEqual(response.status_code, 200)
                html = response.content.decode()
                self.assertEqual(tab_counts(html), expected)
                self.assertRegex(nav_html(html), r'class="is-active" aria-current="page">\s*<span>目前使用</span>')
                self.assertIn('data-status-tab="active"', html)
                listed = self.listed(html)
                self.assertIn(on, listed)
                self.assertNotIn(off, listed)

    def test_each_page_inactive_tab_filters_list(self):
        for name, url, param, extra, on, off, expected in self.cases:
            with self.subTest(page=name):
                html = self.client.get(url, {**extra, param: "inactive"}).content.decode()
                self.assertIn('class="is-active is-inactive" aria-current="page"', nav_html(html))
                self.assertIn('data-status-tab="inactive"', html)
                listed = self.listed(html)
                self.assertIn(off, listed)
                self.assertNotIn(on, listed)
                self.assertEqual(tab_counts(html), expected)  # 筆數不因切換頁籤而變

    def test_each_page_tab_links_keep_other_conditions(self):
        for name, url, param, extra, on, off, expected in self.cases:
            with self.subTest(page=name):
                html = self.client.get(url, {**extra, "page": "1", param: "inactive"}).content.decode()
                active_href, inactive_href = tab_hrefs(html)
                self.assertIn("inactive", inactive_href)
                self.assertNotIn("inactive", active_href)
                for key in extra:
                    self.assertIn(f"{key}=", active_href)
                    self.assertIn(f"{key}=", inactive_href)
                self.assertNotIn("page=", active_href)

    def test_search_forms_carry_current_status(self):
        for url_name, param in (("accessory_product_list", "status"), ("dealer_reward_campaign_list", "tab"),
                                ("settlement_cost_rule_list", "status")):
            with self.subTest(page=url_name):
                html = self.client.get(reverse(url_name), {param: "inactive"}).content.decode()
                self.assertIn(f'<input type="hidden" name="{param}" value="inactive">', html)

    def test_legacy_status_filters_open_inactive_tab(self):
        html = self.client.get(reverse("accessory_product_list"), {"active": "no"}).content.decode()
        self.assertIn('data-status-tab="inactive"', html)
        html = self.client.get(reverse("dealer_reward_campaign_list"), {"status": "inactive"}).content.decode()
        self.assertIn('data-status-tab="inactive"', html)
        self.assertIn("T209活動乙", self.listed(html))

    def test_edit_links_and_saves_stay_on_inactive_tab(self):
        from sales.models import InstallmentCompany

        html = self.client.get(reverse("installment_company_list"), {"status": "inactive"}).content.decode()
        self.assertIn("?status=inactive&amp;edit=", html)
        company = InstallmentCompany.objects.get(name="T209分期乙")
        url = reverse("installment_company_list")
        response = self.client.post(f"{url}?status=inactive&edit={company.pk}", {
            "name": "T209分期乙", "customer_service_phone": "", "note": "", "active": "",
        })
        self.assertRedirects(response, f"{url}?status=inactive", fetch_redirect_response=False)

    def test_volume_bonus_trial_tab_has_no_status_tabs(self):
        html = self.client.get(reverse("dealer_volume_bonus_list"), {"tab": "trial", "show": "all"}).content.decode()
        self.assertEqual(nav_html(html), "")


class UserManagementStatusTabsTests(TestCase):
    """帳號管理（使用者 11-17 決定）：「使用中／已停用」頁籤、預設使用中；管理者、尚未登入改在頁籤底下篩；舊網址導過去。"""

    @classmethod
    def setUpTestData(cls):
        from django.utils import timezone

        users = get_user_model().objects
        cls.admin = users.create_superuser("t209-root", password="Test-Only-123", last_login=timezone.now())
        cls.staff = users.create_user("t209-staff", password="Test-Only-123", first_name="在職業務", last_login=timezone.now())
        cls.fresh = users.create_user("t209-fresh", password="Test-Only-123", first_name="新進未登入")
        cls.gone = users.create_user("t209-gone", password="Test-Only-123", first_name="離職人員", is_active=False)
        cls.gone_admin = users.create_superuser("t209-gone-admin", password="Test-Only-123", is_active=False,
                                                last_login=timezone.now())
        cls.url = reverse("user_management")

    def setUp(self):
        self.client.force_login(self.admin)

    def listed(self, response):
        return response.content.decode().split('data-status-tab="', 1)[1].split("帳號異動", 1)[0]

    def test_defaults_to_active_tab_with_counts(self):
        response = self.client.get(self.url)
        html = response.content.decode()
        self.assertEqual(tab_counts(html), {"active": 3, "inactive": 2})
        self.assertIn('aria-current="page">\n    <span>目前使用</span>\n    <strong>使用中帳號</strong>', nav_html(html))
        listed = self.listed(response)
        self.assertIn("@t209-staff", listed)
        self.assertIn("@t209-fresh", listed)
        self.assertNotIn("@t209-gone", listed)
        self.assertNotIn('class="account-summary"', html)  # 「全部帳號」統計卡拿掉，改用頁籤

    def test_inactive_tab_lists_only_disabled_accounts(self):
        response = self.client.get(self.url, {"status": "inactive"})
        listed = self.listed(response)
        self.assertIn("@t209-gone", listed)
        self.assertIn("@t209-gone-admin", listed)
        self.assertNotIn("@t209-staff", listed)
        self.assertEqual(tab_counts(response.content.decode()), {"active": 3, "inactive": 2})

    def test_admin_and_never_login_filters_work_inside_each_tab(self):
        listed = self.listed(self.client.get(self.url, {"role": "admins"}))
        self.assertIn("@t209-root", listed)
        self.assertNotIn("@t209-staff", listed)
        self.assertNotIn("@t209-gone-admin", listed)
        listed = self.listed(self.client.get(self.url, {"status": "inactive", "role": "admins"}))
        self.assertIn("@t209-gone-admin", listed)
        self.assertNotIn("@t209-gone<", listed.replace("@t209-gone-admin", ""))
        listed = self.listed(self.client.get(self.url, {"role": "never_login"}))
        self.assertIn("@t209-fresh", listed)
        self.assertNotIn("@t209-staff", listed)

    def test_tab_links_keep_search_and_role_filter(self):
        html = self.client.get(self.url, {"q": "t209", "role": "admins", "status": "inactive"}).content.decode()
        active_href, inactive_href = tab_hrefs(html)
        for href in (active_href, inactive_href):
            self.assertIn("q=t209", href)
            self.assertIn("role=admins", href)
        self.assertIn("status=active", active_href)
        self.assertIn('<input type="hidden" name="status" value="inactive">', html)
        self.assertIn('<option value="admins" selected>', html)

    def test_legacy_status_links_redirect_to_the_tabs(self):
        cases = {
            "all": f"{self.url}?q=t209&status=active",
            "admins": f"{self.url}?q=t209&status=active&role=admins",
            "never_login": f"{self.url}?q=t209&status=active&role=never_login",
        }
        for legacy, target in cases.items():
            with self.subTest(status=legacy):
                response = self.client.get(self.url, {"q": "t209", "status": legacy})
                self.assertRedirects(response, target)
        listed = self.listed(self.client.get(self.url, {"status": "inactive", "q": "離職"}))
        self.assertIn("@t209-gone", listed)
