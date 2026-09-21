import tempfile
from decimal import Decimal
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image
from pypdf import PdfReader

from sales.announcement_views import AnnouncementForm
from sales.forms import AccessoryLineForm, PaymentRecordForm, SubsidyDataForm
from sales.models import AnnouncementImage, AnnouncementAttachment, SystemAnnouncement, OrderIntakeAttachment, SalesOrder
from sales.services.operations_sync import sync_order_operations
from sales.services.settlement_cost import apply_order_settlement_cost
from sales.tests import test_order_workspace as workspace_fixtures
from sales.tests import test_order_intake as intake_fixtures


def picture(name="test.png"):
    content = BytesIO()
    Image.new("RGB", (8, 8), "white").save(content, "PNG")
    return SimpleUploadedFile(name, content.getvalue(), content_type="image/png")


class PptRefinementTests(TestCase):
    setUpTestData = classmethod(workspace_fixtures.OrderWorkspaceTests.setUpTestData.__func__)
    operations_data = workspace_fixtures.OrderWorkspaceTests.operations_data
    post = workspace_fixtures.OrderWorkspaceTests.post

    def setUp(self):
        self.client.force_login(self.admin)
        media = tempfile.TemporaryDirectory()
        self.addCleanup(media.cleanup)
        settings = override_settings(MEDIA_ROOT=media.name)
        settings.enable()
        self.addCleanup(settings.disable)

    def test_inline_announcement_keeps_audience_sorts_and_audits(self):
        item = SystemAnnouncement.objects.create(title="舊標題", body="文字", published=True, audience="selected", starts_at=timezone.now())
        item.recipients.add(self.staff)
        first = AnnouncementImage.objects.create(announcement=item, image=picture("one.png"))
        second = AnnouncementImage.objects.create(announcement=item, image=picture("two.png"))
        url = reverse("announcement_detail", args=[item.pk])
        response = self.client.post(url, {"title": "新版", "body": "圖文內容", "expected_version": item.version, "image_order": f"{second.pk},{first.pk}"})
        self.assertEqual(response.status_code, 302, getattr(response, "context", None) and response.context["inline_form"].errors)
        item.refresh_from_db()
        self.assertEqual(item.title, "新版")
        self.assertEqual(item.audience, "selected")
        self.assertEqual(list(item.recipients.all()), [self.staff])
        self.assertTrue(item.published)
        self.assertEqual(list(item.images.values_list("pk", flat=True)), [second.pk, first.pk])
        self.assertEqual(item.revisions.count(), 1)
        stale = self.client.post(url, {"title": "stale", "body": "x", "expected_version": 1, "image_order": f"{first.pk},{second.pk}"})
        self.assertEqual(stale.status_code, 409)
        self.client.force_login(self.staff)
        page = self.client.get(url)
        self.assertNotContains(page, "data-announcement-edit")
        self.assertLess(page.content.index(b'class="announcement-images"'), page.content.index(b'class="announcement-body"'))
        self.assertEqual(self.client.post(url, {"title": "forged"}).status_code, 403)

    def test_attachment_and_image_download_enforce_audience(self):
        item = SystemAnnouncement.objects.create(title="私有", body="x", published=True, audience="selected")
        attachment = AnnouncementAttachment.objects.create(announcement=item, file=SimpleUploadedFile("notes.txt", b"example"), name="notes.txt")
        image = AnnouncementImage.objects.create(announcement=item, image=picture())
        for route, pk, query in (("announcement_attachment", attachment.pk, ""), ("announcement_image", image.pk, "?download=1")):
            self.client.force_login(self.admin)
            response = self.client.get(reverse(route, args=[pk]) + query)
            self.assertEqual(response.status_code, 200)
            self.assertIn("attachment", response["Content-Disposition"])
            response.close()
            self.client.force_login(self.staff)
            self.assertEqual(self.client.get(reverse(route, args=[pk]) + query).status_code, 404)

    def test_announcement_rejects_foreign_image_order_and_unsafe_attachment(self):
        data = {"title": "x", "body": "x", "expected_version": 0, "starts_at": "2026-09-21T10:00", "audience": "all", "image_order": "999"}
        form = AnnouncementForm(data, {"attachments_upload": SimpleUploadedFile("bad.html", b"<script>x</script>", content_type="text/html")})
        self.assertFalse(form.is_valid())

    def test_custom_accessory_requires_price_authority_and_keeps_fee(self):
        data = {"custom_name": "臨時手機架", "quantity": 2, "line_type": "purchase", "amount": 900, "labor_fee": 100}
        form = AccessoryLineForm(data, allow_manual=True)
        self.assertTrue(form.is_valid(), form.errors)
        line = form.save(commit=False)
        self.assertEqual(line.name, "臨時手機架")
        self.assertEqual(line.line_total, 2000)
        denied = AccessoryLineForm(data, allow_manual=False)
        self.assertTrue(denied.is_valid(), denied.errors)
        self.assertTrue(denied.cleaned_data["DELETE"])
        self.assertFalse(denied.instance.name)

    def test_manual_cost_survives_sync(self):
        data = self.operations_data()
        data["operations-vehicle_cost"] = "55000"
        data["operations-change_reason"] = "核對進貨金額"
        response = self.post("order_operations", data)
        self.assertEqual(response.status_code, 200, response.content)
        self.order.refresh_from_db()
        apply_order_settlement_cost(self.order)
        self.order.operations.refresh_from_db()
        self.assertEqual(self.order.operations.vehicle_cost, 55000)
        self.assertTrue(self.order.operations.vehicle_cost_manual)

    def test_receipt_proof_has_authorized_preview_link(self):
        payment = self.order.payment_records.get(system_key='balance')
        payment.proof = picture('receipt.png')
        payment.save()
        response = self.client.get(reverse('order_detail', args=[self.order.pk]))
        url = reverse('protected_media', args=['payment', payment.pk, 'proof'])
        self.assertContains(response, url)
        self.assertContains(response, 'data-preview-name="' + payment.proof.name + '"')
        download = self.client.get(url)
        self.assertEqual(download.status_code, 200)
        download.close()

    def test_new_installment_receivable_and_manual_override(self):
        self.order.cash_receivable_v2 = True
        self.order.payment_type = "installment"
        self.order.plate_insurance_fee = 2600
        self.order.deposit_amount = 600
        self.order.calculated_balance = self.order.calculate_balance()
        self.order.actual_balance = self.order.calculated_balance
        self.order.save()
        sync_order_operations(self.order.pk, update_receivables=True)
        balance = self.order.payment_records.get(system_key="balance")
        self.assertEqual(balance.expected_amount, 2000)
        self.assertEqual(balance.received_amount, 0)
        data = {"expected_amount": "1800", "expected_amount_override_reason": "核定優惠", "received_amount": ""}
        form = PaymentRecordForm(data, instance=balance)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        sync_order_operations(self.order.pk, update_receivables=True)
        balance.refresh_from_db()
        self.assertEqual(balance.expected_amount, 1800)
        self.assertTrue(balance.expected_amount_overridden)

    def test_inline_discount_authority_revision_and_no_finance_side_effects(self):
        before = self.order.operations.actual_disbursement
        response = self.post("order_discount_request", {"mode": "amount", "amount": 1000, "reason": "成交折讓", "_order_revision": self.order.revision})
        self.assertEqual(response.status_code, 200, response.content)
        self.order.refresh_from_db()
        self.assertEqual(self.order.approved_discount_amount, 1000)
        self.assertEqual(self.order.operations.actual_disbursement, before)
        self.assertEqual(self.post("order_discount_request", {"mode": "amount", "amount": 1, "reason": "stale", "_order_revision": -1}).status_code, 409)
        self.client.force_login(self.staff)
        self.assertEqual(self.post("order_discount_request", {}).status_code, 403)

    def test_deposit_edit_updates_balance_without_inventing_receipt(self):
        self.order.cash_receivable_v2 = True
        self.order.save()
        data = self.operations_data()
        deposit = self.order.payment_records.get(system_key="deposit")
        index = next(i for i in range(int(data['payments-TOTAL_FORMS'])) if data.get(f'payments-{i}-id') == str(deposit.pk))
        data[f'payments-{index}-expected_amount'] = '1000'
        data[f'payments-{index}-expected_amount_override_reason'] = '另收訂金'
        response = self.post('order_operations', data)
        self.assertEqual(response.status_code, 200, response.content)
        self.order.refresh_from_db()
        deposit.refresh_from_db()
        self.assertEqual(self.order.actual_balance, 69000)
        self.assertEqual(deposit.received_amount, 0)
        self.assertEqual(self.order.payment_records.get(system_key='balance').expected_amount, 69000)
        from sales.models import OrderChange
        audit = OrderChange.objects.filter(order=self.order).latest('pk')
        self.assertIn('payment_records', audit.changes)

    def test_finance_cannot_delete_system_payment(self):
        data = self.operations_data()
        data['payments-0-DELETE'] = 'on'
        response = self.post('order_operations', data)
        self.assertEqual(response.status_code, 400)

    def test_confirming_lender_receipt_updates_financial_single_source(self):
        self.order.payment_type = 'installment'
        self.order.cash_receivable_v2 = True
        self.order.save()
        data = self.operations_data()
        payment = self.order.payment_records.get(system_key='installment_disbursement')
        index = next(i for i in range(int(data['payments-TOTAL_FORMS'])) if data.get(f'payments-{i}-id') == str(payment.pk))
        data[f'payments-{index}-received_amount'] = '63000'
        data[f'payments-{index}-received_on'] = '2026-09-21'
        data[f'payments-{index}-confirmed'] = 'on'
        response = self.post('order_operations', data)
        self.assertEqual(response.status_code, 200, response.content)
        self.order.operations.refresh_from_db()
        self.assertEqual(self.order.operations.actual_disbursement, 63000)
        self.assertEqual(self.order.operations.payment_disbursement_snapshot['payment_id'], payment.pk)

    def test_same_owner_subsidy_uses_existing_documents_without_copying(self):
        self.order.old_owner_same_as_owner = True
        self.order.id_front = picture("front.png")
        self.order.id_back = picture("back.png")
        self.order.save()
        attachment = OrderIntakeAttachment.objects.create(order=self.order, kind="owner_bankbook", file=picture("bank.png"), name="bank.png", checksum="x", uploaded_by=self.admin)
        evidence = self.order.subsidy_intake_evidence()
        self.assertEqual(set(evidence), {"old_owner_id_front", "old_owner_id_back", "old_owner_bankbook"})
        self.assertIn(str(attachment.pk), evidence["old_owner_bankbook"]["url"])
        form = SubsidyDataForm(instance=self.order)
        self.assertEqual(form["old_owner_name"].value(), self.order.owner_name)
        response = self.client.get(reverse("order_intake_attachment", args=[attachment.pk]) + "?preview=1")
        self.assertEqual(response.status_code, 200)
        self.assertIn("inline", response["Content-Disposition"])
        response.close()

    def test_print_uses_financed_principal_and_removes_description_column(self):
        from sales.services.order_contract_pdf import build_order_contract_pdf
        self.order.payment_type = "installment"
        self.order.actual_balance = Decimal("75000")
        self.order.deposit_amount = Decimal("2000")
        self.order.installment_amount = Decimal("70000")
        pdf = build_order_contract_pdf(self.order)
        text = "\n".join(page.extract_text() for page in PdfReader(BytesIO(pdf)).pages)
        self.assertIn("7,000", text)
        self.assertNotIn("說明\n數量", text)


class IntakeRefinementTests(TestCase):
    setUp = intake_fixtures.OrderIntakeTests.setUp
    image = intake_fixtures.OrderIntakeTests.image
    complete_data = intake_fixtures.OrderIntakeTests.complete_data
    submit = intake_fixtures.OrderIntakeTests.submit

    def test_trade_in_choice_and_optional_bank_documents_survive_creation(self):
        response = self.submit(trade_in_intent="yes", old_owner_same_as_owner="on", owner_bankbook=self.image("bank.png"), old_id_front=self.image("old.png"))
        self.assertEqual(response.status_code, 302, getattr(response, "context", None) and response.context["form"].errors)
        order = SalesOrder.objects.get()
        self.assertTrue(order.cash_receivable_v2)
        self.assertTrue(order.is_trade_in_subsidy)
        self.assertTrue(order.old_owner_same_as_owner)
        self.assertEqual(set(order.intake_attachments.values_list("kind", flat=True)), {"owner_bankbook", "old_id_front"})

    def test_no_trade_in_does_not_check_same_owner(self):
        self.submit(trade_in_intent="no", old_owner_same_as_owner="on")
        order = SalesOrder.objects.get()
        self.assertFalse(order.is_trade_in_subsidy)
        self.assertFalse(order.old_owner_same_as_owner)
