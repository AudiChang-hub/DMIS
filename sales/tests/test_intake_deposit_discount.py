"""下單時的訂金、總價優惠與車行附加獎勵快照。"""
import uuid
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from sales.models import (
    DealerVehicleRewardItem, DealerVehicleRewardPlan, OrderDraft, OrderEvent, PaymentRecord, SalesOrder,
)
from sales.services.dealer_reward_snapshot import order_dealer_reward_plans
from sales.services.document_signing import contract_terms
from sales.tests import test_order_intake as fixtures


class IntakeFixtures(TestCase):
    """沿用建單測試的車型（售價 79,800）、車行與帳號；內部帳號另有兩筆其他費用共 700 元。"""
    setUp = fixtures.OrderIntakeTests.setUp
    image = fixtures.OrderIntakeTests.image
    complete_data = fixtures.OrderIntakeTests.complete_data
    submit = fixtures.OrderIntakeTests.submit


class IntakeDepositDiscountTests(IntakeFixtures):

    def grant_intake_only(self):
        from sales.access.models import ScreenAccessGrant, UserAccessState
        UserAccessState.objects.update_or_create(user=self.user, defaults={"configured": True})
        ScreenAccessGrant.objects.create(user=self.user, screen_key="order_intake", view=True, operate=True)

    def submit_to(self, route, **changes):
        data = self.complete_data()
        data.update(id_front=self.image("front.png"), id_back=self.image("back.png"), _submission_key=str(uuid.uuid4()))
        data.update(changes)
        return self.client.post(reverse(route), data)

    def assert_created(self, response):
        context = getattr(response, "context", None)
        self.assertEqual(response.status_code, 302, context and context["form"].errors)
        return SalesOrder.objects.latest("pk")

    # ---- 訂金 ----

    def test_reception_mode_shows_and_saves_deposit_like_internal_flow(self):
        self.grant_intake_only()
        page = self.client.get(reverse("order_start"), {"classic": "1"}).content.decode()
        self.assertIn('<div class="subsection deposit-subsection" id="deposit-subsection">', page)
        self.assertIn('name="deposit_amount"', page)
        self.assertNotIn('name="deposit_amount" disabled', page)
        # 其他財務段落仍隱藏。
        self.assertIn('<details class="card" open hidden><summary>店內財務・領牌規費與強制險', page)
        today = timezone.localdate()
        order = self.assert_created(self.submit_to(
            "order_start", deposit_amount="5000", deposit_date=today.isoformat(), deposit_method="transfer",
            registration_plate_fee="999",
        ))
        self.assertEqual((order.deposit_amount, order.deposit_date, order.deposit_method), (5000, today, "transfer"))
        self.assertNotEqual(order.registration_plate_fee, 999)
        self.assertEqual(order.calculated_balance, Decimal("79800") - 5000)
        deposit = PaymentRecord.objects.get(order=order, system_key="deposit")
        # 與內部建單同一路徑：約定訂金成為未確認的收款列，由店內確認實收後才入帳。
        self.assertEqual((deposit.expected_amount, deposit.received_amount, deposit.confirmed), (5000, 0, False))
        self.assertEqual(deposit.payment_method, "匯款")

    def test_dealer_can_enter_deposit_but_not_other_finance(self):
        self.client.force_login(self.dealer_user)
        page = self.client.get(reverse("order_start"), {"classic": "1"})
        self.assertEqual(page.status_code, 200)
        self.assertFalse(page.context["intake_finance_editable"])
        body = page.content.decode()
        self.assertIn('id="deposit-subsection">', body)
        self.assertNotIn('id="deposit-subsection" hidden', body)
        self.assertTrue(page.context["form"].fields["commission_recipient"].disabled)
        order = self.assert_created(self.submit_to(
            "order_start", deposit_amount="3000", deposit_method="cash", vehicle_price="1",
            compulsory_insurance_fee="777", **{"other_fees-0-name": "FORGED", "other_fees-0-amount": "50"},
        ))
        self.assertEqual((order.source, order.deposit_amount, order.vehicle_price), (self.dealer, 3000, 79800))
        self.assertNotEqual(order.compulsory_insurance_fee, 777)
        self.assertFalse(order.other_fees.exists())
        self.assertTrue(PaymentRecord.objects.filter(order=order, system_key="deposit", expected_amount=3000, confirmed=False).exists())

    def test_blank_deposit_is_zero_and_negative_is_rejected(self):
        self.grant_intake_only()
        order = self.assert_created(self.submit_to("order_start", deposit_amount=""))
        self.assertEqual(order.deposit_amount, 0)
        response = self.submit_to("order_start", deposit_amount="-1")
        self.assertEqual(response.status_code, 200)
        self.assertIn("deposit_amount", response.context["form"].errors)

    # ---- 總價優惠 ----

    def test_amount_discount_is_approved_immediately_and_on_contract(self):
        order = self.assert_created(self.submit(
            deposit_amount="2000", intake_discount_mode="amount", intake_discount_amount="1800",
            intake_discount_reason="老客戶回購",
        ))
        self.assertEqual(order.discount_status, SalesOrder.DiscountStatus.APPROVED)
        self.assertEqual((order.approved_discount_amount, order.discount_requested_amount), (1800, 1800))
        self.assertEqual(order.discount_basis_total, 80500)
        self.assertEqual(order.pre_discount_total, 80500)
        self.assertEqual(order.discounted_total, 78700)
        self.assertEqual(order.calculated_balance, 80500 - 2000 - 1800)
        self.assertEqual(order.actual_balance, order.calculated_balance)
        self.assertEqual((order.discount_requested_by, order.discount_decided_by), (self.user.username, self.user.username))
        self.assertEqual((order.discount_reason, order.discount_decision_note), ("老客戶回購", "下單時填寫"))
        self.assertIsNotNone(order.discount_decided_at)
        self.assertEqual(contract_terms(order)["approved_discount_amount"], "1800")
        event = OrderEvent.objects.get(order=order, event_type="discount_decided")
        self.assertIn("減少 1,800 元", event.description)
        # 優惠不經待確認，交車閘門不因折扣卡住。
        self.assertNotIn("折扣", "".join(order.delivery_blockers()))
        # 收支同步：應收尾款已扣除優惠。
        balance = order.payment_records.filter(system_key="balance").first()
        if balance:
            self.assertEqual(balance.expected_amount, order.actual_balance)

    def test_dealer_rate_discount_is_approved_with_dealer_as_actor(self):
        self.client.force_login(self.dealer_user)
        order = self.assert_created(self.submit_to(
            "order_start", intake_discount_mode="rate", intake_discount_rate="9.5",
            intake_discount_amount="99999", intake_discount_reason="展示車",
        ))
        # 79,800 × 0.95 = 75,810；殘留在另一種方式的金額不採用。
        self.assertEqual(order.approved_discount_amount, 3990)
        self.assertEqual(order.discounted_total, 75810)
        self.assertEqual(order.discount_decided_by, self.dealer_user.username)
        self.assertEqual(order.discount_status, SalesOrder.DiscountStatus.APPROVED)
        self.assertIn("9.5 折", OrderEvent.objects.get(order=order, event_type="discount_decided").description)

    def test_invalid_discounts_are_rejected_without_creating_order(self):
        cases = (
            ({"intake_discount_amount": "80501", "intake_discount_reason": "超過總價"}, "intake_discount_amount"),
            ({"intake_discount_amount": "1000", "intake_discount_reason": ""}, "intake_discount_reason"),
            ({"intake_discount_mode": "rate", "intake_discount_rate": "10", "intake_discount_reason": "無效折數"}, "intake_discount_rate"),
            ({"intake_discount_amount": "0", "intake_discount_reason": "零元"}, "intake_discount_amount"),
        )
        for changes, field in cases:
            with self.subTest(field=field, changes=changes):
                response = self.submit(**changes)
                self.assertEqual(response.status_code, 200)
                self.assertIn(field, response.context["form"].errors)
        self.assertFalse(SalesOrder.objects.exists())

    def test_discount_counts_accessories_and_fees_in_total(self):
        from sales.models import AccessoryProduct
        product = AccessoryProduct.objects.create(name="置物箱", sale_price=1500, labor_fee=200)
        extra = {"accessories-0-accessory_product": product.pk, "accessories-0-line_type": "purchase",
                 "accessories-0-quantity": "1", "accessories-0-amount": "1500", "accessories-0-labor_fee": "200"}
        # 總價 80,500 + 1,700 = 82,200；剛好全額優惠可以，超過一元就擋。
        response = self.submit(intake_discount_amount="82201", intake_discount_reason="測試", **extra)
        self.assertEqual(response.status_code, 200, response.context and response.context["formset"].errors)
        self.assertIn("intake_discount_amount", response.context["form"].errors)
        order = self.assert_created(self.submit(intake_discount_amount="82200", intake_discount_reason="測試", **extra))
        self.assertEqual((order.discount_basis_total, order.discounted_total), (82200, 0))

    def test_post_creation_discount_request_still_works(self):
        order = self.assert_created(self.submit(intake_discount_amount="1000", intake_discount_reason="下單優惠"))
        receive = self.client.post(reverse("order_receive", args=[order.pk]))
        self.assertIn(receive.status_code, {200, 302})
        self.client.force_login(self.root)
        response = self.client.post(reverse("order_discount_request", args=[order.pk]),
                                    {"mode": "amount", "amount": "500", "reason": "追加優惠"})
        self.assertEqual(response.status_code, 302)
        order.refresh_from_db()
        self.assertEqual((order.discount_status, order.discount_requested_amount, order.approved_discount_amount),
                         (SalesOrder.DiscountStatus.PENDING, 500, 1000))
        self.assertEqual(order.discount_basis_total, 80500)

    # ---- 草稿 ----

    def test_draft_autosave_and_reload_keep_discount_and_deposit(self):
        self.grant_intake_only()
        result = self.client.post(reverse("intake_draft_save"), {
            "owner_name": "草稿客戶", "deposit_amount": "1200", "deposit_method": "card",
            "intake_discount_mode": "rate", "intake_discount_rate": "9", "intake_discount_reason": "週年慶",
        })
        self.assertEqual(result.status_code, 200)
        draft = OrderDraft.objects.get(pk=result.json()["id"])
        self.assertEqual(
            {key: draft.data.get(key) for key in ("deposit_amount", "intake_discount_mode", "intake_discount_rate", "intake_discount_reason")},
            {"deposit_amount": "1200", "intake_discount_mode": "rate", "intake_discount_rate": "9", "intake_discount_reason": "週年慶"},
        )
        page = self.client.get(reverse("order_start"), {"draft": draft.pk, "classic": "1"})
        form = page.context["form"]
        self.assertEqual(str(form["intake_discount_rate"].value()), "9")
        self.assertEqual(form["intake_discount_reason"].value(), "週年慶")
        self.assertEqual(str(form["deposit_amount"].value()), "1200")
        self.assertContains(page, 'data-intake-discount')


class WizardDiscountTests(IntakeFixtures):
    def wizard_post(self, step, draft=None, action="next", **extra):
        data = {**self.complete_data(), "_wizard_step": step, "_wizard_action": action, "_submission_key": self.key,
                "_id_check": "passed", **extra}
        if draft:
            data.update({"_draft_id": str(draft.pk), "_draft_revision": str(draft.revision)})
        if step == "owner":
            data.update(id_front=self.image("front.png"), id_back=self.image("back.png"))
        return self.client.post(reverse("order_create"), data)

    def test_deposit_step_validates_discount_and_summary_previews_totals(self):
        self.key = str(uuid.uuid4())
        draft = None
        for step in ("vehicle", "accessories", "tradein", "delivery", "owner", "payment"):
            self.assertEqual(self.wizard_post(step, draft).status_code, 302)
            draft = OrderDraft.objects.get()
        too_much = self.wizard_post("deposit", draft, intake_discount_amount="90000", intake_discount_reason="太多")
        self.assertEqual(too_much.status_code, 200)
        self.assertContains(too_much, "優惠須大於零，且不可超過折扣前總價。")
        draft.refresh_from_db()
        self.assertNotIn("deposit", draft.data["_wizard_done"])
        good = {"intake_discount_amount": "2800", "intake_discount_reason": "老客戶", "deposit_amount": "1000"}
        self.assertEqual(self.wizard_post("deposit", draft, **good).status_code, 302)
        draft.refresh_from_db()
        self.assertEqual(draft.data["intake_discount_amount"], "2800")
        page = self.client.get(reverse("order_create"), {"draft": draft.pk, "step": "confirm"}).content.decode()
        summary = page.split("wizard-summary", 1)[1].split("</section>", 1)[0]
        self.assertIn("<dt>優惠前總價</dt><dd>80,500 元</dd>", summary)
        self.assertIn("<dt>總價優惠</dt><dd>−2,800 元，送出即生效</dd>", summary)
        self.assertIn("<dt>優惠後總價</dt><dd>77,700 元</dd>", summary)
        response = self.wizard_post("confirm", draft, action="submit", **good)
        order = SalesOrder.objects.get()
        self.assertEqual(response.status_code, 302)
        self.assertEqual((order.approved_discount_amount, order.discount_status, order.calculated_balance),
                         (2800, SalesOrder.DiscountStatus.APPROVED, 80500 - 2800 - 1000))


class DealerRewardSnapshotTests(IntakeFixtures):
    def make_plan(self, name="機油", quantity=2, **kwargs):
        plan = DealerVehicleRewardPlan.objects.create(
            vehicle_model=self.model, effective_from=timezone.localdate() - timedelta(days=10), **kwargs)
        DealerVehicleRewardItem.objects.create(plan=plan, reward_type="physical", name=name, quantity=quantity, unit="瓶")
        return plan

    def test_snapshot_captured_on_create_and_unaffected_by_master_edits(self):
        plan = self.make_plan()
        self.client.force_login(self.dealer_user)
        response = self.client.post(reverse("order_start"), {
            **self.complete_data(), "id_front": self.image("f.png"), "id_back": self.image("b.png"),
            "_submission_key": str(uuid.uuid4())})
        self.assertEqual(response.status_code, 302)
        order = SalesOrder.objects.get()
        self.assertIsNotNone(order.dealer_reward_snapshot_locked_at)
        self.assertEqual(order.dealer_reward_snapshot["reference_date"], order.order_date.isoformat())
        self.assertEqual([item["label"] for item in order.dealer_reward_snapshot["plans"][0]["items"]], ["機油 2 瓶"])
        item = plan.items.get()
        item.name, item.quantity = "輪胎", 4
        item.save()
        order.refresh_from_db()
        plans = order_dealer_reward_plans(order)
        self.assertEqual(plans[0]["items"][0]["label"], "機油 2 瓶")
        from sales.services.historical_date_change import financial_reference
        later = financial_reference(order, timezone.localdate() + timedelta(days=30))
        self.assertIn("機油 2 瓶", later["實物／紅包／禮券／點數"])

    def test_order_without_plans_snapshots_empty_list_and_legacy_falls_back(self):
        response = self.client.post(reverse("order_create"), {
            **self.complete_data(), "id_front": self.image("f.png"), "id_back": self.image("b.png"),
            "_submission_key": str(uuid.uuid4())})
        self.assertEqual(response.status_code, 302)
        order = SalesOrder.objects.get()
        self.assertEqual(order.dealer_reward_snapshot["plans"], [])
        self.make_plan(name="禮券", quantity=1)
        self.assertEqual(order_dealer_reward_plans(order), [])
        # 舊訂單（無快照）依日期查詢主檔。
        SalesOrder.objects.filter(pk=order.pk).update(dealer_reward_snapshot={}, dealer_reward_snapshot_locked_at=None)
        order.refresh_from_db()
        self.assertEqual(order_dealer_reward_plans(order)[0]["items"][0]["name"], "禮券")

    def test_forced_refresh_follows_new_vehicle_model(self):
        from sales.models import VehicleColor, VehicleModel
        from sales.services.dealer_reward_snapshot import apply_order_dealer_reward_snapshot
        response = self.client.post(reverse("order_create"), {
            **self.complete_data(), "id_front": self.image("f.png"), "id_back": self.image("b.png"),
            "_submission_key": str(uuid.uuid4())})
        self.assertEqual(response.status_code, 302)
        order = SalesOrder.objects.get()
        other = VehicleModel.objects.create(brand="測試", name="150", energy_type=VehicleModel.EnergyType.GAS)
        VehicleColor.objects.create(vehicle_model=other, name="黑")
        DealerVehicleRewardItem.objects.create(
            plan=DealerVehicleRewardPlan.objects.create(vehicle_model=other, effective_from=order.order_date),
            reward_type="cash_gift", name="紅包", quantity=500, unit="元")
        order.vehicle_model = other
        apply_order_dealer_reward_snapshot(order, force=True)
        order.refresh_from_db()
        self.assertEqual(order.dealer_reward_snapshot["plans"][0]["items"][0]["label"], "紅包 500 元")

