from decimal import Decimal
from io import BytesIO

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from openpyxl import load_workbook

from sales.forms import OrderOperationsForm
from sales.models import OrderOperationsProfile, SalesOrder, SubsidyItem, VehicleColor, VehicleModel
from sales.services.subsidy_summary import agency_summary
from sales.tests.profit_helpers import unlock_profit

Status = SubsidyItem.Status
Category = SubsidyItem.Category


def item(category, status, amount):
    return SubsidyItem(category=category, status=status, expected_amount=Decimal(amount), item_name="測試")


class AgencySummaryTests(SimpleTestCase):
    def by_label(self, items):
        return {row["label"]: row for row in agency_summary(items)}

    def test_no_items_shows_three_agencies_without_progress(self):
        rows = agency_summary([])
        self.assertEqual([row["label"] for row in rows], ["工業局", "環境部", "地方政府"])
        self.assertTrue(all(row["count"] == 0 and row["text"] == "" for row in rows))

    def test_progress_wording_follows_item_status(self):
        rows = self.by_label([
            item(Category.INDUSTRY, Status.NOT_SUBMITTED, 8000),
            item(Category.ENVIRONMENT, Status.SUBMITTED, 1000),
            item(Category.ENVIRONMENT, Status.NOT_SUBMITTED, 2000),
            item(Category.LOCAL, Status.COMPLETED, 5000),
            item(Category.LOCAL, Status.SUBMITTED, 3000),
        ])
        self.assertEqual(rows["工業局"]["progress"], "尚未送出申請")
        self.assertEqual(rows["環境部"]["progress"], "已送出 1／2 筆")
        self.assertEqual(rows["環境部"]["total"], Decimal("3000"))
        self.assertEqual(rows["地方政府"]["progress"], "已送出申請")
        self.assertEqual(rows["地方政府"]["text"], "已送出申請（2 筆，合計 $8,000）")

    def test_all_completed_and_other_category(self):
        rows = self.by_label([
            item(Category.INDUSTRY, Status.COMPLETED, 100),
            item(Category.OTHER, Status.SUBMITTED, 50),
        ])
        self.assertEqual(rows["工業局"]["progress"], "已申請完成")
        self.assertEqual(rows["其他"]["count"], 1)
        self.assertNotIn("其他", self.by_label([]))


class AgencySummaryPageTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser("finance", password="Test-Only-123")
        model = VehicleModel.objects.create(brand="測試牌", name="補助車", energy_type=VehicleModel.EnergyType.ELECTRIC)
        color = VehicleColor.objects.create(vehicle_model=model, name="白")
        self.order = SalesOrder.objects.create(
            owner_name="測試車主", owner_phone="0912345678", owner_address="新北市", owner_id_number="A123456789",
            vehicle_model=model, color=color, is_trade_in_subsidy=True,
        )
        SubsidyItem.objects.create(order=self.order, category=Category.INDUSTRY, item_name="工業局購車補助",
                                   expected_amount=8000, status=Status.SUBMITTED)
        self.client.force_login(self.user)
        unlock_profit(self, self.user)

    def test_form_no_longer_offers_the_three_status_dropdowns(self):
        form = OrderOperationsForm(instance=OrderOperationsProfile.objects.get(order=self.order))
        for name in ("industry_bureau_status", "environment_ministry_status", "local_government_status"):
            self.assertNotIn(name, form.fields)

    def test_subsidy_tab_shows_summary_instead_of_dropdowns(self):
        page = self.client.get(reverse("order_detail", args=[self.order.pk]), {"tab": "subsidy"})
        self.assertContains(page, 'id="subsidy-agency-summary"')
        self.assertContains(page, "已送出申請")
        self.assertContains(page, "尚未登錄補助項目")  # 環境部、地方政府沒有項目
        self.assertNotContains(page, 'name="operations-industry_bureau_status"')
        self.assertNotContains(page, 'name="operations-local_government_status"')

    def test_saving_items_returns_refreshed_summary(self):
        post = {
            "_order_revision": str(self.order.revision), "_section": "subsidy", "_workspace": "1",
            "is_trade_in_subsidy": "on", "old_owner_same_as_owner": "on", "trade_in_plate": "ABC-1234",
            "old_vehicle_valuation": "0", "old_vehicle_tax": "0", "change_reason": "新增環境部補助",
            "subsidy_items-TOTAL_FORMS": "2", "subsidy_items-INITIAL_FORMS": "1",
            "subsidy_items-MIN_NUM_FORMS": "0", "subsidy_items-MAX_NUM_FORMS": "1000",
            "subsidy_items-0-id": str(self.order.subsidy_items.get().pk),
            "subsidy_items-0-item_name": "工業局購車補助", "subsidy_items-0-expected_amount": "8000",
            "subsidy_items-0-status": Status.SUBMITTED,
            "subsidy_items-1-item_name": "環境部汰舊補助", "subsidy_items-1-expected_amount": "3000",
            "subsidy_items-1-category": Category.ENVIRONMENT, "subsidy_items-1-status": Status.NOT_SUBMITTED,
        }
        response = self.client.post(
            reverse("subsidy_data_update", args=[self.order.pk]), post,
            HTTP_X_ORDER_WORKSPACE="1",
        )
        self.assertEqual(response.status_code, 200, response.content[:300])
        html = response.json()["subsidy_summary_html"]
        self.assertIn("尚未送出申請", html)
        self.assertIn("1 筆・合計 $3,000", html)

    def test_operations_export_uses_summary_text(self):
        response = self.client.get(reverse("operations_report_export"))
        self.assertEqual(response.status_code, 200)
        sheet = load_workbook(BytesIO(response.content)).active
        headers = [cell.value for cell in sheet[1]]
        self.assertIn("工業局補助進度", headers)
        self.assertNotIn("縣市政府", headers)
        row = [cell.value for cell in sheet[2]]
        self.assertEqual(row[headers.index("工業局補助進度")], "已送出申請（1 筆，合計 $8,000）")
        self.assertIn(row[headers.index("環境部補助進度")], ("", None))
