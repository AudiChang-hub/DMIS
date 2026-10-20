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

    def walk_to(self, last, files=True, **owner_extra):
        self.key = getattr(self, "key", str(uuid.uuid4()))
        draft = None
        for step in ("vehicle", "owner", "tradein", "delivery", "accessories", "deposit", "confirm"):
            if step == last:
                return draft
            # 每一步都會送出整張表單，證件檢查結果在車主步驟之後持續帶著。
            extra = owner_extra if step != "vehicle" else {}
            response = self.post(step, draft=draft, files=files, **extra)
            self.assertEqual(response.status_code, 302, response.content.decode()[:300])
            draft = self.draft()
        return draft

    def setUpKey(self):
        self.key = str(uuid.uuid4())

    def test_first_step_and_classic_fallback(self):
        page = self.client.get(reverse("order_create")).content.decode()
        self.assertIn("訂單精靈・第 1／7 步", page)
        self.assertIn('data-wizard-panel="vehicle"', page)
        self.assertIn('data-wizard-panel="owner" hidden', page)
        self.assertIn('value="next"', page)
        self.assertNotIn("確認並建立訂單", page)
        # 證件為選填（2026-10-14）：辨識有結果前只鎖「已人工核對」勾選，不鎖車主步驟的下一步。
        self.assertIn('id="id-verify-hint" hidden', page)
        self.assertIn("function updateVerifyLock", page)
        self.assertNotIn('id="id-manual-check"', page)
        self.assertNotIn("next.disabled = needsId", page)
        # 訂金獨立成段且一律留空，不自動帶入配件金額（1.70.2）。
        self.assertIn('id="deposit-subsection"', page)
        self.assertNotIn('name="_deposit_auto"', page)
        self.assertNotIn("depositAmount.value =", page)
        self.assertIn("function depositGuidance", page)
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
        self.assertRedirects(response, f"{reverse('order_create')}?draft={draft.pk}&step=owner", fetch_redirect_response=False)
        self.assertEqual(draft.data["_wizard_done"], ["vehicle"])
        skipped = self.client.get(reverse("order_create"), {"draft": draft.pk, "step": "delivery"})
        self.assertRedirects(skipped, f"{reverse('order_create')}?draft={draft.pk}&step=owner", fetch_redirect_response=False)
        # 自動儲存不能清掉伺服器記錄的進度，也不能由前端偽造。
        self.client.post(reverse("draft_save"), {**self.complete_data(), "_draft_id": str(draft.pk),
                                                 "_draft_revision": str(draft.revision), "_wizard_done": "owner"})
        draft.refresh_from_db()
        self.assertEqual(draft.data["_wizard_done"], ["vehicle"])

    def test_owner_step_does_not_require_identity_documents(self):
        # 證件照片、自動辨識與人工核對都是選填（2026-10-14），沒有任何一項會擋下一步。
        draft = self.walk_to("owner")
        response = self.post("owner", draft=draft, files=False, id_verified="")
        self.assertEqual(response.status_code, 302)
        draft.refresh_from_db()
        self.assertEqual(draft.data["_wizard_done"], ["vehicle", "owner"])
        self.assertFalse(draft.id_front)
        summary = self.client.get(reverse("order_create"), {"draft": draft.pk, "step": "tradein"})
        self.assertEqual(summary.status_code, 200)

    def test_submit_without_identity_documents_records_status(self):
        draft = self.walk_to("confirm", files=False, id_verified="", owner_phone="", owner_address="", delivery_method="")
        page = self.client.get(reverse("order_create"), {"draft": draft.pk, "step": "confirm"}).content.decode()
        self.assertIn("<dt>證件檢查</dt><dd>尚未上傳證件正反面</dd>", page)
        response = self.post("confirm", action="submit", draft=draft, files=False, id_verified="",
                             owner_phone="", owner_address="", delivery_method="")
        order = SalesOrder.objects.get(owner_name="測試車主")
        self.assertRedirects(response, f"{reverse('order_detail', args=[order.pk])}?created=1", fetch_redirect_response=False)
        self.assertFalse(order.id_front or order.id_verified)
        self.assertEqual((order.owner_phone, order.owner_address, order.delivery_method), ("", "", ""))
        event = OrderEvent.objects.get(order=order, event_type="identity_manual_check")
        self.assertIn("尚未上傳證件正反面", event.description)

    def test_confirm_summary_and_submit_records_manual_identity_check(self):
        draft = self.walk_to("confirm", _id_check="failed", _id_check_error="反面照片看不出是身分證反面")
        page = self.client.get(reverse("order_create"), {"draft": draft.pk, "step": "confirm"}).content.decode()
        self.assertIn("請核對整張訂單", page)
        summary = page.split("wizard-summary", 1)[1].split("</section>", 1)[0]
        # 車型只列品牌／車種／型號／年份，車色只列顏色；訂金一律列出，並提示建立後簽署。
        self.assertIn("<dt>車型</dt><dd>測試／125</dd>", summary)
        self.assertIn("<dt>車色</dt><dd>白</dd>", summary)
        self.assertIn("<dt>訂金</dt><dd>無</dd>", summary)
        self.assertIn("線上簽「車輛訂購單」與「個資同意書」", summary)
        self.assertIn("測試車主", page)
        self.assertIn("自動辨識未通過（反面照片看不出是身分證反面），已人工核對", page)
        self.assertIn("確認並建立訂單", page)

        response = self.post("confirm", action="submit", draft=draft, _id_check="failed",
                             _id_check_error="反面照片看不出是身分證反面")
        order = SalesOrder.objects.get(owner_name="測試車主")
        self.assertRedirects(response, f"{reverse('order_detail', args=[order.pk])}?created=1", fetch_redirect_response=False)
        self.assertFalse(OrderDraft.objects.exists())
        self.assertTrue(order.id_front and order.id_back)
        self.assertEqual(order.other_fees.count(), 2)
        event = OrderEvent.objects.get(order=order, event_type="identity_manual_check")
        self.assertIn("反面照片看不出是身分證反面", event.description)

    def test_note_belongs_to_deposit_step(self):
        # 使用者 2026-10-17：訂單備註從選號與交車移到訂金與費用。
        self.assertEqual(wizard.field_step("note"), "deposit")
        page = self.client.get(reverse("order_create")).content.decode()
        delivery_panel = page.split('id="delivery"', 1)[1].split("</details>", 1)[0]
        deposit_panel = page.split('id="deposit"', 1)[1].split('name="installment_document"', 1)[0]
        self.assertNotIn('name="note"', delivery_panel)
        self.assertIn('name="note"', deposit_panel)
        self.assertEqual(page.count('name="note"'), 1)

    def test_steps_follow_counter_conversation_order(self):
        # 使用者 2026-10-15：車款→付款與車價→車主→汰舊與補助→選號與交車→訂金→確認；2026-10-16 前兩步合併；
        # 2026-10-17 配件加回；同日改為配件在前、訂金與費用在後，接著確認送出。
        self.assertEqual(wizard.STEP_KEYS, ("vehicle", "owner", "tradein", "delivery", "accessories", "deposit", "confirm"))
        page = self.client.get(reverse("order_create")).content.decode()
        bar = page.split("wizard-bar", 1)[1].split("</nav>", 1)[0]
        labels = [bar.index(label) for label in ("車款與車價", "車主與證件", "汰舊與補助", "選號與交車", "加購項目與贈品（可略過）", "訂金與費用", "確認送出")]
        self.assertEqual(labels, sorted(labels))
        deposit_panel = page.split('data-wizard-panel="deposit"', 1)[1].split("</form>", 1)[0]
        self.assertIn('id="deposit-subsection"', deposit_panel)
        self.assertNotIn("installment-picker", deposit_panel)

    def test_accessories_step_can_be_skipped(self):
        # 使用者 2026-10-17：配件加回第 5 步並標示可略過；不選配件直接下一步到訂金，確認頁列「未選配件」。
        draft = self.walk_to("accessories")
        page = self.client.get(reverse("order_create"), {"draft": draft.pk, "step": "accessories"}).content.decode()
        self.assertIn("訂單精靈・第 5／7 步", page)
        panel = page.split('id="accessories"', 1)[1].split("</details>", 1)[0]
        self.assertNotIn("hidden", panel.split(">", 1)[0])
        self.assertIn("data-wizard-skip-note", panel)
        self.assertIn('<span class="optional-badge">可略過</span>', panel)
        response = self.post("accessories", draft=draft)
        self.assertRedirects(response, f"{reverse('order_create')}?draft={draft.pk}&step=deposit", fetch_redirect_response=False)
        self.assertEqual(self.post("deposit", draft=self.draft()).status_code, 302)
        page = self.client.get(reverse("order_create"), {"draft": draft.pk, "step": "confirm"}).content.decode()
        summary = page.split("wizard-summary", 1)[1].split("</section>", 1)[0]
        self.assertIn("<dt>配件</dt><dd>未選配件</dd>", summary)
        # 使用者 2026-10-17：建立訂單的「配件」步驟改名「加購項目與贈品」。
        self.assertIn("加購項目與贈品", summary)
        self.assertIn('value="accessories"', summary)
        self.post("confirm", action="submit", draft=draft)
        self.assertFalse(SalesOrder.objects.get(owner_name="測試車主").accessories.exists())

    def test_selected_accessories_show_on_confirm_and_count_in_total(self):
        draft = self.walk_to("accessories")
        lines = {"accessories-TOTAL_FORMS": "2", "accessories-INITIAL_FORMS": "0"}
        for index, (name, amount, labor, quantity) in enumerate((("安全帽", "1500", "0", "2"), ("手機架", "800", "200", "1"))):
            lines.update({f"accessories-{index}-accessory_product": "other", f"accessories-{index}-custom_name": name,
                          f"accessories-{index}-quantity": quantity, f"accessories-{index}-line_type": "purchase",
                          f"accessories-{index}-amount": amount, f"accessories-{index}-labor_fee": labor})
        self.assertEqual(self.post("accessories", draft=draft, **lines).status_code, 302)
        # 訂金頁（配件之後）列出車價、牌險費、配件與三項合計，由畫面即時加總。
        page = self.client.get(reverse("order_create"), {"draft": draft.pk, "step": "deposit"}).content.decode()
        panel = page.split('id="deposit"', 1)[1].split("</details>", 1)[0]
        for key in ("vehicle", "plate", "selection", "accessories", "sum"):
            self.assertIn(f'data-intake-total="{key}"', panel)
        self.assertIn("三項合計", panel)
        self.assertIn("function updateIntakeTotals", page)
        # 使用者 2026-10-17：指定號碼有選號費時列出選號費並改稱四項合計。
        self.assertIn('data-intake-total-cell="selection" hidden', panel)
        self.assertIn('const selection = plateChoice.value === "watch" ? amountOf("id_plate_selection_fee") : null;', page)
        self.assertIn('showSelection ? "四項合計" : "三項合計"', page)
        # 使用者 2026-10-20：牌險費留空時寫「另計」、不列入合計，客人看不到系統算出的金額。
        self.assertIn('"合計（牌險另計）"', page)
        self.assertIn('node.textContent = pending ? "另計"', page)
        self.assertNotIn("系統預估", page)
        self.assertEqual(self.post("deposit", draft=self.draft(), **lines).status_code, 302)
        page = self.client.get(reverse("order_create"), {"draft": draft.pk, "step": "confirm"}).content.decode()
        summary = page.split("wizard-summary", 1)[1].split("</section>", 1)[0]
        self.assertIn("安全帽 × 2", summary)
        self.assertIn("手機架 × 1", summary)
        self.assertIn("<dt>配件合計</dt><dd>4,000 元</dd>", summary)
        self.post("confirm", action="submit", draft=draft, **lines)
        order = SalesOrder.objects.get(owner_name="測試車主")
        self.assertEqual(order.accessories.count(), 2)
        self.assertEqual(order.accessory_total, 4000)
        self.assertEqual(order.calculate_balance(), order.vehicle_price + order.plate_insurance_fee + 4000
                         + order.registration_extra_fee_total + order.other_fee_total - order.deposit_amount)

    def test_accessory_errors_return_to_accessories_step(self):
        draft = self.walk_to("accessories")
        bad = {"accessories-TOTAL_FORMS": "1", "accessories-INITIAL_FORMS": "0",
               "accessories-0-accessory_product": "other", "accessories-0-custom_name": "",
               "accessories-0-quantity": "1", "accessories-0-line_type": "purchase",
               "accessories-0-amount": "500", "accessories-0-labor_fee": "0"}
        response = self.post("accessories", draft=draft, **bad)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "這一步還有資料需要處理")
        draft.refresh_from_db()
        self.assertNotIn("accessories", draft.data["_wizard_done"])

    def test_vehicle_and_payment_share_first_step(self):
        # 使用者 2026-10-16：跟客人確認車款就接著寫價格，車款、來源、付款與車價同一步；後面步驟還空白時要能單獨通過。
        self.setUpKey()
        page = self.client.get(reverse("order_create")).content.decode()
        payment_tag = page.split('id="payment"', 1)[1].split(">", 1)[0]
        self.assertIn('data-wizard-panel="vehicle"', payment_tag)
        self.assertNotIn("hidden", payment_tag)
        blank_later = {"owner_type": "", "owner_name": "", "owner_phone": "", "owner_birth_date": "", "owner_address": "",
                       "owner_id_number": "", "id_verified": "", "plate_choice": "", "delivery_method": "",
                       "trade_in_intent": "", "deposit_amount": ""}
        response = self.post("vehicle", files=False, **blank_later)
        self.assertEqual(response.status_code, 302, response.content.decode()[:400])
        draft = self.draft()
        self.assertEqual(draft.data["_wizard_done"], ["vehicle"])
        self.assertRedirects(response, f"{reverse('order_create')}?draft={draft.pk}&step=owner", fetch_redirect_response=False)
        # 付款方式有錯就停在第一步（2026-10-16 起付款方式為多筆明細）。
        response = self.post("vehicle", draft=draft, files=False, payment_splits='[{"method": "bitcoin", "amount": 1}]', **blank_later)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "這一步還有資料需要處理")

    def test_plate_choice_offers_pending(self):
        # 使用者 2026-10-15：選號方式多「待確認」，跟不選號一樣不顯示也不計選號費。
        page = self.client.get(reverse("order_create")).content.decode()
        self.assertIn('<option value="pending">待確認</option>', page)
        # 使用者 2026-10-17：只有「指定號碼」才有選號費。
        self.assertIn('<option value="watch">指定號碼</option>', page)
        self.assertIn('showConditional("plate-selection", plateChoice.value === "watch");', page)

    def test_legacy_draft_done_keys_map_to_split_steps(self):
        from types import SimpleNamespace
        old = SimpleNamespace(data={"_wizard_done": ["vehicle", "extras", "owner"]})
        self.assertEqual(wizard.done_steps(old), ["vehicle", "owner", "tradein", "delivery", "accessories"])
        self.assertEqual(wizard.first_open_step(old), "deposit")  # 新順序下跳號的舊草稿回到第一個未完成步驟
        old.data["_wizard_done"].append("payment")
        self.assertEqual(wizard.done_steps(old), ["vehicle", "owner", "tradein", "delivery", "accessories", "deposit"])
        # 1.84–1.86.0 完成訂金、還沒選配件的草稿：回到配件這一步，不能直接送出。
        before = SimpleNamespace(data={"_wizard_done": ["vehicle", "owner", "tradein", "delivery", "deposit"]})
        self.assertEqual(wizard.first_open_step(before), "accessories")
        # 1.83 的草稿（付款與車價是獨立一步）：舊步驟代號不再出現在進度裡。
        recent = SimpleNamespace(data={"_wizard_done": ["vehicle", "payment"]})
        self.assertEqual(wizard.done_steps(recent), ["vehicle"])
        self.assertEqual(wizard.first_open_step(recent), "owner")

    def test_submit_requires_every_step_and_goto_saves_first(self):
        draft = self.walk_to("delivery")
        response = self.post("delivery", action="submit", draft=draft)
        self.assertRedirects(response, f"{reverse('order_create')}?draft={draft.pk}&step=delivery", fetch_redirect_response=False)
        self.assertFalse(SalesOrder.objects.exists())
        response = self.post("delivery", action="goto", draft=draft, plate_preference_note="改完再回第一步", _wizard_goto="vehicle")
        self.assertRedirects(response, f"{reverse('order_create')}?draft={draft.pk}&step=vehicle", fetch_redirect_response=False)
        draft.refresh_from_db()
        self.assertEqual(draft.data["plate_preference_note"], "改完再回第一步")

    def test_three_accessories_and_two_fees_survive_reload(self):
        # 1.72.5：草稿有多筆配件／其他費用時，換步驟重新載入不能只剩第一筆（SO20261010-2AE018 三筆配件只存一筆）。
        self.setUpKey()
        lines = {"accessories-TOTAL_FORMS": "3", "accessories-INITIAL_FORMS": "0",
                 "other_fees-TOTAL_FORMS": "2", "other_fees-INITIAL_FORMS": "0",
                 "other_fees-0-name": "保險升級", "other_fees-0-amount": "500",
                 "other_fees-1-name": "代辦費", "other_fees-1-amount": "300"}
        for index, (name, amount) in enumerate((("前側保桿", "1300"), ("手機架", "800"), ("後照鏡", "600"))):
            lines.update({f"accessories-{index}-accessory_product": "other", f"accessories-{index}-custom_name": name,
                          f"accessories-{index}-quantity": "1", f"accessories-{index}-line_type": "purchase",
                          f"accessories-{index}-amount": amount, f"accessories-{index}-labor_fee": "0"})
        self.assertEqual(self.post("vehicle", **lines).status_code, 302)
        draft = self.draft()
        page = self.client.get(reverse("order_create"), {"draft": draft.pk, "step": "owner"}).content.decode()
        for name in ("前側保桿", "手機架", "後照鏡", "保險升級", "代辦費"):
            self.assertIn(f'value="{name}"', page)
        self.assertIn('name="accessories-TOTAL_FORMS" value="3"', page)
        self.assertIn('name="other_fees-TOTAL_FORMS" value="2"', page)


    def test_custom_accessory_name_survives_later_steps(self):
        self.setUpKey()
        custom = {"accessories-0-accessory_product": "other", "accessories-0-custom_name": "測試安全帽",
                  "accessories-0-amount": "1500", "accessories-0-labor_fee": "0", "accessories-0-quantity": "2"}
        response = self.post("vehicle", **custom)
        self.assertEqual(response.status_code, 302)
        draft = self.draft()
        # 每一步都由草稿重新載入，自訂配件名稱不能遺失，否則後面步驟會被配件錯誤擋下。
        page = self.client.get(reverse("order_create"), {"draft": draft.pk, "step": "owner"}).content.decode()
        self.assertIn('value="測試安全帽"', page)

    def test_tradein_step_keeps_every_subsidy_and_shows_saved_documents(self):
        from sales.models import OrderIntakeAttachment, SubsidyProgram
        first = SubsidyProgram.objects.create(name="測試補助甲")
        second = SubsidyProgram.objects.create(name="測試補助乙")
        draft = self.walk_to("tradein")
        tradein = {"trade_in_intent": "yes", "subsidy_programs_present": "1",
                   "subsidy_programs": [str(first.pk), str(second.pk)]}
        response = self.client.post(reverse("order_create"), {
            **self.complete_data(), **tradein, "_wizard_step": "tradein", "_wizard_action": "next",
            "_submission_key": self.key, "_draft_id": str(draft.pk), "_draft_revision": str(draft.revision),
            "old_id_front": self.image("old-front.png"),
        })
        self.assertEqual(response.status_code, 302)
        # 回到第三步與之後每一步（隱藏的汰舊區塊會跟著送出）都要勾著兩個補助，不能只剩最後一個（2026-10-17）。
        for step in ("tradein", "delivery"):
            page = self.client.get(reverse("order_create"), {"draft": draft.pk, "step": step}).content.decode()
            for program in (first, second):
                self.assertRegex(page, rf'name="subsidy_programs" value="{program.pk}"[^>]*checked')
        # 已存的證件列在第三步，不再像沒上傳過。
        self.assertIn("已存的證件與存摺", page)
        self.assertIn("old-front.png", page)
        # 同一類重新選檔直接取代原檔，不必先勾移除。
        draft.refresh_from_db()
        response = self.client.post(reverse("order_create"), {
            **self.complete_data(), **tradein, "_wizard_step": "tradein", "_wizard_action": "next",
            "_submission_key": self.key, "_draft_id": str(draft.pk), "_draft_revision": str(draft.revision),
            "old_id_front": self.image("old-front-new.png"),
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(list(OrderIntakeAttachment.objects.filter(draft=draft, kind="old_id_front").values_list("name", flat=True)),
                         ["old-front-new.png"])

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
        for step in ("vehicle", "owner", "tradein", "delivery", "accessories", "deposit"):
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
        # 建單填了訂金就算已收妥（使用者 2026-10-20 T-29 方案 A，接待模式也一樣）。
        self.assertEqual((deposit.expected_amount, deposit.received_amount, deposit.confirmed), (3000, 3000, True))
        # 沒有簽署或列印權限時，成立頁不顯示空白的簽署區塊。
        self.assertNotContains(self.client.get(response.url), "sign-choice")
        self.assertFalse(OrderEvent.objects.filter(order=order, event_type="identity_manual_check").exists())