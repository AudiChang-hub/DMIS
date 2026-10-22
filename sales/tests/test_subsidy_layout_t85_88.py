"""補助頁與明細列整理（使用者 2026-10-22）。

T-85：明細表不預設多一列空白（比照 T-43），要新增時按「＋ 新增」才出現；空白列不送出、不建資料，既有資料不動。
T-87：「汰舊與舊車資料」人在上、車在下：舊車車牌移到「舊車與報廢」第一格。
T-88：獨立營運資料頁也拿掉補助撥款追蹤整區；值保留，存檔不會清掉銀行與匯款帳戶。
"""
import re

from django.urls import reverse

from sales import forms as sales_forms
from sales.forms import OrderOperationsForm, PaymentRecordFormSet
from sales.models import OrderOperationsProfile, SalesOrder, SubsidyItem
from sales.tests import test_order_workspace as workspace_fixtures
from sales.tests import test_subsidy_tradein_t80 as t80
from sales.tests.test_order_workspace import form_data, formset_data


class SubsidyPageHelpers(t80.lifecycle.OrderLifecycleTests.__bases__[0]):
    setUp = t80.SubsidyStepTests.setUp
    make_order = t80.SubsidyStepTests.make_order
    login_admin = t80.SubsidyStepTests.login_admin
    page = t80.SubsidyStepTests.page
    post_items = t80.SubsidyStepTests.post_items


class NoBlankRowFormSetTests(SubsidyPageHelpers):
    def test_formsets_have_no_default_blank_row(self):
        for name in ("SubsidyItemFormSet", "OrderPageAccessoryFormSet", "OrderPageOtherFeeFormSet",
                     "DealerRewardCostVersionFormSet"):
            self.assertEqual(getattr(sales_forms, name).extra, 0, name)
        # 成本版本至少一列：新項目靠 min_num 給第一列。
        self.assertEqual(sales_forms.DealerRewardCostVersionFormSet.min_num, 1)
        # 台數門檻、列印範本欄位：新建時給第一列，已有明細不再多一列。
        for name in ("DealerVolumeBonusTierFormSet", "PositionedPrintFieldFormSet"):
            formset = getattr(sales_forms, name)
            self.assertTrue(issubclass(formset, sales_forms.FirstRowWhenEmptyFormSet), name)
            self.assertEqual(len(formset().forms), 1, name)

    def test_subsidy_page_lists_only_saved_items(self):
        self.login_admin()
        order, _vehicle = self.make_order()
        html = self.page(order)
        self.assertIn('name="subsidy_items-TOTAL_FORMS" value="0"', html)
        self.assertRegex(html, r'data-subsidy-empty>還沒有補助項目')
        SubsidyItem.objects.create(order=order, category="other", item_name="縣市加碼", expected_amount=3000)
        html = self.page(order)
        self.assertIn('name="subsidy_items-TOTAL_FORMS" value="1"', html)
        self.assertIn("data-subsidy-empty hidden", html)

    def test_blank_added_row_is_not_saved_and_existing_kept(self):
        self.login_admin()
        order, _vehicle = self.make_order()
        item = SubsidyItem.objects.create(order=order, category="other", item_name="縣市加碼", expected_amount=3000)
        order.refresh_from_db()
        response = self.post_items(order, [
            {"id": str(item.pk), "order": str(order.pk), "item_name": "縣市加碼", "category": "other",
             "expected_amount": "3000", "status": "not_submitted"},
            {"item_name": "", "expected_amount": "0", "category": "", "status": "not_submitted"},
        ])
        self.assertEqual(response.status_code, 302)
        self.assertEqual(list(order.subsidy_items.values_list("item_name", "expected_amount")), [("縣市加碼", 3000)])


class TradeInCardLayoutTests(SubsidyPageHelpers):
    def test_people_on_top_vehicle_below(self):
        self.login_admin()
        order, _vehicle = self.make_order()
        SalesOrder.objects.filter(pk=order.pk).update(is_trade_in_subsidy=True, old_owner_same_as_owner=False)
        html = self.page(order)
        people = html.split('tradein-card__people', 1)[1].split('tradein-card__scrap', 1)[0]
        for name in ("old_owner_name", "old_owner_id_number", "old_owner_phone"):
            self.assertIn(f'name="{name}"', people)
        self.assertNotIn('name="trade_in_plate"', people)
        vehicle = html.split('tradein-card__vehicle', 1)[1]
        names = re.findall(r'name="(trade_in_plate|operations-old_vehicle_engine_number|operations-old_vehicle_brand|'
                           r'operations-old_vehicle_displacement_cc|operations-old_vehicle_manufactured_on|'
                           r'operations-scrapped_on|operations-recycled_on)"', vehicle)
        self.assertEqual(names[:7], ["trade_in_plate", "operations-old_vehicle_engine_number", "operations-old_vehicle_brand",
                                     "operations-old_vehicle_displacement_cc", "operations-old_vehicle_manufactured_on",
                                     "operations-scrapped_on", "operations-recycled_on"])
        # 車牌仍屬補助表單（跟著補助資料自動儲存），不是營運表單。
        plate = re.search(r'<input[^>]*name="trade_in_plate"[^>]*>', vehicle).group(0)
        self.assertNotIn('form="', plate)

    def test_plate_still_saves_with_subsidy_form(self):
        self.login_admin()
        order, _vehicle = self.make_order()
        self.client.post(reverse("subsidy_data_update", args=[order.pk]), {
            "_order_revision": str(order.revision), "trade_in_plate": "abc-1234", "old_owner_name": "",
            "old_owner_id_number": "", "old_owner_phone": ""})
        order.refresh_from_db()
        self.assertEqual(order.trade_in_plate, "ABC-1234")


class StandaloneOperationsPageTests(workspace_fixtures.OrderWorkspaceTests.__bases__[0]):
    @classmethod
    def setUpTestData(cls):
        workspace_fixtures.OrderWorkspaceTests.setUpTestData.__func__(cls)

    def setUp(self):
        self.client.force_login(self.admin)

    def test_subsidy_tracking_removed_and_values_kept_on_save(self):
        OrderOperationsProfile.objects.filter(order=self.order).update(bank_name="臺灣銀行", remittance_account="0123456789")
        response = self.client.get(reverse("order_operations", args=[self.order.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "補助撥款追蹤")
        self.assertNotContains(response, 'name="operations-bank_name"')
        self.assertNotContains(response, 'name="operations-remittance_account"')
        for gone in ("old_vehicle_valuation", "old_vehicle_tax", "old_owner_household_address"):
            self.assertNotContains(response, gone)
        profile = OrderOperationsProfile.objects.get(order=self.order)
        payload = {**form_data(OrderOperationsForm(instance=profile, prefix="operations", section="standalone")),
                   **formset_data(PaymentRecordFormSet(instance=self.order, prefix="payments"))}
        self.assertNotIn("operations-bank_name", payload)
        self.client.post(reverse("order_operations", args=[self.order.pk]), payload)
        profile.refresh_from_db()
        self.assertEqual((profile.bank_name, profile.remittance_account), ("臺灣銀行", "0123456789"))
