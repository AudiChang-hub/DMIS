"""汰舊與補助精簡（使用者 2026-10-22 T-80～T-83，方案 A）。

T-80：不再選「是否有汰舊」，勾到汰舊類補助方案（requires_old_vehicle）就是有汰舊；建單不上傳舊車主附件。
T-81：補助頁不再手動勾「申請汰舊／政府補助」，由補助項目推導；舊車主戶籍、舊車估價、未繳稅金不再輸入；
      補助申請項目在上，舊車主與舊車報廢資料併成「汰舊與舊車資料」一張卡。
T-82：撥款銀行與匯款帳戶放在補助申請項目標題列；補助撥款追蹤整區拿掉。
T-83：其他補助文件的上傳列直接在標題下，不受汰舊流程影響。
"""
import re

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from sales.models import SalesOrder, SubsidyItem, SubsidyProgram
from sales.services.subsidy_programs import sync_trade_in_from_subsidies
from sales.tests import test_order_intake as intake_fixtures
from sales.tests import test_order_lifecycle as lifecycle


def trade_in_program():
    return SubsidyProgram.objects.update_or_create(
        name="產業發展署 汰舊", defaults={"category": "industry", "requires_old_vehicle": True, "active": True, "vehicle_kind": "", "exclusive_group": ""})[0]


def new_purchase_program():
    return SubsidyProgram.objects.update_or_create(
        name="產業發展署 新購", defaults={"category": "industry", "requires_old_vehicle": False, "active": True, "vehicle_kind": "", "exclusive_group": ""})[0]


class IntakeTradeInTests(TestCase):
    setUp = intake_fixtures.OrderIntakeTests.setUp
    image = intake_fixtures.OrderIntakeTests.image
    complete_data = intake_fixtures.OrderIntakeTests.complete_data
    submit = intake_fixtures.OrderIntakeTests.submit

    def test_form_has_no_trade_in_select_or_old_owner_uploads(self):
        trade_in_program()
        self.client.force_login(self.user)
        page = self.client.get(reverse("order_create")).content.decode()
        self.assertNotIn('name="trade_in_intent"', page)
        self.assertNotIn('name="is_trade_in_subsidy"', page)
        for name in ("old_id_front", "old_id_back", "old_bankbook"):
            self.assertNotIn(f'name="{name}"', page)
        self.assertIn('name="owner_bankbook"', page)
        self.assertRegex(page, r'data-subsidy-trade-in>[^<]*<input[^>]*name="subsidy_programs"')

    def test_trade_in_program_means_trade_in(self):
        program = trade_in_program()
        response = self.submit(subsidy_programs=[str(program.pk)], subsidy_programs_present="1")
        self.assertEqual(response.status_code, 302, getattr(response, "context", None) and response.context["form"].errors)
        order = SalesOrder.objects.get()
        self.assertEqual((order.trade_in_intent, order.is_trade_in_subsidy, order.old_owner_same_as_owner), ("yes", True, True))

    def test_new_purchase_only_is_not_trade_in(self):
        program = new_purchase_program()
        response = self.submit(subsidy_programs=[str(program.pk)], subsidy_programs_present="1")
        self.assertEqual(response.status_code, 302)
        order = SalesOrder.objects.get()
        self.assertEqual((order.trade_in_intent, order.is_trade_in_subsidy, order.old_owner_same_as_owner), ("no", False, True))


class SubsidyStepTests(lifecycle.OrderLifecycleTests.__bases__[0]):
    setUp = lifecycle.OrderLifecycleTests.setUp
    make_order = lifecycle.OrderLifecycleTests.make_order

    def login_admin(self):
        self.client.force_login(get_user_model().objects.create_superuser("admin", password="Subsidy-test-80!"))

    def page(self, order):
        return self.client.get(reverse("order_detail", args=[order.pk]), {"tab": "subsidy"}).content.decode()

    def post_items(self, order, rows):
        data = {"_order_revision": str(order.revision), "trade_in_plate": "", "old_owner_name": "",
                "old_owner_id_number": "", "old_owner_phone": "",
                "subsidy_items-TOTAL_FORMS": str(len(rows)), "subsidy_items-INITIAL_FORMS": str(sum(1 for r in rows if r.get("id"))),
                "subsidy_items-MIN_NUM_FORMS": "0", "subsidy_items-MAX_NUM_FORMS": "1000"}
        for index, row in enumerate(rows):
            for key, value in row.items():
                data[f"subsidy_items-{index}-{key}"] = value
        return self.client.post(reverse("subsidy_data_update", args=[order.pk]), data)

    def test_subsidy_items_drive_trade_in(self):
        self.login_admin()
        order, _vehicle = self.make_order()
        program = trade_in_program()
        self.post_items(order, [{"item_name": program.name, "category": "industry", "status": "not_submitted"}])
        order.refresh_from_db()
        self.assertEqual((order.is_trade_in_subsidy, order.trade_in_intent), (True, "yes"))
        item = order.subsidy_items.get()
        self.post_items(order, [{"id": str(item.pk), "order": str(order.pk), "item_name": program.name, "category": "industry",
                                 "status": "not_submitted", "DELETE": "on"}])
        order.refresh_from_db()
        self.assertEqual((order.is_trade_in_subsidy, order.trade_in_intent, order.old_owner_same_as_owner), (False, "no", True))

    def test_existing_flag_is_not_recomputed_without_item_changes(self):
        order, _vehicle = self.make_order()
        SalesOrder.objects.filter(pk=order.pk).update(is_trade_in_subsidy=True)
        order.refresh_from_db()
        self.assertTrue(order.is_trade_in_subsidy)  # 匯入單：有勾但沒有汰舊類項目，畫面開啟不會改
        SubsidyItem.objects.create(order=order, category="other", item_name="新購補助")
        order.refresh_from_db()
        self.assertTrue(order.is_trade_in_subsidy)
        self.assertFalse(sync_trade_in_from_subsidies(order))

    def test_layout(self):
        self.login_admin()
        order, _vehicle = self.make_order()
        html = self.page(order)
        for gone in ("申請汰舊／政府補助", 'name="is_trade_in_subsidy"', 'name="old_owner_household_address"',
                     'name="old_vehicle_valuation"', 'name="old_vehicle_tax"', "補助撥款追蹤", 'id="subsidy-agency-summary"'):
            self.assertNotIn(gone, html)
        head = html.split('<div class="subsidy-items__head">', 1)[1].split("{{", 1)[0].split('data-form-list', 1)[0]
        self.assertRegex(head, r'name="operations-bank_name"[^>]*form="ops-subsidy-form"|form="ops-subsidy-form"[^>]*name="operations-bank_name"')
        self.assertIn('name="operations-remittance_account"', head)
        self.assertLess(html.index('data-subsidy-items'), html.index('id="tradein-card-title"'))
        self.assertIn('id="ops-subsidy-form"', html)
        self.assertIn('id="ops-old-vehicle-form"', html)
        # 沒有汰舊時不顯示「新舊車主不同人」，其他補助文件仍可直接上傳。
        self.assertNotIn('name="old_owner_different"', html)
        other = html.split('class="other-subsidy-documents"', 1)[1].split("</section>", 1)[0]
        form_tag = re.search(r'<form class="other-subsidy-documents__form"[^>]*>', other).group(0)
        self.assertNotIn("hidden", form_tag)
        self.assertNotIn("data-subsidy-upload-control", form_tag)
        self.assertNotIn("目前沒有其他補助文件", other)

    def test_bank_fields_save_through_operations_section(self):
        self.login_admin()
        order, _vehicle = self.make_order()
        profile = order.operations
        profile.subsidy_applied_on = None
        profile.save(update_fields=["subsidy_applied_on"])
        profile.refresh_from_db()
        response = self.client.post(reverse("order_operations", args=[order.pk]), {
            "_section": "subsidy", "operations-financial_revision": profile.updated_at.isoformat(),
            "operations-bank_name": "台灣銀行", "operations-remittance_account": "012-3456789",
        }, HTTP_X_ORDER_WORKSPACE="1")
        self.assertEqual(response.status_code, 200, response.content)
        profile.refresh_from_db()
        self.assertEqual((profile.bank_name, profile.remittance_account), ("台灣銀行", "012-3456789"))
        self.assertIsNone(profile.subsidy_applied_on)
