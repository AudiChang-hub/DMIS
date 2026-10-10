import tempfile
import uuid

from django.test import TestCase, override_settings
from django.urls import reverse

from sales.models import OrderDraft, OrderEvent, SalesOrder
from sales.services import order_wizard as wizard
from sales.tests import test_drafts, test_reception_entry

MEDIA = tempfile.mkdtemp()


@override_settings(MEDIA_ROOT=MEDIA)
class OrderWizardTests(TestCase):
    setUp = test_drafts.OrderDraftTests.setUp
    image = test_drafts.OrderDraftTests.image
    complete_data = test_drafts.OrderDraftTests.complete_data

    def post(self, step, action="next", draft=None, files=True, **extra):
        data = {**self.complete_data(), "_wizard_step": step, "_submission_key": self.key, **extra}
        if action == "goto":
            data["_wizard_goto"] = extra.get("_wizard_goto", "vehicle")
        else:
            data["_wizard_action"] = action
        if draft:
            data.update({"_draft_id": str(draft.pk), "_draft_revision": str(draft.revision)})
        if files and step == "owner":
            data.update({"id_front": self.image("front.png"), "id_back": self.image("back.png")})
        return self.client.post(reverse("order_create"), data)

    def draft(self):
        return OrderDraft.objects.get()

    def walk_to(self, last, **owner_extra):
        self.key = getattr(self, "key", str(uuid.uuid4()))
        draft = None
        for step in ("vehicle", "accessories", "tradein", "delivery", "owner", "payment", "deposit", "confirm"):
            if step == last:
                return draft
            # 每一步都會送出整張表單，證件檢查結果在車主步驟之後持續帶著。
            extra = owner_extra if step in {"owner", "payment", "deposit"} else {}
            response = self.post(step, draft=draft, **extra)
            self.assertEqual(response.status_code, 302, response.content.decode()[:300])
            draft = self.draft()
        return draft

    def setUpKey(self):
        self.key = str(uuid.uuid4())

    def test_first_step_and_classic_fallback(self):
        page = self.client.get(reverse("order_create")).content.decode()
        self.assertIn("訂單精靈・第 1／8 步", page)
        self.assertIn('data-wizard-panel="vehicle"', page)
        self.assertIn('data-wizard-panel="owner" hidden', page)
        self.assertIn('value="next"', page)
        self.assertNotIn("確認並建立訂單", page)
        # 證件辨識有結果前，人工核對與車主步驟的下一步都鎖住；人工確認框只在辨識未通過時出現。
        self.assertIn('id="id-verify-hint" hidden', page)
        self.assertIn('id="id-manual-check" hidden', page)
        self.assertIn("function updateVerifyLock", page)
        # 自然人未勾「已人工核對證件」也不能前往下一步。
        self.assertIn('next.disabled = needsId && (!ocrReady || !verified)', page)
        # 訂金獨立成段；分期預設以配件金額當訂金。
        self.assertIn('id="deposit-subsection"', page)
        self.assertIn('name="_deposit_auto"', page)
        self.assertIn("function accessoryPurchaseTotal", page)
        classic = self.client.get(reverse("order_create"), {"classic": "1"}).content.decode()
        self.assertIn("建立新訂單", classic)
        self.assertNotIn("wizard-bar", classic)

    def test_next_saves_draft_and_cannot_skip_ahead(self):
        self.setUpKey()
        response = self.post("vehicle", vehicle_model="")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "這一步還有資料需要處理")
        draft = self.draft()
        self.assertEqual(draft.data.get("_wizard_done"), None)
        # 後面步驟的錯誤（例如車主）不在第一步顯示。
        self.assertNotContains(response, "請對照證件並確認資料正確")

        response = self.post("vehicle", draft=draft)
        draft.refresh_from_db()
        self.assertRedirects(response, f"{reverse('order_create')}?draft={draft.pk}&step=accessories", fetch_redirect_response=False)
        self.assertEqual(draft.data["_wizard_done"], ["vehicle"])
        skipped = self.client.get(reverse("order_create"), {"draft": draft.pk, "step": "payment"})
        self.assertRedirects(skipped, f"{reverse('order_create')}?draft={draft.pk}&step=accessories", fetch_redirect_response=False)
        # 自動儲存不能清掉伺服器記錄的進度，也不能由前端偽造。
        self.client.post(reverse("draft_save"), {**self.complete_data(), "_draft_id": str(draft.pk),
                                                 "_draft_revision": str(draft.revision), "_wizard_done": "payment"})
        draft.refresh_from_db()
        self.assertEqual(draft.data["_wizard_done"], ["vehicle"])

    def test_owner_step_requires_passed_identity_check_or_manual_confirmation(self):
        draft = self.walk_to("owner")
        response = self.post("owner", draft=draft)
        self.assertContains(response, "證件尚未完成自動辨識")
        response = self.post("owner", draft=draft, _id_check="failed", _id_check_error="正面照片看起來是健保卡，請改拍身分證或居留證。")
        self.assertContains(response, "證件自動辨識未通過：正面照片看起來是健保卡")
        draft.refresh_from_db()
        self.assertTrue(draft.id_front)
        self.assertNotIn("owner", draft.data["_wizard_done"])
        # 辨識通過但未勾「已人工核對證件」仍不能前往下一步。
        response = self.post("owner", draft=draft, files=False, _id_check="passed", id_verified="")
        self.assertContains(response, "勾選「已人工核對證件」後才能前往下一步")
        response = self.post("owner", draft=draft, files=False, _id_check="passed")
        self.assertEqual(response.status_code, 302)
        draft.refresh_from_db()
        self.assertEqual(draft.data["_wizard_done"], ["vehicle", "accessories", "tradein", "delivery", "owner"])

    def test_confirm_summary_and_submit_records_manual_identity_check(self):
        draft = self.walk_to("confirm", _id_check="failed", _id_check_error="反面照片看不出是身分證反面", _id_manual_confirmed="on")
        page = self.client.get(reverse("order_create"), {"draft": draft.pk, "step": "confirm"}).content.decode()
        self.assertIn("請核對整張訂單", page)
        summary = page.split("wizard-summary", 1)[1].split("</section>", 1)[0]
        # 車型只列品牌／車種／型號／年份，車色只列顏色；訂金一律列出，並提示建立後簽署。
        self.assertIn("<dt>車型</dt><dd>測試／125</dd>", summary)
        self.assertIn("<dt>車色</dt><dd>白</dd>", summary)
        self.assertIn("<dt>訂金</dt><dd>無</dd>", summary)
        self.assertIn("線上簽「車輛訂購單」與「個資同意書」", summary)
        self.assertIn("測試車主", page)
        self.assertIn("自動辨識未通過，已人工核對證件正反面", page)
        self.assertIn("確認並建立訂單", page)

        response = self.post("confirm", action="submit", draft=draft, _id_check="failed",
                             _id_check_error="反面照片看不出是身分證反面", _id_manual_confirmed="on")
        order = SalesOrder.objects.get(owner_name="測試車主")
        self.assertRedirects(response, f"{reverse('order_detail', args=[order.pk])}?created=1", fetch_redirect_response=False)
        self.assertFalse(OrderDraft.objects.exists())
        self.assertTrue(order.id_front and order.id_back)
        self.assertEqual(order.other_fees.count(), 2)
        event = OrderEvent.objects.get(order=order, event_type="identity_manual_check")
        self.assertIn("反面照片看不出是身分證反面", event.description)

    def test_steps_follow_counter_conversation_order(self):
        # 1.68.0：配件、汰舊補助、選號交車各自一步，依現場詢問順序排列，不必回頭往上找。
        page = self.client.get(reverse("order_create")).content.decode()
        order = [page.index(f'data-wizard-panel="{key}"') for key in
                 ("accessories", "tradein", "delivery", "owner", "payment", "deposit")]
        self.assertEqual(order, sorted(order))
        deposit_panel = page.split('data-wizard-panel="deposit"', 1)[1].split("</form>", 1)[0]
        self.assertIn('id="deposit-subsection"', deposit_panel)
        self.assertNotIn("installment-picker", deposit_panel)

    def test_legacy_draft_done_keys_map_to_split_steps(self):
        from types import SimpleNamespace
        old = SimpleNamespace(data={"_wizard_done": ["vehicle", "extras", "owner"]})
        self.assertEqual(wizard.done_steps(old), ["vehicle", "accessories", "tradein", "delivery", "owner"])
        old.data["_wizard_done"].append("payment")
        self.assertEqual(wizard.done_steps(old)[-2:], ["payment", "deposit"])

    def test_submit_requires_every_step_and_goto_saves_first(self):
        draft = self.walk_to("delivery")
        response = self.post("delivery", action="submit", draft=draft)
        self.assertRedirects(response, f"{reverse('order_create')}?draft={draft.pk}&step=delivery", fetch_redirect_response=False)
        self.assertFalse(SalesOrder.objects.exists())
        response = self.post("delivery", action="goto", draft=draft, note="改完再回第一步", _wizard_goto="vehicle")
        self.assertRedirects(response, f"{reverse('order_create')}?draft={draft.pk}&step=vehicle", fetch_redirect_response=False)
        draft.refresh_from_db()
        self.assertEqual(draft.data["note"], "改完再回第一步")

    def test_custom_accessory_name_survives_later_steps(self):
        self.setUpKey()
        custom = {"accessories-0-accessory_product": "other", "accessories-0-custom_name": "測試安全帽",
                  "accessories-0-amount": "1500", "accessories-0-labor_fee": "0", "accessories-0-quantity": "2"}
        self.post("vehicle", **custom)
        draft = self.draft()
        response = self.post("accessories", draft=draft, **custom)
        self.assertEqual(response.status_code, 302)
        # 每一步都由草稿重新載入，自訂配件名稱不能遺失，否則後面步驟會被配件錯誤擋下。
        page = self.client.get(reverse("order_create"), {"draft": draft.pk, "step": "tradein"}).content.decode()
        self.assertIn('value="測試安全帽"', page)

@override_settings(MEDIA_ROOT=MEDIA)
class ReceptionWizardTests(TestCase):
    setUp = test_reception_entry.ReceptionEntryTests.setUp
    image = test_reception_entry.ReceptionEntryTests.image
    complete_data = test_reception_entry.ReceptionEntryTests.complete_data
    grant_intake_only = test_reception_entry.ReceptionEntryTests.grant_intake_only

    def test_reception_walks_every_step_and_submits_deposit_without_other_finance(self):
        self.grant_intake_only()
        key = str(uuid.uuid4())
        draft = None
        for step in ("vehicle", "accessories", "tradein", "delivery", "owner", "payment", "deposit"):
            data = {**self.complete_data(), "_wizard_step": step, "_wizard_action": "next", "_submission_key": key,
                    "_id_check": "passed", "deposit_amount": "3000", "deposit_method": "cash",
                    "registration_plate_fee": "999"}
            if draft:
                data["_draft_id"] = str(draft.pk)
            if step == "owner":
                data.update(id_front=self.image("front.png"), id_back=self.image("back.png"))
            response = self.client.post(reverse("order_start"), data)
            draft = OrderDraft.objects.get()
            self.assertEqual(response.status_code, 302, response.content.decode()[:300])
            self.assertTrue(response.url.startswith(reverse("order_start")))
        self.assertTrue(draft.data["_reception"])
        # 訂金所有建單帳號都可填並存進草稿；其他財務欄位仍不保存。
        self.assertEqual(draft.data["deposit_amount"], "3000")
        self.assertNotIn("registration_plate_fee", draft.data)
        page = self.client.get(reverse("order_start"), {"draft": draft.pk, "step": "confirm"})
        self.assertContains(page, "請核對整張訂單")
        summary = page.content.decode().split("wizard-summary", 1)[1].split("</section>", 1)[0]
        self.assertIn("<dt>訂金</dt><dd>3,000 元</dd>", summary)
        self.assertNotIn("實際牌險合計", summary)
        response = self.client.post(reverse("order_start"), {**self.complete_data(), "_wizard_step": "confirm", "_wizard_action": "submit",
                                                            "_submission_key": key, "_id_check": "passed", "_draft_id": str(draft.pk),
                                                            "deposit_amount": "3000", "deposit_method": "cash"})
        order = SalesOrder.objects.get()
        self.assertEqual(response.url, reverse("order_submitted", args=[order.pk]))
        self.assertEqual((order.deposit_amount, order.deposit_method), (3000, "cash"))
        deposit = order.payment_records.get(system_key="deposit")
        self.assertEqual((deposit.expected_amount, deposit.received_amount, deposit.confirmed), (3000, 0, False))
        # 沒有簽署或列印權限時，成立頁不顯示空白的簽署區塊。
        self.assertNotContains(self.client.get(response.url), "sign-choice")
        self.assertFalse(OrderEvent.objects.filter(order=order, event_type="identity_manual_check").exists())