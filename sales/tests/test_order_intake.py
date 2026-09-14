import tempfile
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase, Client, TransactionTestCase, override_settings, skipUnlessDBFeature
from django.urls import reverse
from django.utils import timezone

from sales.models import SalesOrder, SalesSource, OrderAccountProfile, OrderDraft, OrderEvent, VehiclePriceVersion, OrderIntakeAttachment
from sales.services.order_intake import receive_order, scoped_orders
from sales.services.order_next_actions import build_order_next_actions
from . import test_drafts as fixtures


class OrderIntakeTests(TestCase):
    image = fixtures.OrderDraftTests.image
    complete_data = fixtures.OrderDraftTests.complete_data

    def setUp(self):
        fixtures.OrderDraftTests.setUp(self)
        self.media = tempfile.TemporaryDirectory()
        self.addCleanup(self.media.cleanup)
        self.override = override_settings(MEDIA_ROOT=self.media.name)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.dealer = SalesSource.objects.create(name="甲車行", source_type="dealer")
        self.other_dealer = SalesSource.objects.create(name="乙車行", source_type="dealer")
        self.dealer_user = get_user_model().objects.create_user("dealer-a", password="test-only")
        self.profile = OrderAccountProfile.objects.create(user=self.dealer_user, kind="dealer", source=self.dealer)
        self.root = get_user_model().objects.create_superuser("admin", password="test-only")
        VehiclePriceVersion.objects.create(vehicle_model=self.model, cash_price=79800, effective_from=timezone.localdate())

    def submit(self, **changes):
        data = self.complete_data()
        data.update(id_front=self.image("front.png"), id_back=self.image("back.png"))
        data.update(changes)
        return self.client.post(reverse("order_create"), data)

    def test_new_order_waits_and_receive_records_actor_once(self):
        response = self.submit()
        self.assertEqual(response.status_code, 302, getattr(response, "context", None) and response.context["form"].errors)
        order = SalesOrder.objects.get()
        self.assertEqual(order.status, "intake_pending")
        self.assertEqual(order.submitted_by, self.user)
        self.assertEqual(build_order_next_actions(order).primary.key, "receive-order")
        self.assertContains(self.client.get(reverse("dashboard")), "待接單工作：1 筆")
        receive_order(self.user, order.pk)
        order.refresh_from_db()
        self.assertEqual(order.status, "allocation_pending")
        self.assertEqual(order.accepted_by, self.user)
        self.assertIsNotNone(order.accepted_at)
        with self.assertRaises(ValidationError):
            receive_order(self.root, order.pk)
        self.assertEqual(OrderEvent.objects.filter(event_type="accepted").count(), 1)

    def test_internal_explicit_self_accept_and_dealer_cannot(self):
        self.assertEqual(self.submit(accept_by_me="on").status_code, 302)
        self.assertEqual(SalesOrder.objects.get().accepted_by, self.user)
        self.client.force_login(self.dealer_user)
        response = self.submit(accept_by_me="on", source_type="store", source="", vehicle_price="1", deposit_amount="99999", commission_recipient=str(self.other_dealer.pk))
        self.assertEqual(response.status_code, 302, getattr(response, "context", None) and response.context["form"].errors)
        order = SalesOrder.objects.latest("pk")
        self.assertEqual((order.status, order.source, order.vehicle_price, order.deposit_amount), ("intake_pending", self.dealer, 79800, 0))
        self.assertFalse(order.accepted_at)
        self.assertFalse(order.commission_recipient_id)
        self.assertEqual(order.other_fees.count(), 0)
        self.assertEqual(self.client.post(reverse("order_receive", args=[order.pk])).status_code, 403)

    def test_dealer_scope_blocks_details_drafts_exports_admin_and_costs(self):
        self.submit()
        internal = SalesOrder.objects.get()
        draft = OrderDraft.objects.create(owner_account=self.user)
        self.client.force_login(self.dealer_user)
        for url in [reverse("order_detail", args=[internal.pk]), reverse("order_create") + f"?draft={draft.pk}"]:
            self.assertEqual(self.client.get(url).status_code, 404)
        for name in ["operations_report", "user_management", "settlement_cost_rule_list", "system_integrity_report"]:
            self.assertEqual(self.client.get(reverse(name)).status_code, 403)
        self.assertNotContains(self.client.get(reverse("order_list")), internal.number)
        self.assertEqual(self.client.get(reverse("vehicle_price_options") + f"?vehicle_model={self.model.pk}&order_id={internal.pk}").status_code, 403)
        self.assertEqual(self.client.get(reverse("installment_plan_options") + f"?vehicle_model={self.model.pk}&order_id={internal.pk}").status_code, 403)

    def test_dealer_readonly_projection_and_attachments(self):
        self.client.force_login(self.dealer_user)
        response = self.submit(supplement_documents=[self.image("extra.png")])
        self.assertEqual(response.status_code, 302, response.context and response.context["form"].errors)
        order = SalesOrder.objects.get()
        page = self.client.get(reverse("order_detail", args=[order.pk]))
        self.assertContains(page, "待接單")
        self.assertNotContains(page, "淨利")
        attachment = OrderIntakeAttachment.objects.get()
        download = self.client.get(reverse("order_intake_attachment", args=[attachment.pk]))
        self.assertEqual(download.status_code, 200)
        download.close()
        self.profile.source = self.other_dealer
        self.profile.save()
        self.assertEqual(self.client.get(reverse("order_intake_attachment", args=[attachment.pk])).status_code, 404)

    def test_admin_default_source_is_internal_and_locked_against_dealer_role(self):
        source = SalesSource.objects.create(name="馭盛", source_type="store")
        profile = OrderAccountProfile.objects.create(user=self.root, kind="internal", source=source)
        self.client.force_login(self.root)
        page = self.client.get(reverse("order_create"))
        self.assertEqual(page.context["form"].initial["source"], source.pk)
        self.assertTrue(page.context["intake_finance_editable"])
        profile.kind = "dealer"
        profile.source = self.dealer
        with self.assertRaises(ValidationError):
            profile.full_clean()

    def test_receive_requires_post_and_csrf(self):
        self.submit()
        order = SalesOrder.objects.get()
        self.assertEqual(self.client.get(reverse("order_receive", args=[order.pk])).status_code, 405)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.root)
        self.assertEqual(client.post(reverse("order_receive", args=[order.pk])).status_code, 403)

    def test_same_submission_key_returns_original_order(self):
        import uuid
        key = str(uuid.uuid4())
        self.client.force_login(self.dealer_user)
        draft = OrderDraft.objects.create(owner_account=self.dealer_user)
        first = self.submit(_submission_key=key, _draft_id=str(draft.pk))
        second = self.submit(_submission_key=key, _draft_id=str(draft.pk))
        self.assertEqual((first.status_code, second.status_code), (302, 302))
        self.assertEqual(SalesOrder.objects.count(), 1)
        self.assertIn(str(SalesOrder.objects.get().pk), second.url)

    def test_old_orders_unchanged_and_prefill_validates_color(self):
        page = self.client.get(reverse("order_create") + f"?model={self.model.pk}&color={self.color.pk}")
        self.assertEqual(page.context["form"].initial["vehicle_model"], self.model.pk)
        self.assertEqual(str(page.context["form"].initial["color"]), str(self.color.pk))
        self.assertFalse(OrderDraft.objects.exists())

    def test_pending_cannot_allocate_and_legacy_model_creation_stays_compatible(self):
        from sales.models import VehicleInventory, Store
        self.submit()
        order = SalesOrder.objects.get()
        store = Store.objects.create(name="驗收庫存店", code="INTAKE")
        vehicle = VehicleInventory.objects.create(vehicle_model=self.model, color=self.color, engine_number="QAINTAKEONLY", ownership_store=store, location_store=store)
        with self.assertRaisesMessage(ValidationError, "請先接單"):
            order.allocate(vehicle)
        vehicle.refresh_from_db()
        self.assertEqual(vehicle.status, "available")
        order.status = SalesOrder.Status.DRAFT
        order.save()
        order.refresh_from_db()
        self.assertEqual(order.status, SalesOrder.Status.ALLOCATION_PENDING)
        self.assertIsNone(order.accepted_at)

    def test_installment_public_payload_and_amount_tampering(self):
        from sales.models import InstallmentCompany, InstallmentPlanVersion, InstallmentPlanOption
        company = InstallmentCompany.objects.create(name="測試分期")
        version = InstallmentPlanVersion.objects.create(vehicle_model=self.model, effective_from=timezone.localdate())
        InstallmentPlanOption.objects.create(version=version, company=company, periods=24, monthly_amount=3500, opening_fee=500)
        self.client.force_login(self.dealer_user)
        option = self.client.get(reverse("installment_plan_options"), {"vehicle_model": self.model.pk}).json()["options"][0]
        self.assertNotIn("actual_disbursement", option)
        self.assertEqual(set(option) - {"id", "periods", "monthly_amount", "company_id", "company", "customer_service_phone", "opening_fee", "effective_from", "effective_to"}, set())
        response = self.submit(payment_type="installment", installment_company=company.name, installment_periods="24", installment_monthly="1", installment_opening_fee="1")
        self.assertEqual(response.status_code, 302, response.context and response.context["form"].errors)
        order = SalesOrder.objects.get()
        self.assertEqual((order.installment_monthly, order.installment_opening_fee), (3500, 500))
        response = self.submit(payment_type="installment", installment_company="偽造方案", installment_periods="999")
        self.assertEqual(response.status_code, 200)
        self.assertIn("installment_periods", response.context["form"].errors)
        self.assertEqual(SalesOrder.objects.count(), 1)

    def test_uploads_deduplicate_and_removal_is_parent_scoped(self):
        from sales.services.order_intake import save_intake_uploads
        draft = OrderDraft.objects.create(owner_account=self.dealer_user)
        save_intake_uploads(self.dealer_user, [("supplement", self.image("first.png")), ("supplement", self.image("duplicate.png"))], draft=draft)
        self.assertEqual(draft.intake_attachments.count(), 1)
        attachment = draft.intake_attachments.get()
        storage, name = attachment.file.storage, attachment.file.name
        other = OrderDraft.objects.create(owner_account=self.user)
        save_intake_uploads(self.user, [], draft=other, remove_ids=[str(attachment.pk)])
        self.assertTrue(draft.intake_attachments.exists())
        with self.captureOnCommitCallbacks(execute=True):
            save_intake_uploads(self.dealer_user, [], draft=draft, remove_ids=[str(attachment.pk)])
        self.assertFalse(storage.exists(name))

    def test_invalid_upload_and_capacity_error_do_not_create_order(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        bad = SimpleUploadedFile("bad.pdf", b"not a PDF", content_type="application/pdf")
        self.assertEqual(self.submit(supplement_documents=bad).status_code, 200)
        self.assertFalse(SalesOrder.objects.exists())
        draft = OrderDraft.objects.create(owner_account=self.user)
        for index in range(10):
            OrderIntakeAttachment.objects.create(draft=draft, kind="supplement", checksum=str(index), file=f"nonexistent-test-{index}.png", name="test", uploaded_by=self.user)
        response = self.submit(_draft_id=str(draft.pk), supplement_documents=self.image("eleventh.png"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("最多 10 個", str(response.context["form"].errors))
        self.assertFalse(SalesOrder.objects.exists())

    def test_scope_admin_only_revision_and_default_does_not_overwrite_draft(self):
        from sales.models import UserAccountAuditLog
        source = SalesSource.objects.create(name="馭盛", source_type="store")
        OrderAccountProfile.objects.create(user=self.root, source=source)
        url = reverse("order_account_scope", args=[self.dealer_user.pk])
        self.assertEqual(self.client.post(url, {}).status_code, 403)
        self.client.force_login(self.root)
        self.assertEqual(self.client.post(url, {"kind": "dealer", "source": self.other_dealer.pk, "expected_revision": 0}).status_code, 302)
        response = self.client.post(url, {"kind": "dealer", "source": self.dealer.pk, "expected_revision": 0})
        self.assertContains(response, "已被其他視窗更新")
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.source, self.other_dealer)
        self.assertEqual(UserAccountAuditLog.objects.filter(description="修改下單身分與所屬通路").count(), 1)
        draft = OrderDraft.objects.create(owner_account=self.root, data={"source_type": "dealer", "source": str(self.dealer.pk)})
        page = self.client.get(reverse("order_create"), {"draft": str(draft.pk)})
        self.assertEqual(str(page.context["form"].initial["source"]), str(self.dealer.pk))

    def test_finance_revocation_and_bad_draft_identifier(self):
        from sales.models import ScreenAccessGrant, UserAccessState
        self.submit()
        order = SalesOrder.objects.get()
        UserAccessState.objects.create(user=self.user, configured=True)
        ScreenAccessGrant.objects.create(user=self.user, screen_key="orders", view=True, operate=True)
        self.assertEqual(self.client.post(reverse("order_edit", args=[order.pk]), {}).status_code, 403)
        page = self.client.get(reverse("order_edit", args=[order.pk]))
        self.assertTrue(page.context["screen_read_only"])
        self.client.force_login(self.dealer_user)
        self.assertEqual(self.client.get(reverse("order_create"), {"draft": "not-a-uuid"}).status_code, 404)
        self.profile.source.active = False
        self.profile.source.save()
        self.assertEqual(self.client.get(reverse("order_create")).status_code, 403)
        self.assertEqual(self.client.post(reverse("logout")).status_code, 302)

    def test_default_migration_is_repeatable_and_preserves_account_settings(self):
        from importlib import import_module
        from types import SimpleNamespace
        from django.apps import apps
        from django.db import connection
        from sales.models import ScreenAccessGrant
        ScreenAccessGrant.objects.create(user=self.user, screen_key="work", view=True, operate=True)
        defaults = import_module("sales.migrations.0135_intake_account_defaults").defaults
        for _ in range(2):
            defaults(apps, SimpleNamespace(connection=connection))
        profile = OrderAccountProfile.objects.get(user=self.root)
        self.assertEqual((profile.kind, profile.source.name, profile.source.source_type), ("internal", "馭盛", "store"))
        self.assertEqual(ScreenAccessGrant.objects.filter(user=self.user, screen_key="order_finance").count(), 1)
        profile.source = self.other_dealer
        profile.save()
        defaults(apps, SimpleNamespace(connection=connection))
        profile.refresh_from_db()
        self.assertEqual(profile.source, self.other_dealer)

    def test_draft_owner_and_attachment_survive_submission(self):
        self.client.force_login(self.dealer_user)
        draft_response = self.client.post(reverse("draft_save"), {"owner_name": "draft", "supplement_documents": self.image("extra.png")})
        self.assertEqual(draft_response.status_code, 200)
        draft = OrderDraft.objects.get()
        self.assertEqual(draft.owner_account, self.dealer_user)
        self.assertEqual(draft.intake_attachments.count(), 1)
        self.assertEqual(self.submit(_draft_id=str(draft.pk), _draft_revision=str(draft.revision)).status_code, 302)
        self.assertEqual(SalesOrder.objects.get().intake_attachments.count(), 1)
        self.assertFalse(OrderDraft.objects.exists())

    def test_dealer_autosave_cannot_smuggle_finance_into_internal_form(self):
        self.client.force_login(self.dealer_user)
        response = self.client.post(reverse("draft_save"), {"source_type": "store", "source": str(self.other_dealer.pk), "vehicle_price": "1", "accept_by_me": "on", "other_fees-0-amount": "999", "note": "客戶需求"})
        self.assertEqual(response.status_code, 200)
        data = OrderDraft.objects.get().data
        self.assertNotIn("vehicle_price", data)
        self.assertNotIn("accept_by_me", data)
        self.assertNotIn("other_fees-0-amount", data)
        self.assertEqual((data["source_type"], data["source"], data["note"]), ("dealer", str(self.dealer.pk), "客戶需求"))


class IntakeConcurrencyTests(TransactionTestCase):
    @skipUnlessDBFeature("has_select_for_update")
    def test_only_one_staff_member_can_receive(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from django.db import close_old_connections
        from sales.models import VehicleModel, VehicleColor
        model = VehicleModel.objects.create(brand="接單測試", name="QA", energy_type="gas")
        color = VehicleColor.objects.create(vehicle_model=model, name="白")
        order = SalesOrder.objects.create(vehicle_model=model, color=color, owner_name="合成資料", owner_phone="0900000000", owner_address="合成地址", owner_id_number="A123456789", status="intake_pending")
        users = [get_user_model().objects.create_user(f"receiver-{i}") for i in range(2)]
        barrier = Barrier(2, timeout=10)

        def receive(user_id):
            close_old_connections()
            try:
                user = get_user_model().objects.get(pk=user_id)
                from django.db import connection
                with connection.cursor() as cursor:
                    cursor.execute("SET statement_timeout = '10s'")
                barrier.wait()
                try:
                    receive_order(user, order.pk)
                    return "accepted"
                except ValidationError:
                    return "already-accepted"
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(receive, [user.pk for user in users]))
        self.assertCountEqual(results, ["accepted", "already-accepted"])
        self.assertEqual(order.events.filter(event_type="accepted").count(), 1)
