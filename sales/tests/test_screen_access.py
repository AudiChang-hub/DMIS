import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import skipUnless

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse

from sales import urls
from sales.access.models import ReportAccessGrant, ScreenAccessGrant, UserAccessRevision, UserAccessState
from sales.access.registry import LOOKUPS, PERSONAL, REPORT_ROUTES, ROOT_ONLY, ROUTES, SPECIAL, TOGGLE_RESOURCES
from sales.access.services import AccessPolicy, apply_policy, normalize
from sales.models import ReportDefinition
from sales.reporting.views import initial_config, navigation


class ScreenAccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.root = get_user_model().objects.create_superuser("admin", password="Test-Only-123")
        cls.user = get_user_model().objects.create_user("limited", password="Test-Only-123")
        cls.legacy = get_user_model().objects.create_user("legacy", password="Test-Only-123")
        cls.manager = get_user_model().objects.create_superuser("manager", password="Test-Only-123")
        UserAccessState.objects.create(user=cls.user, configured=True)
        config = initial_config()
        config.update(audience="team", include_records=True)
        cls.report = ReportDefinition.objects.create(draft=config, published=config)

    def setUp(self):
        self.client.force_login(self.user)

    def grant(self, key, **actions):
        return ScreenAccessGrant.objects.create(user=self.user, screen_key=key, view=True, **actions)

    def preview(self, **data):
        self.client.force_login(self.root)
        return self.client.post(reverse("access_edit", args=[self.user.pk]), {"action": "preview", "version": "0", **data})

    def test_every_business_route_is_explicitly_classified_including_aliases(self):
        known = set(ROUTES) | PERSONAL | ROOT_ONLY | set(REPORT_ROUTES) | set(LOOKUPS) | SPECIAL
        for route in urls.urlpatterns:
            name = getattr(route.callback, "view_initkwargs", {}).get("pattern_name") or route.name
            with self.subTest(route=str(route.pattern)):
                self.assertIn(name, known)
        from sales.views import ACTIVE_TOGGLE_RESOURCES
        self.assertEqual(set(TOGGLE_RESOURCES), set(ACTIVE_TOGGLE_RESOURCES))

    def test_deny_all_business_get_and_post_before_loading_records(self):
        for route in urls.urlpatterns:
            name = getattr(route.callback, "view_initkwargs", {}).get("pattern_name") or route.name
            if name in PERSONAL | SPECIAL or name == "dashboard":
                continue
            args = {}
            for key, converter in route.pattern.converters.items():
                args[key] = uuid.UUID(int=1) if converter.__class__.__name__ == "UUIDConverter" else 999999
            path = "/" + route.pattern._route
            import re
            path = re.sub(r"<[^:>]+:([^>]+)>", lambda m: str(args[m[1]]), path)
            for method in ("get", "post"):
                with self.subTest(name=name, method=method):
                    self.assertEqual(getattr(self.client, method)(path).status_code, 403)

    def test_legacy_preserved_and_new_policy_does_not_change_superuser(self):
        self.assertTrue(AccessPolicy(self.legacy).screen("orders", "operate"))
        self.assertFalse(AccessPolicy(self.user).screen("orders"))
        self.assertTrue(AccessPolicy(self.root).screen("orders", "export"))
        self.assertFalse(AccessPolicy(self.manager).route("access_overview"))

    def test_view_does_not_allow_write_form_post_export_or_toggle(self):
        self.grant("brands")
        self.grant("orders")
        self.assertEqual(self.client.get(reverse("vehicle_brand_list")).status_code, 200)
        for name, args, method in (("vehicle_brand_list", [], "post"), ("order_create", [], "get"),
                                  ("master_record_set_active", ["vehicle-brand", 999], "post"),
                                  ("contract_print", [999], "get")):
            self.assertEqual(getattr(self.client, method)(reverse(name, args=args)).status_code, 403)
        self.assertEqual(self.client.get(reverse("vehicle_colors")).status_code, 200)
        self.assertEqual(self.client.get(reverse("sales_sources")).status_code, 200)

    def test_no_permission_home_and_navigation_do_not_leak_counts_or_shortcuts(self):
        self.assertRedirects(self.client.get(reverse("dashboard")), reverse("access_home"))
        response = self.client.get(reverse("data_maintenance"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, reverse("inventory_list"))
        self.assertNotContains(response, reverse("order_list"))
        self.assertNotContains(response, reverse("sales_source_list"))
        self.assertContains(response, reverse("password_change_required"))
        self.assertNotContains(response, "個機種")

    def test_report_allowlist_export_and_new_report_default_deny(self):
        grant = ReportAccessGrant.objects.create(user=self.user, report=self.report, view=True)
        url = reverse("report_display", args=[self.report.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "data-report-print")
        self.assertNotContains(response, "匯出 CSV")
        self.assertEqual(self.client.get(reverse("report_records_export", args=[self.report.pk])).status_code, 403)
        grant.export = True
        grant.save()
        self.assertEqual(self.client.get(reverse("report_records_export", args=[self.report.pk])).status_code, 200)
        other = ReportDefinition.objects.create(draft=self.report.draft, published=self.report.published)
        self.assertEqual(self.client.get(reverse("report_display", args=[other.pk])).status_code, 403)
        from django.test import RequestFactory
        request = RequestFactory().get("/")
        request.user = self.user
        self.assertEqual([r.pk for group in navigation(request) for r in group["pages"]], [self.report.pk])

    def test_sensitive_report_ceiling_cannot_be_overridden(self):
        ReportAccessGrant.objects.create(user=self.user, report=self.report, view=True, export=True)
        for config in ({"audience": "admin"}, {"records_mode": "population"}, {"records_columns": ["legacy_notes"]}):
            self.report.published = {**self.report.draft, **config}
            self.report.save()
            self.assertEqual(self.client.get(reverse("report_display", args=[self.report.pk])).status_code, 403)

    def test_revocation_applies_to_existing_session_next_request(self):
        grant = self.grant("brands")
        url = reverse("vehicle_brand_list")
        self.assertEqual(self.client.get(url).status_code, 200)
        grant.delete()
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_preview_requires_confirmation_and_signed_target_bound_token(self):
        response = self.preview(**{"screens.brands.view": "on"})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(ScreenAccessGrant.objects.filter(user=self.user).exists())
        token = response.context["preview_token"]
        other_url = reverse("access_edit", args=[self.legacy.pk])
        self.assertEqual(self.client.post(other_url, {"action": "apply", "preview_token": token}).status_code, 403)
        url = reverse("access_edit", args=[self.user.pk])
        self.assertEqual(self.client.post(url, {"action": "apply", "preview_token": token + "broken"}).status_code, 409)
        self.assertRedirects(self.client.post(url, {"action": "apply", "preview_token": token}), url)
        self.assertTrue(AccessPolicy(self.user).screen("brands"))
        self.assertFalse(AccessPolicy(self.user).screen("orders"))
        self.assertEqual(self.client.post(url, {"action": "apply", "preview_token": token}).status_code, 409)
        self.assertEqual(UserAccessRevision.objects.filter(user=self.user).count(), 1)

    def test_copy_restore_only_preview_and_revision_is_bound_to_person(self):
        self.grant("brands")
        self.client.force_login(self.root)
        url = reverse("access_edit", args=[self.legacy.pk])
        response = self.client.post(url, {"action": "copy", "version": "0", "source": self.user.pk})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(UserAccessState.objects.filter(user=self.legacy).exists())
        self.client.post(url, {"action": "apply", "preview_token": response.context["preview_token"]})
        revision = UserAccessRevision.objects.get(user=self.legacy)
        response = self.client.post(url, {"action": "restore", "version": "1", "revision": revision.pk})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(UserAccessRevision.objects.filter(user=self.legacy).count(), 1)
        self.assertEqual(self.client.post(reverse("access_edit", args=[self.user.pk]), {"action": "restore", "version": "0", "revision": revision.pk}).status_code, 404)
        self.legacy.refresh_from_db()
        self.assertFalse(self.legacy.is_superuser)

    def test_cancel_view_removes_dependent_flags_server_side(self):
        response = self.preview(**{"screens.orders.operate": "on", "screens.orders.export": "on"})
        self.client.post(reverse("access_edit", args=[self.user.pk]), {"action": "apply", "preview_token": response.context["preview_token"]})
        self.assertFalse(AccessPolicy(self.user).screen("orders", "export"))
        self.assertFalse(ScreenAccessGrant.objects.filter(user=self.user).exists())

    def test_admin_identity_protected_even_from_legacy_superuser(self):
        self.client.force_login(self.manager)
        for route in ("user_account_edit", "user_account_status", "user_account_reset_password"):
            self.assertEqual(self.client.post(reverse(route, args=[self.root.pk]), {"is_active": "on"}).status_code, 403)
        self.assertEqual(self.client.post(reverse("user_account_edit", args=[self.manager.pk]), {"username": "admin"}).status_code, 403)
        self.client.force_login(self.root)
        self.assertEqual(self.client.post(reverse("user_account_edit", args=[self.root.pk]), {"username": "renamed", "is_active": "on", "is_superuser": "on"}).status_code, 403)
        self.assertEqual(self.client.get(reverse("access_edit", args=[self.root.pk])).status_code, 302)

    def test_configured_superuser_cannot_bypass_using_django_admin(self):
        UserAccessState.objects.create(user=self.manager, configured=True)
        self.client.force_login(self.manager)
        self.assertEqual(self.client.get("/admin/").status_code, 403)
        self.assertEqual(self.client.get(reverse("access_overview")).status_code, 403)

    def test_new_ui_account_starts_with_no_business_grants(self):
        self.client.force_login(self.root)
        response = self.client.post(reverse("user_account_create"), {"display_name": "新員工", "username": "new-staff", "password1": "Test-Only-123", "password2": "Test-Only-123", "is_active": "on"})
        self.assertEqual(response.status_code, 302)
        user = get_user_model().objects.get(username="new-staff")
        self.assertTrue(UserAccessState.objects.get(user=user).configured)
        self.assertFalse(AccessPolicy(user).screen("orders"))

    def test_csrf_required_and_inactive_grants_are_ineffective(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.root)
        self.assertEqual(csrf_client.post(reverse("access_edit", args=[self.user.pk]), {"action": "preview"}).status_code, 403)
        self.grant("brands", operate=True)
        self.user.is_active = False
        self.user.save()
        self.assertFalse(AccessPolicy(self.user).screen("brands"))
        self.assertEqual(self.client.get(reverse("vehicle_brand_list")).status_code, 302)

    def test_inactive_account_retains_saved_policy_and_can_be_preconfigured(self):
        self.grant("brands", operate=True)
        ReportAccessGrant.objects.create(user=self.user, report=self.report, view=True)
        UserAccessState.objects.filter(user=self.user).update(version=3)
        self.user.is_active = False
        self.user.save()
        from sales.access.services import snapshot
        saved = snapshot(self.user, [self.report])
        self.assertEqual(saved["version"], 3)
        self.assertTrue(saved["screens"]["brands"]["operate"])
        self.assertTrue(saved["reports"][str(self.report.pk)]["view"])
        self.assertFalse(AccessPolicy(self.user).report(self.report))
        self.client.force_login(self.root)
        response = self.client.get(reverse("access_edit", args=[self.user.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "第 3 版")

    def test_malformed_copy_identifier_returns_validation_error(self):
        self.client.force_login(self.root)
        response = self.client.post(reverse("access_edit", args=[self.user.pk]), {"action": "copy", "version": "0", "source": "invalid"})
        self.assertEqual(response.status_code, 409)

    def test_report_order_number_remains_text_when_order_screen_is_denied(self):
        from django.core.paginator import Paginator
        from django.template.loader import render_to_string
        from django.test import RequestFactory
        from types import SimpleNamespace
        request = RequestFactory().get("/reports/")
        request.user = self.user
        order = SimpleNamespace(pk=998, number="QA-REPORT-ORDER")
        html = render_to_string("sales/reporting/detail_panel.html", {"card": {"title": "測試"}, "page_obj": Paginator([order], 50).page(1)}, request=request)
        self.assertIn("QA-REPORT-ORDER", html)
        self.assertNotIn(reverse("order_detail", args=[998]), html)


@skipUnless(connection.vendor == "postgresql", "需 PostgreSQL 驗證列鎖")
class ScreenAccessConcurrencyTests(TransactionTestCase):
    def test_first_apply_serializes_and_stale_writer_cannot_overwrite(self):
        root = get_user_model().objects.create_superuser("admin", password="Test-Only-123")
        user = get_user_model().objects.create_user("concurrent")
        barrier = Barrier(2)
        draft = normalize(user, {}, [])

        def write():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                apply_policy(actor=root, user=user, expected_version=0, data=draft, reports=[])
                return "saved"
            except ValidationError:
                return "stale"
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(write) for _ in range(2)]
            self.assertCountEqual([future.result(timeout=20) for future in futures], ["saved", "stale"])
        self.assertEqual(UserAccessState.objects.get(user=user).version, 1)
        self.assertEqual(UserAccessRevision.objects.filter(user=user).count(), 1)
