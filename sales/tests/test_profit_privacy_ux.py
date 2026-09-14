from datetime import timedelta
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from sales.access.models import ScreenAccessGrant, UserAccessState
from sales.access.services import AccessPolicy
from sales.models import SalesOrder, VehicleModel, VehicleColor, OrderOperationsProfile, SalesSource, OrderAccountProfile, VehicleCatalogEntry
from sales.services.audience_content import RELEASE_RULES, release_context
from sales.services.profit_access import SESSION_KEY
from config.release_notes import RELEASES


class ProfitPrivacyTests(TestCase):
    def test_locked_search_excludes_finance_json_and_original_values(self):
        from sales.models import LegacySalesSnapshot, SalesOrderSearchIndex, LegacyImportRow, LegacyImportBatch
        from sales.services.order_search import rebuild_order_search_index
        batch = LegacyImportBatch.objects.create(import_type="operations", original_filename="synthetic.xlsx", file_size=0)
        row = LegacyImportRow.objects.create(batch=batch, sheet_name="銷貨", source_row=1, fingerprint="privacy")
        LegacySalesSnapshot.objects.create(order=self.order, import_row=row, raw_financials={"單筆淨利": "privateprofit98271"})
        OrderOperationsProfile.objects.filter(order=self.order).update(legacy_finance_reconciliation={"source_profit": "privatejson76193"})
        rebuild_order_search_index(self.order.pk)
        self.client.force_login(self.root)
        for query in ("privateprofit98271", "privatejson76193"):
            response = self.client.get(reverse("order_list"), {"q": query})
            self.assertEqual(response.context["page_obj"].paginator.count, 0)
        # 一般車主／車牌搜尋繼續可用，不依賴解鎖。
        self.assertEqual(self.client.get(reverse("order_list"), {"q": self.order.owner_name}).context["page_obj"].paginator.count, 1)
        self.unlock()
        self.assertEqual(self.client.get(reverse("order_list"), {"q": "privateprofit98271"}).context["page_obj"].paginator.count, 1)
        # 舊快取回填也必須移除敏感值，且可重跑。
        from importlib import import_module
        from django.apps import apps
        from django.db import connection
        migration = import_module("sales.migrations.0139_safe_order_search")
        from types import SimpleNamespace
        editor = SimpleNamespace(connection=connection)
        migration.backfill(apps, editor)
        migration.backfill(apps, editor)
        index = SalesOrderSearchIndex.objects.get(order=self.order)
        self.assertNotIn("privateprofit", index.safe_search_text)
        self.assertNotIn("privatejson", index.safe_search_text)

    def test_profit_export_needs_separate_export_grant(self):
        ScreenAccessGrant.objects.create(user=self.staff, screen_key="profit", view=True, export=False)
        ScreenAccessGrant.objects.create(user=self.staff, screen_key="operations", view=True, export=True)
        self.unlock(self.staff)
        self.assertEqual(self.client.get(reverse("operations_report_export")).status_code, 403)
        ScreenAccessGrant.objects.filter(user=self.staff, screen_key="profit").update(export=True)
        self.assertEqual(self.client.get(reverse("operations_report_export")).status_code, 200)

    def test_history_and_emergency_admin_do_not_bypass_lock(self):
        from sales.models import OrderChange
        OrderChange.objects.create(order=self.order, actor_name="合成人員", reason="合成核對",
            changes={"legacy_finance_reconciliation": {"before": "", "after": "privateprofit86423"},
                     "備註": {"before": "", "after": "正常可見備註"}})
        self.client.force_login(self.root)
        response = self.client.get(reverse("order_detail", args=[self.order.pk]))
        self.assertNotContains(response, "privateprofit86423")
        self.assertContains(response, "正常可見備註")
        url = reverse("admin:sales_orderoperationsprofile_change", args=[self.order.operations.pk])
        self.assertEqual(self.client.get(url).status_code, 302)
        self.assertIn(reverse("profit_unlock"), self.client.get(url).url)
        self.unlock()
        self.assertContains(self.client.get(reverse("order_detail", args=[self.order.pk])), "privateprofit86423")
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_color_image_validation_and_parent_isolation(self):
        import io
        import tempfile
        from PIL import Image
        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.test import override_settings
        with tempfile.TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            VehicleCatalogEntry.objects.create(vehicle_model=self.model, published=True)
            buffer = io.BytesIO(); Image.new("RGB", (20, 20), "blue").save(buffer, "PNG")
            self.client.force_login(self.root)
            response = self.client.post(reverse("catalog_edit", args=[self.model.pk]), {
                "expected_revision": 0, "position": 0, "published": "on",
                f"color_image_{self.color.pk}": SimpleUploadedFile("blue.png", buffer.getvalue(), content_type="image/png")})
            self.assertEqual(response.status_code, 302)
            self.client.logout()
            url = reverse("catalog_color_image", args=[self.model.pk, self.color.pk])
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200); response.close()
            self.assertEqual(response["Cache-Control"], "no-store")
            other = VehicleModel.objects.create(brand="TEST", name="其他型號")
            VehicleCatalogEntry.objects.create(vehicle_model=other, published=True)
            self.assertEqual(self.client.get(reverse("catalog_color_image", args=[other.pk, self.color.pk])).status_code, 404)
            self.assertContains(self.client.get(reverse("catalog_detail", args=[self.model.pk])), 'type="radio" name="color"')
            VehicleCatalogEntry.objects.filter(vehicle_model=self.model).update(published=False)
            self.assertEqual(self.client.get(url).status_code, 404)
            VehicleCatalogEntry.objects.filter(vehicle_model=self.model).update(published=True)
            VehicleColor.objects.filter(pk=self.color.pk).update(active=False)
            self.assertEqual(self.client.get(url).status_code, 404)

    @classmethod
    def setUpTestData(cls):
        cls.root = get_user_model().objects.create_superuser("admin", password="Privacy-test-730!")
        cls.staff = get_user_model().objects.create_user("limited", password="Privacy-test-730!")
        cls.state = UserAccessState.objects.create(user=cls.staff, configured=True)
        ScreenAccessGrant.objects.create(user=cls.staff, screen_key="orders", view=True)
        cls.model = VehicleModel.objects.create(brand="TEST", name="機種名稱很長很長超過十個字", energy_type="gas")
        cls.color = VehicleColor.objects.create(vehicle_model=cls.model, name="白")
        cls.order = SalesOrder.objects.create(owner_name="測試姓名", owner_phone="0900000000", owner_address="測試地址", owner_id_number="A123456789", vehicle_model=cls.model, color=cls.color, note="備註文字很長超過十二個字元的測試")
        OrderOperationsProfile.objects.update_or_create(order=cls.order, defaults={"actual_disbursement": 987654, "vehicle_cost": 321})

    def setUp(self):
        cache.clear()

    def unlock(self, user=None):
        self.client.force_login(user or self.root)
        return self.client.post(reverse("profit_unlock"), {"password": "Privacy-test-730!", "next": reverse("order_list")})

    def test_root_locked_default_then_password_and_lock(self):
        self.client.force_login(self.root)
        response = self.client.get(reverse("order_list"), {"sort": "profit,owner_name"})
        self.assertNotContains(response, "987,333")
        self.assertEqual(response.context["sort_value"], "owner_name")
        self.assertContains(response, "解鎖後可排序")
        self.assertEqual(self.unlock().status_code, 302)
        response = self.client.get(reverse("order_list"), {"sort": "profit"})
        self.assertContains(response, "987,333")
        self.assertEqual(response.context["sort_value"], "profit")
        self.client.post(reverse("profit_lock"))
        self.assertNotContains(self.client.get(reverse("order_list")), "987,333")

    def test_permission_is_explicit_even_legacy_and_other_superuser(self):
        for user in [self.staff, get_user_model().objects.create_superuser("manager", password="test")]:
            self.client.force_login(user)
            self.assertFalse(AccessPolicy(user).screen("profit"))
            self.assertEqual(self.client.post(reverse("profit_unlock"), {"password": "test"}).status_code, 403)
        ScreenAccessGrant.objects.create(user=self.staff, screen_key="profit", view=True)
        self.assertEqual(self.unlock(self.staff).status_code, 302)
        self.assertContains(self.client.get(reverse("order_list")), "987,333")

    def test_expiration_revoke_regrant_password_and_session_isolation(self):
        grant = ScreenAccessGrant.objects.create(user=self.staff, screen_key="profit", view=True)
        self.unlock(self.staff)
        other = Client(); other.force_login(self.staff)
        self.assertNotContains(other.get(reverse("order_list")), "987,333")
        with patch("sales.services.profit_access.timezone.now", return_value=timezone.now() + timedelta(seconds=301)):
            self.assertNotContains(self.client.get(reverse("order_list")), "987,333")
        grant.delete()
        self.assertNotContains(self.client.get(reverse("order_list")), "987,333")
        ScreenAccessGrant.objects.create(user=self.staff, screen_key="profit", view=True)
        UserAccessState.objects.filter(user=self.staff).update(version=2)
        self.assertNotContains(self.client.get(reverse("order_list")), "987,333")
        self.unlock(self.staff)
        self.staff.set_password("Changed-9382!"); self.staff.save()
        self.assertEqual(self.client.get(reverse("order_list")).status_code, 302)

    def test_wrong_password_throttled_csrf_and_safe_redirect(self):
        self.client.force_login(self.root)
        for _ in range(5):
            self.assertEqual(self.client.post(reverse("profit_unlock"), {"password": "wrong"}).status_code, 400)
        self.assertEqual(self.client.post(reverse("profit_unlock"), {"password": "Privacy-test-730!"}).status_code, 429)
        self.assertNotIn(SESSION_KEY, self.client.session)
        csrf = Client(enforce_csrf_checks=True); csrf.force_login(self.root)
        self.assertEqual(csrf.post(reverse("profit_unlock"), {"password": "Privacy-test-730!"}).status_code, 403)
        self.assertEqual(csrf.post(reverse("profit_lock")).status_code, 403)
        self.assertEqual(self.client.get(reverse("profit_lock")).status_code, 405)
        cache.clear()
        response = self.client.post(reverse("profit_unlock"), {"password": "Privacy-test-730!", "next": "https://evil.example/"})
        self.assertEqual(response.url, reverse("order_list"))
        self.assertIn("no-store", response["Cache-Control"])

    def test_export_and_raw_financial_routes_require_unlock(self):
        self.client.force_login(self.root)
        for route in ["operations_report_export"]:
            response = self.client.get(reverse(route))
            self.assertEqual(response.status_code, 302)
            self.assertIn(reverse("profit_unlock"), response.url)
        self.unlock()
        self.assertEqual(self.client.get(reverse("operations_report_export")).status_code, 200)

    def test_narrow_text_preserves_original_and_column_order(self):
        self.client.force_login(self.root)
        response = self.client.get(reverse("order_list"))
        columns = [item["key"] for item in response.context["sort_columns"] if item["key"] != "number"]
        self.assertEqual(columns, ["established_on", "registration_date", "plate", "owner_name", "machine", "color", "source", "status", "note", "profit"])
        self.assertContains(response, self.order.note)
        self.assertContains(response, "compact-text-narrow")
        mobile_cards = response.content.decode().split('class="order-list order-sort-cards"', 1)[1]
        self.assertIn('class="order-row order-row--detailed"', mobile_cards)
        self.assertGreaterEqual(mobile_cards.count('class="compact-text-narrow"'), 2)
        self.assertNotIn('<a class="order-row', mobile_cards)
        from sales.templatetags.compact_text import compact_value
        self.assertEqual(len(compact_value(self.order.note, 12)["preview"]), 12)
        self.assertEqual(len(compact_value(self.model.name, 10)["preview"]), 10)

    def test_empty_groups_and_releases_and_help_filtered_server_side(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("dashboard"))
        self.assertNotContains(response, 'aria-label="資料維護選單"')
        self.assertNotContains(response, 'href="/reports/"')
        self.assertNotContains(response, "車行帳號管理重整")
        self.assertEqual(self.client.get(reverse("data_maintenance")).status_code, 403)
        self.assertEqual(self.client.get(reverse("catalog")).status_code, 403)
        guide = self.client.get(reverse("user_guide"))
        self.assertContains(guide, "訂單進度與查詢")
        self.assertNotContains(guide, "開通車行帳號")
        self.assertNotContains(guide, "建立新同仁帳號")
        self.assertNotContains(guide, "原廠獎勵與補助")
        for entry in RELEASES:
            for group in entry["changes"]:
                self.assertEqual(len(RELEASE_RULES[(entry["version"], group["kind"])]), len(group["items"]))
        self.assertTrue(release_context(AccessPolicy(self.staff))["release_history"])

    def test_dealer_can_hide_entire_category_and_catalog_permission(self):
        source = SalesSource.objects.create(name="測試車行", source_type="dealer")
        profile = OrderAccountProfile.objects.create(user=self.staff, kind="dealer", source=source,
            can_view_orders=False, can_browse_catalog=False, can_submit_orders=False)
        self.client.force_login(self.staff)
        response = self.client.get(reverse("dashboard"))
        self.assertNotContains(response, 'href="/orders/"')
        self.assertNotContains(response, 'href="/catalog/"')
        self.assertEqual(self.client.get(reverse("order_list")).status_code, 403)
        self.assertEqual(self.client.get(reverse("catalog")).status_code, 403)
        profile.can_browse_catalog = True; profile.save()
        self.assertEqual(self.client.get(reverse("catalog")).status_code, 200)
        self.assertEqual(self.client.get(reverse("order_create")).status_code, 403)
        self.assertContains(self.client.get(reverse("dashboard")), 'href="/catalog/"')

    def test_catalog_dropdown_does_not_include_unpublished(self):
        VehicleCatalogEntry.objects.create(vehicle_model=self.model, published=True)
        hidden = VehicleModel.objects.create(brand="TEST", name="不公開的車款")
        response = self.client.get(reverse("catalog"), {"model": self.model.pk})
        self.assertContains(response, 'name="model"')
        self.assertNotContains(response, 'name="q"')
        self.assertNotContains(response, hidden.name)
        self.assertEqual(response.context["page_obj"].paginator.count, 1)
        self.assertEqual(self.client.get(reverse("catalog"), {"model": "bad"}).context["page_obj"].paginator.count, 0)

    def test_bulk_controls_present_and_new_account_not_prefilled(self):
        self.client.force_login(self.root)
        response = self.client.get(reverse("access_edit", args=[self.staff.pk]))
        self.assertContains(response, 'data-access-bulk="1"')
        self.assertContains(response, "選車下單入口")
        self.assertContains(response, "查看淨利")
        source = SalesSource.objects.create(name="車行", source_type="dealer", code="D001")
        response = self.client.get(reverse("dealer_account_create", args=[source.pk]))
        self.assertFalse(response.context["form"]["username"].value())
        self.assertEqual(response.context["suggested_username"], "D001-01")
        get_user_model().objects.create_user("D001-01")
        self.assertEqual(self.client.get(reverse("dealer_account_create", args=[source.pk])).context["suggested_username"], "D001-02")
