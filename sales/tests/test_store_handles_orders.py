"""1.69.0：現階段訂單都由本店處理——建立人直接接單、代合作車行開單不需公司確認。"""
from django.urls import reverse

from django.test import TestCase

from sales.models import SalesOrder
from sales.tests import test_order_intake as intake_fixtures


class StoreHandlesOrdersTests(TestCase):
    image = intake_fixtures.OrderIntakeTests.image
    complete_data = intake_fixtures.OrderIntakeTests.complete_data
    setUp = intake_fixtures.OrderIntakeTests.setUp

    def submit(self, url_name="order_create", **changes):
        data = self.complete_data()
        data.update(id_front=self.image("front.png"), id_back=self.image("back.png"))
        data.update(changes)
        return self.client.post(reverse(url_name), data)

    def test_creator_accepts_order_immediately(self):
        page = self.client.get(reverse("order_create")).content.decode()
        self.assertNotIn("intake-accept-card", page)
        response = self.submit()
        self.assertEqual(response.status_code, 302, getattr(response, "context", None) and response.context["form"].errors)
        order = SalesOrder.objects.get()
        self.assertEqual(order.status, SalesOrder.Status.ALLOCATION_PENDING)
        self.assertEqual(order.accepted_by, self.user)
        self.assertTrue(order.events.filter(event_type="accepted").exists())

    def test_dealer_source_needs_no_company_confirmation_and_uses_store_company(self):
        self.client.force_login(self.root)
        page = self.client.get(reverse("order_start")).content.decode()
        self.assertNotIn("data-assisted-company", page)
        self.assertNotIn("assisted-companies", page)
        response = self.submit("order_start", source_type="dealer", source=str(self.dealer.pk))
        self.assertEqual(response.status_code, 302, getattr(response, "context", None) and response.context["form"].errors)
        order = SalesOrder.objects.get()
        self.assertEqual(order.source_id, self.dealer.pk)
        self.assertEqual(order.print_company_snapshot["legal_name"], "馭盛國際有限公司")
        self.assertEqual(order.status, SalesOrder.Status.ALLOCATION_PENDING)
        # 送出後的「訂單已成立」頁不再有接單步驟：可直接簽署，或前往這筆訂單／全部訂單。
        done = self.client.get(response.url).content.decode()
        self.assertIn(reverse("order_list"), done)
        self.assertIn(reverse("order_detail", args=[order.pk]), done)

    def test_dealer_account_orders_still_wait_for_store(self):
        self.client.force_login(self.dealer_user)
        response = self.submit()
        self.assertEqual(response.status_code, 302, getattr(response, "context", None) and response.context["form"].errors)
        self.assertEqual(SalesOrder.objects.get().status, SalesOrder.Status.INTAKE_PENDING)

    def test_catalog_entry_offers_other_accessory_to_everyone(self):
        # 1.70.1：清單找不到的配件（例如手機架），從選車頁進來也一律可選「其他」自行填名稱與售價。
        page = self.client.get(reverse("order_start")).content.decode()
        self.assertIn('<option value="other">其他（自行填寫名稱）</option>', page)
        custom = {"accessories-TOTAL_FORMS": "1", "accessories-0-accessory_product": "other",
                  "accessories-0-custom_name": "行車紀錄器", "accessories-0-quantity": "1",
                  "accessories-0-line_type": "purchase", "accessories-0-amount": "2500", "accessories-0-labor_fee": "300"}
        response = self.submit("order_start", **custom)
        self.assertEqual(response.status_code, 302, getattr(response, "context", None) and response.context["form"].errors)
        line = SalesOrder.objects.get().accessories.get()
        self.assertEqual((line.name, line.amount, line.labor_fee), ("行車紀錄器", 2500, 300))

    def test_deposit_field_starts_empty(self):
        # 1.70.2：建立訂單時訂金欄位保持清空，不帶預設值，也不自動帶入配件金額。
        import re
        for name in ("order_start", "order_create"):
            page = self.client.get(reverse(name)).content.decode()
            field = re.search(r'<input[^>]*id="id_deposit_amount"[^>]*>', page).group(0)
            self.assertNotIn("value=", field)
            self.assertIn('placeholder="沒有收訂金請留空"', field)

    def test_only_store_orders_show_signing_step(self):
        # 1.73.2：只有本店訂單需要客人簽訂購單與個資同意書；合作車行、網路平台略過且不顯示。
        from sales.services.order_next_actions import build_order_next_actions
        from sales.services.order_steps import build_order_steps
        self.client.force_login(self.root)
        self.assertEqual(self.submit("order_start").status_code, 302)
        self.assertEqual(self.submit("order_start", source_type="dealer", source=str(self.dealer.pk), _submission_key="").status_code, 302)
        store, dealer = SalesOrder.objects.order_by("pk")
        self.assertTrue(store.needs_customer_signatures)
        self.assertFalse(dealer.needs_customer_signatures)
        store_steps = [step["key"] for step in build_order_steps(store)["step_list"]]
        dealer_steps = build_order_steps(dealer)["step_list"]
        self.assertIn("documents", store_steps)
        self.assertNotIn("documents", [step["key"] for step in dealer_steps])
        self.assertEqual([step["number"] for step in dealer_steps], list(range(1, len(dealer_steps) + 1)))
        actions = build_order_next_actions(dealer)
        self.assertNotIn("documents", [action.key for action in [actions.primary, *actions.secondary] if action])
        page = self.client.get(reverse("order_detail", args=[dealer.pk]), {"created": "1"}).content.decode()
        self.assertNotIn('id="panel-documents"', page)
        self.assertNotIn("簽署與列印文件", page)
        self.assertNotIn('id="print-contract-dialog"', page)
        store_page = self.client.get(reverse("order_detail", args=[store.pk]), {"created": "1"}).content.decode()
        self.assertIn('id="panel-documents"', store_page)
        self.assertIn('id="print-contract-dialog"', store_page)
        done = self.client.get(reverse("order_submitted", args=[dealer.pk])).content.decode()
        self.assertNotIn("這次要怎麼簽", done)
