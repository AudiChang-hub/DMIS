"""建立訂單：只有本店人員使用，開單者即接單人（使用者 2026-10-16）。"""
import tempfile
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

from sales.access.models import ScreenAccessGrant, UserAccessState
from sales.models import SalesOrder, SalesSource, OrderAccountProfile, OrderDraft, OrderEvent, VehiclePriceVersion, OrderIntakeAttachment
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
        # 只能建立與查本人訂單、沒有訂價與財務權限的店內人員。
        self.clerk = get_user_model().objects.create_user("clerk", password="test-only")
        self.profile = OrderAccountProfile.objects.create(user=self.clerk, order_scope="own")
        UserAccessState.objects.create(user=self.clerk, configured=True)
        ScreenAccessGrant.objects.create(user=self.clerk, screen_key="orders", view=True, operate=True)
        ScreenAccessGrant.objects.create(user=self.clerk, screen_key="order_intake", view=True, operate=True)
        self.root = get_user_model().objects.create_superuser("admin", password="test-only")
        VehiclePriceVersion.objects.create(vehicle_model=self.model, cash_price=79800, effective_from=timezone.localdate())

    def submit(self, **changes):
        data = self.complete_data()
        data.update(id_front=self.image("front.png"), id_back=self.image("back.png"))
        data.update(changes)
        return self.client.post(reverse("order_create"), data)

    def test_creator_accepts_new_order(self):
        response = self.submit()
        self.assertEqual(response.status_code, 302, getattr(response, "context", None) and response.context["form"].errors)
        order = SalesOrder.objects.get()
        self.assertEqual(order.status, "allocation_pending")
        self.assertEqual((order.submitted_by, order.accepted_by), (self.user, self.user))
        self.assertIsNotNone(order.accepted_at)
        self.assertEqual(order.print_company_snapshot['legal_name'], '馭盛國際有限公司')
        self.assertNotEqual(build_order_next_actions(order).primary.key, "receive-order")
        self.assertIn("接單", OrderEvent.objects.get(order=order, event_type="created").description)
        self.assertNotContains(self.client.get(reverse("dashboard")), "?status=intake_pending")
        self.assertNotContains(self.client.get(reverse("order_detail", args=[order.pk])), "由我接單")
        with self.assertRaises(NoReverseMatch):
            reverse("order_receive", args=[order.pk])
        self.assertNotIn("intake_pending", SalesOrder.Status.values)

    def test_restricted_staff_is_also_the_receiver(self):
        self.client.force_login(self.clerk)
        response = self.submit(vehicle_price="1", deposit_amount="99999", commission_recipient=str(self.other_dealer.pk), print_company='999999', print_company_snapshot='{"legal_name":"偽造公司"}')
        self.assertEqual(response.status_code, 302, getattr(response, "context", None) and response.context["form"].errors)
        order = SalesOrder.objects.get()
        self.assertEqual((order.status, order.accepted_by), ("allocation_pending", self.clerk))
        # 可填訂金（客人當場付款），但不能改售價、歸屬或開單公司。
        self.assertEqual((order.vehicle_price, order.deposit_amount), (79800, 99999))
        self.assertFalse(order.commission_recipient_id)
        self.assertEqual(order.print_company_snapshot['legal_name'], '馭盛國際有限公司')

    def test_source_choices_are_store_dealer_platform(self):
        page = self.client.get(reverse("order_create"), {"classic": "1"}).content.decode()
        self.assertNotIn("代合作車行開單", page)
        self.assertNotIn("由我接單", page)
        self.assertNotIn("assisted", page)
        self.assertEqual([label for _value, label in SalesOrder.SourceType.choices], ["本店", "車行", "網路平台"])

    def test_gift_grant_without_pricing_creates_zero_gift(self):
        from sales.models import AccessoryProduct
        grant = ScreenAccessGrant.objects.create(user=self.clerk, screen_key="order_gift", view=True, operate=True)
        product = AccessoryProduct.objects.create(name="贈品測試", sale_price=2100, labor_fee=100)
        self.client.force_login(self.clerk)
        values = {"accessories-0-accessory_product": product.pk, "accessories-0-line_type": "gift", "accessories-0-amount": 2100, "accessories-0-labor_fee": 100}
        response = self.submit(**values)
        self.assertEqual(response.status_code, 302, response.context and response.context['formset'].errors)
        line = SalesOrder.objects.get().accessories.get()
        self.assertEqual((line.line_type, line.amount, line.labor_fee), ("gift", 0, 0))
        grant.delete()
        response = self.submit(**values)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(SalesOrder.objects.count(), 1)

    def test_own_scope_blocks_other_orders_drafts_and_admin_pages(self):
        self.submit()
        other = SalesOrder.objects.get()
        draft = OrderDraft.objects.create(owner_account=self.user)
        self.client.force_login(self.clerk)
        for url in [reverse("order_detail", args=[other.pk]), reverse("order_create") + f"?draft={draft.pk}"]:
            self.assertEqual(self.client.get(url).status_code, 404)
        for name in ["operations_report", "user_management", "settlement_cost_rule_list", "system_integrity_report"]:
            self.assertEqual(self.client.get(reverse(name)).status_code, 403)
        self.assertNotContains(self.client.get(reverse("order_list")), other.number)

    def test_same_submission_key_returns_original_order(self):
        import uuid
        key = str(uuid.uuid4())
        self.client.force_login(self.clerk)
        draft = OrderDraft.objects.create(owner_account=self.clerk)
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

    def test_new_order_can_allocate_and_legacy_model_creation_stays_compatible(self):
        from sales.models import VehicleInventory, Store
        self.submit()
        order = SalesOrder.objects.get()
        store = Store.objects.create(name="驗收庫存店", code="INTAKE")
        vehicle = VehicleInventory.objects.create(vehicle_model=self.model, color=self.color, engine_number="QAINTAKEONLY", ownership_store=store, location_store=store)
        order.allocate(vehicle)
        vehicle.refresh_from_db()
        self.assertNotEqual(vehicle.status, "available")
        legacy = SalesOrder.objects.create(vehicle_model=self.model, color=self.color, owner_name="舊單", owner_id_number="A123456789", status=SalesOrder.Status.DRAFT)
        legacy.save()
        legacy.refresh_from_db()
        self.assertEqual(legacy.status, SalesOrder.Status.ALLOCATION_PENDING)
        self.assertIsNone(legacy.accepted_at)

    def test_installment_public_payload_and_amount_tampering(self):
        from sales.models import InstallmentCompany, InstallmentPlanVersion, InstallmentPlanOption
        company = InstallmentCompany.objects.create(name="測試分期")
        version = InstallmentPlanVersion.objects.create(vehicle_model=self.model, effective_from=timezone.localdate())
        InstallmentPlanOption.objects.create(version=version, company=company, periods=24, monthly_amount=3500, opening_fee=500)
        self.client.force_login(self.clerk)
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
        draft = OrderDraft.objects.create(owner_account=self.clerk)
        save_intake_uploads(self.clerk, [("supplement", self.image("first.png")), ("supplement", self.image("duplicate.png"))], draft=draft)
        self.assertEqual(draft.intake_attachments.count(), 1)
        attachment = draft.intake_attachments.get()
        storage, name = attachment.file.storage, attachment.file.name
        other = OrderDraft.objects.create(owner_account=self.user)
        save_intake_uploads(self.user, [], draft=other, remove_ids=[str(attachment.pk)])
        self.assertTrue(draft.intake_attachments.exists())
        with self.captureOnCommitCallbacks(execute=True):
            save_intake_uploads(self.clerk, [], draft=draft, remove_ids=[str(attachment.pk)])
        self.assertFalse(storage.exists(name))

    def test_intake_attachment_follows_order_scope(self):
        self.client.force_login(self.clerk)
        response = self.submit(supplement_documents=[self.image("extra.png")])
        self.assertEqual(response.status_code, 302, response.context and response.context["form"].errors)
        attachment = OrderIntakeAttachment.objects.get()
        download = self.client.get(reverse("order_intake_attachment", args=[attachment.pk]))
        self.assertEqual(download.status_code, 200)
        # 透過 Django test client 的 closing_iterator_wrapper 收尾，避免
        # 直接 response.close() 觸發 request_finished 而關閉測試中的 PG 交易。
        self.assertTrue(b"".join(download.streaming_content).startswith(b"\x89PNG"))
        other = get_user_model().objects.create_user("other-clerk", password="test-only")
        OrderAccountProfile.objects.create(user=other, order_scope="own")
        UserAccessState.objects.create(user=other, configured=True)
        ScreenAccessGrant.objects.create(user=other, screen_key="orders", view=True, operate=True)
        ScreenAccessGrant.objects.create(user=other, screen_key="order_intake", view=True, operate=True)
        self.client.force_login(other)
        self.assertEqual(self.client.get(reverse("order_intake_attachment", args=[attachment.pk])).status_code, 404)

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
        url = reverse("order_account_scope", args=[self.clerk.pk])
        self.assertEqual(self.client.post(url, {}).status_code, 403)
        self.client.force_login(self.root)
        self.assertEqual(self.client.post(url, {"source": source.pk, "order_scope": "all", "expected_revision": 0}).status_code, 302)
        response = self.client.post(url, {"source": "", "order_scope": "own", "expected_revision": 0})
        self.assertContains(response, "已被其他視窗更新")
        self.profile.refresh_from_db()
        self.assertEqual((self.profile.source, self.profile.order_scope), (source, "all"))
        self.assertEqual(UserAccountAuditLog.objects.filter(description="修改預設店別與訂單資料範圍").count(), 1)
        page = self.client.get(url).content.decode()
        self.assertNotIn("下單身分", page)
        self.assertNotIn("所屬車行的訂單", page)
        draft = OrderDraft.objects.create(owner_account=self.root, data={"source_type": "dealer", "source": str(self.dealer.pk)})
        page = self.client.get(reverse("order_create"), {"draft": str(draft.pk)})
        self.assertEqual(str(page.context["form"].initial["source"]), str(self.dealer.pk))
        new = self.client.get(reverse("order_create"))
        self.assertEqual(new.context["form"].initial["source"], source.pk)

    def test_finance_revocation_and_bad_draft_identifier(self):
        self.submit()
        order = SalesOrder.objects.get()
        UserAccessState.objects.create(user=self.user, configured=True)
        ScreenAccessGrant.objects.create(user=self.user, screen_key="orders", view=True, operate=True)
        self.assertEqual(self.client.post(reverse("order_edit", args=[order.pk]), {}).status_code, 403)
        page = self.client.get(reverse("order_detail", args=[order.pk]), {"tab": "order"})
        # 1.82.0：沒有修改權限時訂單頁只顯示唯讀摘要，不放訂單表單。
        self.assertFalse(page.context.get("inline_order_form"))
        self.assertNotContains(page, 'id="order-form"')
        self.client.force_login(self.clerk)
        self.assertEqual(self.client.get(reverse("order_create"), {"draft": "not-a-uuid"}).status_code, 404)
        self.assertEqual(self.client.post(reverse("logout")).status_code, 302)

    def test_draft_owner_and_attachment_survive_submission(self):
        self.client.force_login(self.clerk)
        draft_response = self.client.post(reverse("draft_save"), {"owner_name": "draft", "supplement_documents": self.image("extra.png")})
        self.assertEqual(draft_response.status_code, 200)
        draft = OrderDraft.objects.get()
        self.assertEqual(draft.owner_account, self.clerk)
        self.assertEqual(draft.intake_attachments.count(), 1)
        self.assertEqual(self.submit(_draft_id=str(draft.pk), _draft_revision=str(draft.revision)).status_code, 302)
        self.assertEqual(SalesOrder.objects.get().intake_attachments.count(), 1)
        self.assertFalse(OrderDraft.objects.exists())

    def test_autosave_cannot_smuggle_finance_or_old_accept_flag(self):
        self.client.force_login(self.clerk)
        response = self.client.post(reverse("draft_save"), {"source_type": "dealer", "source": str(self.other_dealer.pk), "vehicle_price": "1", "accept_by_me": "on", "other_fees-0-amount": "999", "note": "客戶需求"})
        self.assertEqual(response.status_code, 200)
        data = OrderDraft.objects.get().data
        self.assertNotIn("vehicle_price", data)
        self.assertNotIn("accept_by_me", data)
        self.assertNotIn("other_fees-0-amount", data)
        self.assertEqual((data["source_type"], data["source"], data["note"]), ("dealer", str(self.other_dealer.pk), "客戶需求"))
