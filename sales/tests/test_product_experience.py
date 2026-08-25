from pathlib import Path

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.http import HttpResponse
from django.test import RequestFactory, TestCase
from django.urls import reverse

from config.middleware import RequestIdMiddleware
from sales import views
from sales.models import UserAppearancePreference


class ProductExperienceTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(
            username="guide-user",
            password="test-pass-123",
        )

    def test_user_guide_requires_login_and_is_task_oriented(self):
        response = self.client.get(reverse("user_guide"))
        self.assertRedirects(
            response,
            f"{reverse('login')}?next={reverse('user_guide')}",
        )

        self.client.force_login(self.user)
        response = self.client.get(reverse("user_guide"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "現在想做什麼？從任務開始找")
        self.assertContains(response, 'data-guide-search')
        self.assertContains(response, 'id="create-order"')
        self.assertContains(response, 'id="ocr"')
        self.assertContains(response, 'id="inventory"')
        self.assertContains(response, 'id="troubleshooting"')
        self.assertContains(response, "LicenseWatcher 尚未啟用")
        self.assertContains(response, 'data-print-guide')

    def test_navigation_opens_context_help_without_leaving_work(self):
        self.client.force_login(self.user)

        dashboard = self.client.get(reverse("dashboard"))
        self.assertContains(dashboard, f'{reverse("user_guide")}#dashboard')
        self.assertContains(dashboard, 'target="_blank"')
        self.assertContains(dashboard, "不會離開目前資料")

        inventory = self.client.get(reverse("inventory_list"))
        self.assertContains(inventory, f'{reverse("user_guide")}#inventory')

    def test_data_navigation_exposes_common_maintenance_without_extra_detour(self):
        self.client.force_login(self.user)

        source_page = self.client.get(reverse("sales_source_list"))

        self.assertEqual(source_page.status_code, 200)
        self.assertContains(source_page, 'class="desktop-data-menu active"')
        self.assertContains(source_page, "車行、平台與傭金")
        self.assertContains(source_page, reverse("accessory_product_list"))
        self.assertContains(source_page, reverse("settlement_cost_rule_list"))
        self.assertContains(source_page, reverse("incentive_rule_list"))
        self.assertContains(source_page, reverse("dealer_volume_bonus_list"))
        self.assertContains(source_page, reverse("business_holiday_list"))
        self.assertContains(source_page, 'class="mobile-data-popover__grid"')
        self.assertContains(source_page, "全部功能 →")

        css = Path("static/css/app.css").read_text(encoding="utf-8")
        navigation = Path("static/js/ui-navigation.js").read_text(encoding="utf-8")
        self.assertIn("max-height: min(72vh, 650px)", css)
        self.assertIn(
            ".hero-row { align-items: stretch; flex-direction: column; gap: 14px; }",
            css,
        )
        self.assertIn('event.key === "Escape"', navigation)
        self.assertIn('window.history.scrollRestoration = "auto"', navigation)
        self.assertIn("parseSameOriginUrl", navigation)
        self.assertIn("data-current-page-label", navigation)

    def test_disclosure_controls_use_consistent_font_independent_chevrons(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            'class="ui-chevron desktop-data-menu__chevron"',
            html=False,
        )
        css = Path("static/css/app.css").read_text(encoding="utf-8")
        searchable_select = Path("static/js/searchable-select.js").read_text(
            encoding="utf-8"
        )
        disclosure_templates = "".join(
            Path(path).read_text(encoding="utf-8")
            for path in (
                "templates/base.html",
                "templates/sales/vehicle_model_list.html",
                "templates/sales/order_detail.html",
                "templates/sales/user_management.html",
                "templates/sales/operations_report.html",
            )
        )
        self.assertIn(".ui-chevron {", css)
        self.assertIn("border-right: 2px solid currentColor", css)
        self.assertIn("searchable-select.is-open", css)
        self.assertIn('class="ui-chevron"', searchable_select)
        self.assertNotIn("⌄", css)
        self.assertNotIn("⌄", searchable_select)
        self.assertNotIn("⌄", disclosure_templates)

    def test_professional_theme_uses_semantic_tokens_and_accessible_contrast(self):
        css = Path("static/css/app.css").read_text(encoding="utf-8")

        for token in (
            "--navy: #18323b",
            "--forest: #0e5d57",
            "--gold: #c99735",
            "--ink: #17252b",
            "--muted: #526168",
            "--field-label: var(--ink)",
            "--field-hint: var(--muted)",
            "--line: #c9d2d5",
            "--focus-ring: #d6a63c",
            "--surface-raised: #ffffff",
            "--header-surface: var(--navy)",
        ):
            with self.subTest(token=token):
                self.assertIn(token, css)

        def relative_luminance(hex_color):
            channels = [
                int(hex_color[index : index + 2], 16) / 255
                for index in (1, 3, 5)
            ]
            linear = [
                channel / 12.92
                if channel <= 0.04045
                else ((channel + 0.055) / 1.055) ** 2.4
                for channel in channels
            ]
            return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

        def contrast_ratio(foreground, background):
            values = sorted(
                (relative_luminance(foreground), relative_luminance(background))
            )
            return (values[1] + 0.05) / (values[0] + 0.05)

        for foreground, background in (
            ("#17252b", "#f3f5f6"),
            ("#526168", "#ffffff"),
            ("#ffffff", "#0e5d57"),
            ("#ffffff", "#18323b"),
        ):
            with self.subTest(foreground=foreground, background=background):
                self.assertGreaterEqual(contrast_ratio(foreground, background), 4.5)

        theme_contrast_pairs = {
            "professional": (
                ("#17252b", "#f3f5f6"),
                ("#526168", "#ffffff"),
                ("#ffffff", "#0e5d57"),
                ("#ffffff", "#18323b"),
            ),
            "deep-blue": (
                ("#18283b", "#f2f5f9"),
                ("#52657b", "#ffffff"),
                ("#ffffff", "#245b86"),
                ("#ffffff", "#162c4a"),
            ),
            "graphite-gold": (
                ("#27292d", "#f4f3ef"),
                ("#5c6067", "#ffffff"),
                ("#ffffff", "#72520a"),
                ("#ffffff", "#2b2e33"),
            ),
            "bright-indigo": (
                ("#20243a", "#f4f5fb"),
                ("#565e78", "#ffffff"),
                ("#ffffff", "#3b4e9a"),
                ("#ffffff", "#252a57"),
            ),
            "high-contrast": (
                ("#101820", "#ffffff"),
                ("#38474d", "#ffffff"),
                ("#ffffff", "#005544"),
                ("#ffffff", "#0b1f2a"),
            ),
            "night-blue": (
                ("#e8eef0", "#081117"),
                ("#a9b6bc", "#132129"),
                ("#42b883", "#17382f"),
                ("#ffffff", "#1f746d"),
                ("#eff5f6", "#172f3a"),
            ),
        }
        for theme, pairs in theme_contrast_pairs.items():
            for foreground, background in pairs:
                with self.subTest(
                    theme=theme,
                    foreground=foreground,
                    background=background,
                ):
                    self.assertGreaterEqual(
                        contrast_ratio(foreground, background),
                        4.5,
                    )

    def test_searchable_select_supports_recent_keyboard_and_empty_options(self):
        script = Path("static/js/searchable-select.js").read_text(encoding="utf-8")
        css = Path("static/css/app.css").read_text(encoding="utf-8")

        self.assertIn('input.type = "search"', script)
        self.assertIn('const toggle = document.createElement("span")', script)
        self.assertIn('toggle.setAttribute("aria-hidden", "true")', script)
        self.assertNotIn('toggle.addEventListener("click"', script)
        self.assertIn("pointer-events: none", css)
        self.assertIn('select.dataset.searchableEmptyPlaceholder === "1"', script)
        self.assertIn('select.dataset.searchableSearchIcon === "1"', script)
        self.assertIn('searchIcon.className = "searchable-select__search-icon"', script)
        self.assertIn(".searchable-select__search-icon {", css)
        self.assertIn("localStorage.setItem(storageKey", script)
        self.assertIn('event.key === "ArrowDown"', script)
        self.assertIn('event.key === "Enter"', script)
        self.assertIn('event.key === "Escape"', script)
        self.assertIn('empty.textContent = "找不到符合的選項"', script)
        self.assertIn('select.dataset.searchableIncludeEmpty === "1"', script)

    def test_authenticated_user_can_preview_and_sync_theme_across_pages(self):
        self.client.force_login(self.user)
        target = reverse("vehicle_model_list")

        response = self.client.post(
            reverse("appearance_theme_update"),
            {"theme": "deep-blue", "next": target},
        )

        self.assertRedirects(response, target)
        preference = UserAppearancePreference.objects.get(user=self.user)
        self.assertEqual(preference.theme, "deep-blue")

        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, 'data-theme="deep-blue"')
        self.assertContains(response, '<meta name="theme-color" content="#162c4a">')
        self.assertContains(response, 'data-theme-dialog')
        self.assertContains(response, "專業藍綠")
        self.assertContains(response, "夜間深藍")
        self.assertContains(response, "跟隨裝置")
        self.assertContains(response, "沉穩深藍")
        self.assertContains(response, "石墨灰金")
        self.assertContains(response, "明亮靛藍")
        self.assertContains(response, "高對比")
        self.assertContains(response, "theme-selector.js")

        response = self.client.post(
            reverse("appearance_theme_update"),
            {"theme": "system", "next": target},
        )
        self.assertRedirects(response, target)
        self.assertEqual(
            UserAppearancePreference.objects.get(user=self.user).theme,
            "system",
        )
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, 'data-theme="system"')

    def test_theme_update_rejects_unknown_theme_and_external_return_url(self):
        UserAppearancePreference.objects.create(
            user=self.user,
            theme="graphite-gold",
        )
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("appearance_theme_update"),
            {"theme": "not-a-theme", "next": "https://example.org/steal"},
        )

        self.assertRedirects(response, reverse("dashboard"))
        self.assertEqual(
            UserAppearancePreference.objects.get(user=self.user).theme,
            "graphite-gold",
        )

    def test_theme_update_requires_login_and_post(self):
        endpoint = reverse("appearance_theme_update")
        response = self.client.post(endpoint, {"theme": "high-contrast"})
        self.assertRedirects(response, f'{reverse("login")}?next={endpoint}')

        self.client.force_login(self.user)
        response = self.client.get(endpoint)
        self.assertEqual(response.status_code, 405)

    def test_theme_preview_is_immediate_but_print_colors_stay_fixed(self):
        css = Path("static/css/app.css").read_text(encoding="utf-8")
        script = Path("static/js/theme-selector.js").read_text(encoding="utf-8")

        self.assertIn('html[data-theme="deep-blue"]', css)
        self.assertIn('html[data-theme="graphite-gold"]', css)
        self.assertIn('html[data-theme="bright-indigo"]', css)
        self.assertIn('html[data-theme="high-contrast"]', css)
        self.assertIn('html[data-theme="night-blue"]', css)
        self.assertIn('html[data-theme="system"]', css)
        self.assertIn("prefers-color-scheme: dark", css)
        self.assertIn("color-scheme: dark", css)
        self.assertEqual(css.count("--header-surface: #172f3a"), 2)
        self.assertEqual(css.count("--surface-raised: #1c3039"), 2)
        self.assertIn("background: var(--header-surface)", css)
        self.assertIn("background: var(--header-interactive)", css)
        self.assertIn("background: var(--surface-raised)", css)
        self.assertIn("@media print", css)
        self.assertIn("html[data-theme]", css)
        self.assertIn("root.dataset.theme = theme", script)
        self.assertIn('updateSelection("professional")', script)
        self.assertIn('matchMedia?.("(prefers-color-scheme: dark)")', script)
        self.assertIn('updateThemeMeta(root.dataset.theme || "professional")', script)
        self.assertNotIn("localStorage", script)

    def test_maintenance_help_stays_on_master_data_topic(self):
        self.client.force_login(self.user)

        for route in (
            reverse("sales_source_list"),
            reverse("dealer_volume_bonus_list"),
            reverse("business_holiday_list"),
            reverse("brand_registration_fee_rule_list"),
        ):
            with self.subTest(route=route):
                response = self.client.get(route)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, f'{reverse("user_guide")}#master-data')

    def test_every_maintenance_landing_page_has_a_clear_return_path(self):
        self.client.force_login(self.user)

        expected_parents = {
            "data_maintenance": "dashboard",
            "customer_list": "data_maintenance",
            "inventory_list": "data_maintenance",
            "vehicle_model_list": "data_maintenance",
            "accessory_product_list": "data_maintenance",
            "sales_source_list": "data_maintenance",
            "installment_company_list": "data_maintenance",
            "dealer_volume_bonus_list": "sales_source_list",
            "business_holiday_list": "data_maintenance",
            "brand_registration_fee_rule_list": "data_maintenance",
            "settlement_cost_rule_list": "data_maintenance",
            "incentive_rule_list": "data_maintenance",
            "legacy_import_list": "data_maintenance",
            "positioned_template_list": "data_maintenance",
        }
        for route_name, parent_name in expected_parents.items():
            with self.subTest(route_name=route_name):
                response = self.client.get(reverse(route_name))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'class="page-context-nav"')
                self.assertContains(response, f'href="{reverse(parent_name)}"')
                self.assertContains(response, "data-smart-back")
                self.assertContains(response, "回到上一畫面")
                self.assertContains(response, 'class="page-breadcrumbs"')

    def test_every_response_has_non_sensitive_request_id(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("dashboard"))
        request_id = response.headers.get("X-Request-ID")
        self.assertRegex(request_id, r"^[A-F0-9]{12}$")

    def test_health_endpoint_is_minimal_and_does_not_require_login(self):
        response = self.client.get(reverse("system_health"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True})

    def test_diagnostics_requires_login_and_uses_plain_language(self):
        url = reverse("system_diagnostics")
        anonymous = self.client.get(url)
        self.assertRedirects(anonymous, f"{reverse('login')}?next={url}")

        self.client.force_login(self.user)
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "系統狀態")
        self.assertContains(response, "訂單資料庫")
        self.assertContains(response, "全欄位搜尋")
        self.assertContains(response, "照片與文件空間")
        self.assertNotContains(response, "DJANGO_SECRET_KEY")
        self.assertNotContains(response, "REDIS_URL")

    def test_error_pages_use_plain_language_and_support_reference(self):
        request = RequestFactory().get("/missing/")
        request.user = AnonymousUser()
        request.request_id = "ABCDEF123456"

        not_found = views.page_not_found(request)
        self.assertEqual(not_found.status_code, 404)
        self.assertIn("找不到你要開啟的頁面", not_found.content.decode())

        server_error = views.server_error(request)
        body = server_error.content.decode()
        self.assertEqual(server_error.status_code, 500)
        self.assertIn("ABCDEF123456", body)
        self.assertIn("這不是你的操作問題", body)

    def test_legacy_odoo_urls_redirect_to_current_django_pages(self):
        response = self.client.get("/web")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("dashboard"))

        response = self.client.get("/web/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("dashboard"))

        response = self.client.get(
            "/zh_TW/data/vehicle-models/", {"_appv": "legacy"}
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("vehicle_model_list"))

    def test_request_id_middleware_marks_failures(self):
        middleware = RequestIdMiddleware(lambda request: HttpResponse(status=500))
        response = middleware(RequestFactory().get("/broken/"))
        self.assertRegex(response["X-Request-ID"], r"^[A-F0-9]{12}$")

    def test_common_ux_scripts_include_recovery_controls(self):
        feedback = Path("static/js/form-feedback.js").read_text(encoding="utf-8")
        connectivity = Path("static/js/connectivity-status.js").read_text(
            encoding="utf-8"
        )
        base = Path("templates/base.html").read_text(encoding="utf-8")

        self.assertIn("dataset.formErrorSummary", feedback)
        self.assertIn("還有 ${result.items.length} 個地方需要確認", feedback)
        self.assertIn("請先上傳證件正反面", feedback)
        self.assertIn("dataset.submitting", feedback)
        self.assertIn("資料正在處理，請不要重複送出", feedback)
        self.assertIn('window.addEventListener("offline"', connectivity)
        self.assertIn("尚未送出的內容可能還沒同步", base)

    def test_login_is_temporarily_throttled_after_repeated_failures(self):
        login_url = reverse("login")
        for _ in range(4):
            response = self.client.post(
                login_url,
                {"username": self.user.username, "password": "wrong-password"},
            )
            self.assertEqual(response.status_code, 200)

        response = self.client.post(
            login_url,
            {"username": self.user.username, "password": "wrong-password"},
        )
        self.assertContains(response, "帳號已暫停嘗試 15 分鐘")

        response = self.client.post(
            login_url,
            {"username": self.user.username, "password": "test-pass-123"},
        )
        self.assertContains(response, "請 15 分鐘後再試")

        cache.clear()
        response = self.client.post(
            login_url,
            {"username": self.user.username, "password": "test-pass-123"},
        )
        self.assertRedirects(response, reverse("dashboard"))

    def test_admin_login_cannot_bypass_the_same_throttle(self):
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        admin_login_url = reverse("admin:login")

        for _ in range(5):
            response = self.client.post(
                admin_login_url,
                {"username": self.user.username, "password": "wrong-password"},
            )
            self.assertEqual(response.status_code, 200)

        response = self.client.post(
            admin_login_url,
            {"username": self.user.username, "password": "test-pass-123"},
        )
        self.assertContains(response, "請 15 分鐘後再試")


class UserDocumentationTests(TestCase):
    def test_end_user_manual_is_current_django_workflow(self):
        manual = Path("docs/USER_MANUAL.md").read_text(encoding="utf-8")
        self.assertIn("戰情首頁與全欄位搜尋", manual)
        self.assertIn("訂單建立後怎麼做", manual)
        self.assertIn("營運、淨利與對帳", manual)
        self.assertNotIn("Odoo 16", manual)
        self.assertNotIn("8069", manual)
