"""開單以外頁面放寬的必填（2026-10-14）：空白一律以安全預設值儲存。"""
from decimal import Decimal

from django.test import TestCase

from sales.forms import AccessoryLineForm, SubsidyDataForm, SubsidyItemForm
from sales.models import AccessoryProduct, SalesOrder, SubsidyItem, VehicleColor, VehicleModel


class OptionalFieldTests(TestCase):
    def setUp(self):
        model = VehicleModel.objects.create(brand="測試牌", name="選填車", energy_type=VehicleModel.EnergyType.GAS)
        color = VehicleColor.objects.create(vehicle_model=model, name="白")
        self.order = SalesOrder.objects.create(
            owner_type=SalesOrder.OwnerType.COMPANY, owner_name="測試有限公司", owner_id_number="12345678",
            vehicle_model=model, color=color,
        )

    def test_old_vehicle_amounts_default_to_zero(self):
        form = SubsidyDataForm({"is_trade_in_subsidy": "on", "trade_in_plate": "abc-1234", "old_owner_name": "",
                                "old_owner_id_number": "", "subsidy_type": "", "old_vehicle_valuation": "",
                                "old_vehicle_tax": ""}, instance=self.order)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual((form.cleaned_data["old_vehicle_valuation"], form.cleaned_data["old_vehicle_tax"]), (0, 0))
        self.assertEqual(form.cleaned_data["trade_in_plate"], "ABC-1234")

    def test_subsidy_item_amount_can_be_blank(self):
        form = SubsidyItemForm({"item_name": "縣市加碼補助", "expected_amount": "", "category": "",
                                "status": SubsidyItem.Status.NOT_SUBMITTED})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["expected_amount"], Decimal("0"))
        self.assertFalse(form.fields["expected_amount"].required)

    def test_custom_accessory_defaults_quantity_and_labor(self):
        form = AccessoryLineForm({"accessory_product": "other", "custom_name": "手機架", "quantity": "",
                                  "line_type": "purchase", "amount": "800", "labor_fee": ""}, allow_manual=True)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual((form.cleaned_data["quantity"], form.cleaned_data["labor_fee"]), (1, Decimal("0")))
        # 售價影響收費，仍須填寫。
        form = AccessoryLineForm({"accessory_product": "other", "custom_name": "手機架", "quantity": "1",
                                  "line_type": "purchase", "amount": "", "labor_fee": ""}, allow_manual=True)
        self.assertFalse(form.is_valid())
        self.assertIn("amount", form.errors)

    def test_catalog_accessory_blank_quantity_is_one(self):
        product = AccessoryProduct.objects.create(name="後箱", sale_price=1500, labor_fee=200)
        form = AccessoryLineForm({"accessory_product": str(product.pk), "quantity": "", "line_type": "purchase",
                                  "amount": "", "labor_fee": ""})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["quantity"], 1)
