"""訂單頁整理（使用者 2026-10-21）：頁首新車主資料列、訂車與配件分區調整、選號與交車排版。"""
import re
from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from sales.models import SalesOrder
from sales.tests import test_order_flow as flow


def hero(page):
    start = page.rindex("<section", 0, page.index("data-order-hero"))
    return page[start:page.index("data-order-stage-start")]


def owner_facts(page):
    start = page.index('id="order-owner-facts"')
    return page[start:page.index("</ul>", start)]


class OrderPageSectionTests(TestCase):
    setUp = flow.OrderFlowTests.setUp
    make_order = flow.OrderFlowTests.make_order

    def page(self, order, query="?tab=order"):
        admin = get_user_model().objects.filter(username="admin").first() or get_user_model().objects.create_superuser(
            "admin", password="test-only")
        self.client.force_login(admin)
        response = self.client.get(reverse("order_detail", args=[order.pk]) + query)
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def update(self, order, **fields):
        SalesOrder.objects.filter(pk=order.pk).update(**fields)
        return SalesOrder.objects.get(pk=order.pk)

    # T-35：頁首依序顯示證號 → 生日 → 電話 → Email → 地址。
    def test_header_lists_owner_facts_in_requested_order(self):
        order = self.update(self.make_order(), owner_birth_date=date(1988, 2, 23), owner_email="owner@example.com",
                            owner_address="台北市萬華區寶興街115號")
        facts = owner_facts(self.page(order))
        labels = re.findall(r"<li[^>]*><span>([^<]+)</span>", facts)
        self.assertEqual(labels, ["身分證字號", "生日", "電話", "Email", "戶籍地址"])
        for value in ("A123456789", "民國 77 年 2 月 23 日", "西元 1988/02/23", "0912345678", "owner@example.com",
                      "台北市萬華區寶興街115號"):
            self.assertIn(value, facts)
        self.assertIn("data-inplace-region", facts[:200])

    def test_header_skips_blank_email_and_import_placeholders(self):
        order = self.update(self.make_order(), owner_email="", owner_id_number="HIST-abc-1", owner_phone="未提供",
                            owner_address="未提供")
        facts = owner_facts(self.page(order))
        self.assertNotIn("Email", facts)
        self.assertNotIn("HIST-", facts)
        self.assertNotIn("未提供", facts)

    def test_header_labels_follow_owner_type(self):
        order = self.update(self.make_order(), owner_type=SalesOrder.OwnerType.COMPANY, owner_id_number="83739807")
        facts = owner_facts(self.page(order))
        self.assertIn("<span>統一編號</span>", facts)
        self.assertIn("<span>公司地址</span>", facts)
        order = self.update(order, owner_type=SalesOrder.OwnerType.FOREIGN, owner_id_number="AC01234567")
        self.assertIn("<span>居留證號</span>", owner_facts(self.page(order)))

    def test_compact_bar_does_not_repeat_owner_facts(self):
        page = self.page(self.make_order())
        bar = page[page.index("data-order-compact-bar"):page.index("data-order-stage-start")]
        self.assertNotIn("order-owner-facts", bar)
        self.assertNotIn("A123456789", bar)

    # T-36：新車主資料排最後、不放附件；證件與下訂附件區與浮水印入口移除。
    def test_order_sections_put_new_owner_last_without_attachments(self):
        page = self.page(self.make_order())
        panel = page[page.index('id="panel-order"'):page.index('id="panel-deposit"')]
        titles = re.findall(r'<details class="form-section" id="(\w+)"', panel)
        self.assertEqual(titles[-1], "owner")
        self.assertLess(panel.index('id="deposit"'), panel.index('id="owner"'))
        owner = panel[panel.index('id="owner"'):]
        self.assertIn("<strong>新車主資料</strong>", owner)
        self.assertNotIn("車主與證件", panel)
        self.assertNotIn("intake-attachments", owner[:owner.index("</summary>") + 400])
        for removed in ("證件與下訂附件", "列印／下載浮水印證件", "order-identity-tools"):
            self.assertNotIn(removed, page)

    def test_order_sections_are_renumbered_in_order(self):
        page = self.page(self.make_order())
        panel = page[page.index('id="panel-order"'):page.index('id="panel-deposit"')]
        numbers = [int(n) for n in re.findall(r'<span class="step-number">(\d+)</span>', panel)]
        self.assertEqual(numbers, list(range(1, len(numbers) + 1)))

    def test_attachments_step_still_lists_owner_documents_and_intake_files(self):
        # 訂單頁不再顯示證件與下訂附件，檔案仍在左側「附件」查得到。
        import tempfile
        from django.test import RequestFactory, override_settings
        from sales.models import OrderIntakeAttachment
        from sales.services.order_attachments import collect_order_file_groups
        media = tempfile.TemporaryDirectory()
        self.addCleanup(media.cleanup)
        with override_settings(MEDIA_ROOT=media.name):
            order = self.make_order()
            order.id_front = flow.uploaded_test_jpeg("front.jpg")
            order.save(update_fields=["id_front", "updated_at"])
            admin = get_user_model().objects.create_superuser("admin", password="test-only")
            OrderIntakeAttachment.objects.create(order=order, kind="owner_bankbook", file=flow.uploaded_test_jpeg("bank.jpg"),
                                                 name="bank.jpg", checksum="x", uploaded_by=admin)
            request = RequestFactory().get("/")
            request.user = admin
            groups = {group["title"]: group["files"] for group in collect_order_file_groups(order, request)}
        self.assertEqual([item.label for item in groups["車主證件"]], ["證件正面"])
        self.assertEqual(len(groups["下訂附件"]), 1)

    def test_wizard_keeps_owner_and_identity_section(self):
        admin = get_user_model().objects.create_superuser("admin", password="test-only")
        self.client.force_login(admin)
        page = self.client.get(reverse("order_create")).content.decode()
        self.assertIn("車主與證件", page)
        self.assertNotIn("新車主資料", page)

    # T-37：送達地點緊接交車方式，備註在左欄往上移。
    def test_delivery_section_puts_destination_under_method_and_note_up(self):
        page = self.page(self.make_order())
        section = page[page.index('id="delivery"'):]
        section = section[:section.index("</details>")]
        left, right = section.split('<div class="delivery-layout__col">')[1:3]
        self.assertIn('name="plate_choice"', left)
        self.assertIn('name="note"', left)
        self.assertLess(right.index('name="delivery_method"'), right.index('name="delivery_destination"'))
        self.assertIn('name="plate_selection_fee"', right)


class OrderSourceInCardTests(TestCase):
    """T-36 方案 A：訂單來源併進頁首右上角小卡，存檔仍走訂單自動儲存與修改紀錄。"""
    setUp = flow.OrderFlowTests.setUp
    make_order = flow.OrderFlowTests.make_order
    page = OrderPageSectionTests.page

    def detail(self, order):
        self.page(order)  # 登入 admin
        return self.client.get(reverse("order_detail", args=[order.pk]), {"tab": "order"})

    def workspace_payload(self, response, **changes):
        from sales.tests.test_order_workspace import form_data, formset_data
        data = {**form_data(response.context["form"]), **formset_data(response.context["formset"]),
                **formset_data(response.context["fee_formset"]),
                "_order_revision": response.context["order"].revision, "_workspace": "1"}
        data.update(changes)
        return data

    def test_source_fields_live_in_card_and_belong_to_order_form(self):
        page = self.page(self.make_order())
        card = hero(page)
        self.assertIn("訂單來源</p>", card)
        self.assertRegex(card, r'<select name="source_type"[^>]*form="order-form"')
        self.assertRegex(card, r'<select name="source"[^>]*form="order-form"')
        self.assertIn('data-autosave-mirror="order-form"', card)
        panel = page[page.index('id="panel-order"'):page.index('id="panel-deposit"')]
        self.assertNotIn('id="source"', panel)
        self.assertNotIn("<strong>訂單來源</strong>", panel)
        self.assertEqual(page.count('name="source_type"'), 1)

    def test_source_change_from_card_saves_with_audit(self):
        from sales.models import OrderChange, SalesSource
        dealer = SalesSource.objects.create(name="來源測試車行", source_type=SalesSource.SourceType.DEALER)
        order = self.make_order()
        response = self.detail(order)
        data = self.workspace_payload(response, source_type="dealer", source=str(dealer.pk))
        saved = self.client.post(reverse("order_edit", args=[order.pk]), data, HTTP_X_ORDER_WORKSPACE="1")
        self.assertEqual(saved.status_code, 200, saved.content)
        order.refresh_from_db()
        self.assertEqual((order.source_type, order.source_id), ("dealer", dealer.pk))
        change = OrderChange.objects.filter(order=order).latest("pk")
        self.assertEqual(change.changes["訂單來源"], {"before": "store", "after": "dealer"})

    def test_source_validation_rules_are_unchanged(self):
        from sales.models import SalesSource
        dealer = SalesSource.objects.create(name="來源測試車行", source_type=SalesSource.SourceType.DEALER)
        order = self.make_order()
        data = self.workspace_payload(self.detail(order), source_type="store", source=str(dealer.pk))
        rejected = self.client.post(reverse("order_edit", args=[order.pk]), data, HTTP_X_ORDER_WORKSPACE="1")
        self.assertEqual(rejected.status_code, 400)
        self.assertIn("source", rejected.json()["errors"])
        order.refresh_from_db()
        self.assertEqual(order.source_type, "store")

    def test_platform_order_card_edits_source_without_attribution(self):
        from sales.models import SalesSource
        platform = SalesSource.objects.create(name="測試平台", source_type=SalesSource.SourceType.PLATFORM)
        order = self.make_order()
        SalesOrder.objects.filter(pk=order.pk).update(source_type="platform", source=platform)
        card = hero(self.page(SalesOrder.objects.get(pk=order.pk)))
        self.assertIn('data-source-summary="full">網路平台／測試平台', card)
        self.assertIn("變更來源", card)
        self.assertNotIn("調整台數與傭金歸屬", card)
        self.assertRegex(card, r'<select name="source_type"[^>]*form="order-form"')

    def test_workspace_script_forwards_fields_owned_by_form_from_outside(self):
        script = open("static/js/order-workspace.js", encoding="utf-8").read()
        self.assertIn("!form.contains(event.target)", script)
        self.assertIn("data-autosave-mirror", script)
