import importlib
import uuid

from django.apps import apps
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, Client
from django.urls import reverse

from sales.access.models import ScreenAccessGrant, UserAccessState, UserAccessRevision
from sales.access.services import AccessPolicy
from sales.models import SalesOrder, OrderDraft, OrderIntakeAttachment, InstallmentCompany, InstallmentPlanVersion, InstallmentPlanOption
from sales.tests import test_order_intake as intake_fixtures


class ReceptionEntryTests(TestCase):
    setUp = intake_fixtures.OrderIntakeTests.setUp
    image = intake_fixtures.OrderIntakeTests.image
    complete_data = intake_fixtures.OrderIntakeTests.complete_data

    def grant_intake_only(self):
        UserAccessState.objects.update_or_create(user=self.user, defaults={"configured": True})
        ScreenAccessGrant.objects.create(user=self.user, screen_key="order_intake", view=True, operate=True)

    def submit(self, **changes):
        data = self.complete_data()
        data.update(id_front=self.image("front.png"), id_back=self.image("back.png"))
        data.update(changes)
        return self.client.post(reverse("order_start"), data)

    def test_create_only_can_submit_without_viewing_other_orders(self):
        self.grant_intake_only()
        page = self.client.get(reverse("order_start"))
        self.assertEqual(page.status_code, 200)
        self.assertTrue(page.context["reception_mode"])
        self.assertFalse(page.context["intake_finance_editable"])
        self.assertEqual(self.client.get(reverse("order_list")).status_code, 403)
        self.assertEqual(self.client.get(reverse("order_create")).status_code, 403)
        result = self.submit()
        self.assertEqual(result.status_code, 302, result.context and result.context["form"].errors)
        order = SalesOrder.objects.get()
        self.assertEqual(result.url, reverse("order_submitted", args=[order.pk]))
        receipt = self.client.get(result.url)
        self.assertContains(receipt, order.number)
        self.assertContains(receipt, "再建立一筆")
        self.assertContains(receipt, f'<a class="button" href="{reverse("dashboard")}">回首頁</a>', html=True)
        self.assertNotContains(receipt, "離開接待")
        self.assertNotContains(receipt, "測試車主")
        self.assertNotContains(receipt, "淨利")
        self.assertEqual(self.client.get(reverse("order_detail", args=[order.pk])).status_code, 403)

    def test_reception_forces_public_terms_even_for_admin_and_is_idempotent(self):
        self.client.force_login(self.root)
        key = str(uuid.uuid4())
        result = self.submit(_submission_key=key, vehicle_price="1", deposit_amount="99999", accept_by_me="on",
                             **{"other_fees-0-name": "FORGED-INTERNAL", "other_fees-0-amount": "999"})
        self.assertEqual(result.status_code, 302, result.context and result.context["form"].errors)
        order = SalesOrder.objects.get()
        self.assertEqual((order.vehicle_price, order.deposit_amount, order.status), (79800, 0, "intake_pending"))
        self.assertFalse(order.other_fees.exists())
        repeated = self.submit(_submission_key=key)
        self.assertEqual(repeated.url, result.url)
        self.assertEqual(SalesOrder.objects.count(), 1)
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(result.url).status_code, 404)

    def test_draft_ownership_sanitization_and_legacy_preservation(self):
        self.grant_intake_only()
        other = OrderDraft.objects.create(owner_account=self.root, data={"_reception": True, "owner_name": "別人的客戶"})
        for name in ("order_start", "intake_draft_save"):
            response = (self.client.get(reverse(name), {"draft": other.pk}) if name == "order_start" else
                        self.client.post(reverse(name), {"_draft_id": other.pk}))
            self.assertEqual(response.status_code, 404)
        for name in ("draft_presence", "draft_delete"):
            self.assertEqual(self.client.post(reverse(name, args=[other.pk])).status_code, 404)
        legacy = OrderDraft.objects.create(owner_account=self.user, data={"deposit_amount": "9988"})
        self.assertEqual(self.client.get(reverse("order_start"), {"draft": legacy.pk}).status_code, 409)
        result = self.client.post(reverse("intake_draft_save"), {"owner_name": "本人客戶", "deposit_amount": "8888", "accept_by_me": "on"})
        self.assertEqual(result.status_code, 200)
        draft = OrderDraft.objects.get(pk=result.json()["id"])
        self.assertTrue(draft.data["_reception"])
        self.assertNotIn("deposit_amount", draft.data)
        self.assertNotIn("accept_by_me", draft.data)
        self.assertIn(reverse("order_start"), result.json()["edit_url"])
        self.assertEqual(self.client.get(result.json()["edit_url"]).status_code, 200)
        legacy.refresh_from_db()
        self.assertEqual(legacy.data["deposit_amount"], "9988")

    def test_independent_dealer_submit_without_company_order_visibility(self):
        self.profile.can_view_orders = False
        self.profile.save()
        self.client.force_login(self.dealer_user)
        self.assertEqual(self.client.get(reverse("order_list")).status_code, 403)
        result = self.submit()
        self.assertEqual(result.status_code, 302, result.context and result.context["form"].errors)
        self.assertEqual(self.client.get(result.url).status_code, 200)
        self.profile.can_submit_orders = False
        self.profile.save()
        self.assertEqual(self.client.get(reverse("order_start")).status_code, 403)

    def test_revoke_intake_keeps_query_but_blocks_submission(self):
        self.grant_intake_only()
        ScreenAccessGrant.objects.filter(user=self.user, screen_key="order_intake").update(operate=False)
        ScreenAccessGrant.objects.create(user=self.user, screen_key="orders", view=True, operate=True)
        self.assertEqual(self.client.get(reverse("order_list")).status_code, 200)
        self.assertEqual(self.client.get(reverse("order_start")).status_code, 403)
        self.assertEqual(self.client.post(reverse("order_create"), {}).status_code, 403)
        self.assertEqual(self.client.post(reverse("intake_draft_save"), {}).status_code, 403)

    def test_public_options_exclude_finance_and_order_snapshot(self):
        from django.utils import timezone
        self.client.force_login(self.root)
        company = InstallmentCompany.objects.create(name="測試分期")
        version = InstallmentPlanVersion.objects.create(vehicle_model=self.model, effective_from=timezone.localdate())
        InstallmentPlanOption.objects.create(version=version, company=company, periods=12, monthly_amount=7000,
                                             expected_disbursement_fixed_amount=65432)
        response = self.client.get(reverse("intake_installment_options"), {"vehicle_model": self.model.pk})
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "65432")
        self.assertNotContains(response, "expected_disbursement")
        for name in ("intake_installment_options", "intake_price_options"):
            self.assertEqual(self.client.get(reverse(name), {"vehicle_model": self.model.pk, "order_id": "1"}).status_code, 403)

    def test_csrf_navigation_and_login_prefill(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(client.post(reverse("order_start"), {}).status_code, 403)
        self.assertEqual(client.post(reverse("intake_draft_save"), {}).status_code, 403)
        response = self.client.get(reverse("order_start"), {"model": self.model.pk, "color": self.color.pk})
        self.assertEqual(str(response.context["form"]["color"].value()), str(self.color.pk))
        self.assertNotContains(response, 'aria-label="主要選單"')
        self.assertNotContains(response, 'href="/orders/"')
        self.assertContains(response, f'<a href="{reverse("dashboard")}">首頁</a>', html=True)
        self.assertNotContains(response, "離開接待")
        self.assertContains(response, reverse("intake_draft_save"))
        self.assertContains(response, reverse("intake_installment_options"))
        listing = self.client.get(reverse("order_list"))
        self.assertNotContains(listing, "＋ 建立訂單")

    def test_reception_home_navigation_is_consistent_for_staff_and_dealers(self):
        from sales.models import VehicleCatalogEntry
        VehicleCatalogEntry.objects.create(vehicle_model=self.model, published=True)
        for user in (self.root, self.dealer_user):
            self.client.force_login(user)
            for url in (reverse("catalog"), reverse("catalog_detail", args=[self.model.pk]), reverse("order_start")):
                page = self.client.get(url)
                self.assertEqual(page.status_code, 200)
                body = page.content.decode()
                nav = body.split('aria-label="接待下單">', 1)[1].split("</nav>", 1)[0]
                self.assertLess(nav.index(">首頁</a>"), nav.index(">建立訂單</a>"))
                self.assertContains(page, f'<a class="brand" href="{reverse("dashboard")}">')
                self.assertNotContains(page, 'href="/orders/"')
                self.assertNotContains(page, "離開接待")
            self.assertEqual(self.client.get(reverse("dashboard")).status_code, 200)
        self.client.logout()
        self.assertContains(self.client.get(reverse("catalog")), f'<a class="brand" href="{reverse("catalog")}">')

    def test_grant_migration_is_audited_idempotent_and_does_not_expand_viewers(self):
        UserAccessState.objects.create(user=self.user, configured=True, version=0)
        ScreenAccessGrant.objects.create(user=self.user, screen_key="orders", view=True, operate=True)
        viewer = get_user_model().objects.create_user("viewer-only")
        UserAccessState.objects.create(user=viewer, configured=True)
        ScreenAccessGrant.objects.create(user=viewer, screen_key="orders", view=True)
        migration = importlib.import_module("sales.migrations.0141_order_intake_access")
        schema = type("Schema", (), {"connection": connection})()
        migration.split_intake_access(apps, schema)
        migration.split_intake_access(apps, schema)
        self.assertTrue(AccessPolicy(self.user).route("order_start"))
        self.assertFalse(AccessPolicy(viewer).route("order_start"))
        self.assertEqual(UserAccessRevision.objects.filter(user=self.user).count(), 1)
        self.assertEqual(UserAccessState.objects.get(user=self.user).version, 1)

    def test_own_draft_directory_and_legacy_route_keep_reception_boundary(self):
        self.grant_intake_only()
        mine = OrderDraft.objects.create(owner_account=self.user, data={"_reception": True, "owner_name": "自己的接待"})
        OrderDraft.objects.create(owner_account=self.root, data={"_reception": True, "owner_name": "其他客戶機密"})
        response = self.client.get(reverse("intake_drafts"))
        self.assertContains(response, "自己的接待")
        self.assertNotContains(response, "其他客戶機密")
        self.assertContains(response, reverse("order_start") + f"?draft={mine.pk}")
        self.client.force_login(self.root)
        own = OrderDraft.objects.create(owner_account=self.root, data={"_reception": True})
        page = self.client.get(reverse("order_create"), {"draft": own.pk})
        self.assertTrue(page.context["reception_mode"])
        self.assertFalse(page.context["intake_finance_editable"])
        saved = self.client.post(reverse("draft_save"), {"_draft_id": own.pk, "_draft_revision": own.revision, "deposit_amount": "777"})
        self.assertEqual(saved.status_code, 200)
        own.refresh_from_db()
        self.assertTrue(own.is_reception_draft)
        self.assertNotIn("deposit_amount", own.data)

    def test_reception_draft_delete_returns_to_entry_not_internal_home(self):
        self.grant_intake_only()
        draft = OrderDraft.objects.create(owner_account=self.user, data={"_reception": True})
        response = self.client.post(reverse("draft_delete", args=[draft.pk]), HTTP_ACCEPT="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["redirect_url"], reverse("order_start"))
