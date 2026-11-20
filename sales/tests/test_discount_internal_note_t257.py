"""T-257：優惠備註（內部）——建單第 6 步與訂單頁內部折扣卡可填，不印訂購單、不進總覽與匯出（使用者選 A）。"""
from io import BytesIO

from django.urls import reverse
from pypdf import PdfReader

from sales.models import OrderChange, OrderDraft, SalesOrder
from sales.tests.test_intake_deposit_discount import IntakeFixtures

NOTE = "店長同意 NOTE257X"


class DiscountInternalNoteTests(IntakeFixtures):
    def workspace_post(self, order, data):
        return self.client.post(reverse("order_discount_note", args=[order.pk]), data,
                                HTTP_X_ORDER_WORKSPACE="1", HTTP_ACCEPT="application/json")

    def create_with_note(self, note=NOTE, **changes):
        response = self.submit(intake_discount_mode="amount", intake_discount_amount="1800",
                               discount_internal_note=note, **changes)
        self.assertEqual(response.status_code, 302, getattr(response, "context", None) and response.context["form"].errors)
        return SalesOrder.objects.latest("pk")

    # ---- 建單第 6 步 ----

    def test_intake_discount_block_has_note_next_to_amount(self):
        page = self.client.get(reverse("order_create"), {"classic": "1"}).content.decode()
        block = page.split('id="intake-discount"', 1)[1].split("</details>", 1)[0]
        fields = block.split('class="form-grid discount-fields"', 1)[1]
        # 減少金額、折數之後接優惠備註：桌面兩欄時在減少金額右邊，手機單欄時在下方。
        self.assertLess(fields.index('name="intake_discount_amount"'), fields.index('name="discount_internal_note"'))
        before, after = fields.split('name="discount_internal_note"', 1)
        tag = before.rsplit("<input", 1)[1] + after.split(">", 1)[0]
        self.assertIn('maxlength="250"', tag)
        self.assertIn("只有店內看得到，不會印在訂購單上。", block)

    def test_intake_saves_note_without_touching_printed_reason(self):
        order = self.create_with_note()
        self.assertEqual(order.discount_internal_note, NOTE)
        # 印在訂購單的折扣原因維持空白，優惠照常直接核定。
        self.assertEqual((order.discount_reason, order.approved_discount_amount, order.discount_status),
                         ("", 1800, SalesOrder.DiscountStatus.APPROVED))

    def test_intake_note_is_optional_and_limited(self):
        order = self.create_with_note(note="")
        self.assertEqual(order.discount_internal_note, "")
        response = self.submit(intake_discount_amount="1000", discount_internal_note="字" * 251)
        self.assertEqual(response.status_code, 200)
        self.assertIn("discount_internal_note", response.context["form"].errors)

    def test_draft_keeps_note_and_reopens_discount_block(self):
        result = self.client.post(reverse("intake_draft_save"), {"owner_name": "草稿客戶", "discount_internal_note": NOTE})
        self.assertEqual(result.status_code, 200)
        draft = OrderDraft.objects.get(pk=result.json()["id"])
        self.assertEqual(draft.data.get("discount_internal_note"), NOTE)
        page = self.client.get(reverse("order_create"), {"draft": draft.pk, "classic": "1"})
        self.assertEqual(page.context["form"]["discount_internal_note"].value(), NOTE)
        self.assertContains(page, 'data-intake-discount open>')

    def test_wizard_maps_note_to_deposit_step(self):
        from sales.services.order_wizard import field_step
        self.assertEqual(field_step("discount_internal_note"), "deposit")

    # ---- 訂單頁內部折扣卡 ----

    def test_order_page_shows_and_autosaves_note_with_audit(self):
        order = self.create_with_note()
        self.client.force_login(self.root)
        page = self.client.get(reverse("order_detail", args=[order.pk])).content.decode()
        card = page.split('id="internal-discount-title"', 1)[1].split("</section>", 1)[0]
        self.assertIn('data-workspace-save="discount_note"', card)
        self.assertIn(f'value="{NOTE}"', card)
        order.refresh_from_db()
        revision = order.revision
        response = self.workspace_post(order, {"_order_revision": str(revision), "discount_internal_note": "改成老客戶介紹"})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.json()["ok"])
        order.refresh_from_db()
        self.assertEqual(order.discount_internal_note, "改成老客戶介紹")
        # 只改備註：折扣金額與印在訂購單的原因不動。
        self.assertEqual((order.approved_discount_amount, order.discount_reason), (1800, ""))
        change = OrderChange.objects.filter(order=order).latest("pk")
        self.assertEqual(change.changes, {"discount_internal_note": {"before": NOTE, "after": "改成老客戶介紹"}})
        self.assertEqual(change.actor_name, self.root.username)
        # 沒有變動不重複寫紀錄。
        count = OrderChange.objects.filter(order=order).count()
        self.workspace_post(order, {"_order_revision": str(order.revision), "discount_internal_note": "改成老客戶介紹"})
        self.assertEqual(OrderChange.objects.filter(order=order).count(), count)

    def test_order_page_rejects_stale_revision_and_too_long_note(self):
        order = self.create_with_note()
        self.client.force_login(self.root)
        stale = self.workspace_post(order, {"_order_revision": str(order.revision + 5), "discount_internal_note": "x"})
        self.assertEqual(stale.status_code, 409)
        too_long = self.workspace_post(order, {"_order_revision": str(order.revision), "discount_internal_note": "字" * 251})
        self.assertEqual(too_long.status_code, 400)
        self.assertIn("discount_internal_note", too_long.json()["errors"])
        order.refresh_from_db()
        self.assertEqual(order.discount_internal_note, NOTE)

    def test_only_discount_editors_can_change_note(self):
        order = self.create_with_note()
        # 有訂單作業畫面、但沒有財務編輯與折扣核定權限的店內人員：送出被拒（與套用折扣同一判斷）。
        from sales.access.models import ScreenAccessGrant
        ScreenAccessGrant.objects.create(user=self.clerk, screen_key="work", view=True, operate=True)
        self.client.force_login(self.clerk)
        SalesOrder.objects.filter(pk=order.pk).update(accepted_by=self.clerk, submitted_by=self.clerk)
        denied = self.workspace_post(order, {"_order_revision": str(order.revision), "discount_internal_note": "偽造"})
        self.assertEqual(denied.status_code, 403)
        order.refresh_from_db()
        self.assertEqual(order.discount_internal_note, NOTE)
        # 補上財務編輯權限就能改（折扣核定路由同屬 work 畫面操作權限）。
        ScreenAccessGrant.objects.create(user=self.clerk, screen_key="order_finance", view=True, operate=True)
        allowed = self.workspace_post(order, {"_order_revision": str(order.revision), "discount_internal_note": "可以改"})
        self.assertEqual(allowed.status_code, 200, allowed.content)

    def test_non_editable_order_keeps_note_read_only(self):
        order = self.create_with_note()
        SalesOrder.objects.filter(pk=order.pk).update(status=SalesOrder.Status.COMPLETED)
        order.refresh_from_db()
        self.client.force_login(self.root)
        response = self.workspace_post(order, {"_order_revision": str(order.revision), "discount_internal_note": "交車後改"})
        self.assertEqual(response.status_code, 400)
        order.refresh_from_db()
        self.assertEqual(order.discount_internal_note, NOTE)

    # ---- 不外流 ----

    def test_note_not_on_contract_pdf_or_terms(self):
        from sales.services.document_signing import contract_terms
        from sales.services.order_contract_pdf import build_order_contract_pdf
        order = self.create_with_note()
        text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(build_order_contract_pdf(order))).pages)
        self.assertIn("1,800", text)  # 優惠金額照印，確認讀得到 PDF 內容
        self.assertNotIn("NOTE257X", text)
        self.assertNotIn("NOTE257X", str(contract_terms(order)))

    def test_note_not_in_order_overview(self):
        from sales.services.order_overview import build_order_overview
        order = self.create_with_note()
        overview = build_order_overview(order)
        self.assertNotIn("NOTE257X", str(overview))
        self.client.force_login(self.root)
        response = self.client.get(reverse("order_overview", args=[order.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "NOTE257X")

    def test_note_not_in_export_or_reimport_columns(self):
        from sales.order_exchange import columns
        self.assertNotIn("discount_internal_note", {column.key for column in columns.COLUMNS})
        self.assertNotIn("優惠備註（內部）", {column.label for column in columns.COLUMNS})


class DiscountInternalNoteSearchTests(IntakeFixtures):
    """使用者 2026-11-20：優惠備註保留可被搜尋，但結果列表與命中摘要不顯示備註內容（PM 選 B）。"""

    def create_with_note(self):
        response = self.submit(intake_discount_mode="amount", intake_discount_amount="1800", discount_internal_note=NOTE)
        self.assertEqual(response.status_code, 302)
        return SalesOrder.objects.latest("pk")

    def test_note_text_finds_the_order(self):
        order = self.create_with_note()
        other = self.create_with_note()
        SalesOrder.objects.filter(pk=other.pk).update(discount_internal_note="")
        from sales.services.order_search import rebuild_order_search_index
        rebuild_order_search_index(other.pk)
        self.client.force_login(self.root)
        response = self.client.get(reverse("order_list"), {"q": "NOTE257X"})
        found = [row.pk for row in response.context["orders"]]
        self.assertEqual(found, [order.pk])

    def test_results_and_match_summary_never_show_note(self):
        from sales.services.order_search import build_order_match_summary
        order = self.create_with_note()
        self.client.force_login(self.root)
        page = self.client.get(reverse("order_list"), {"q": "NOTE257X"}).content.decode()
        table = page.split("<tbody", 1)[1].split("</tbody>", 1)[0]
        self.assertIn(order.number, table)
        self.assertNotIn("NOTE257X", table)
        self.assertNotIn("優惠備註", table)
        # 有快取索引、沒有快取（即時比對）兩條路都不露出。
        order = SalesOrder.objects.select_related("search_index").get(pk=order.pk)
        self.assertEqual(build_order_match_summary(order, "NOTE257X"), [])
        self.assertEqual(build_order_match_summary(order, "NOTE257X", profit_unlocked=False), [])
        order.search_index.delete()
        order = SalesOrder.objects.get(pk=order.pk)
        self.assertEqual(build_order_match_summary(order, "NOTE257X"), [])
