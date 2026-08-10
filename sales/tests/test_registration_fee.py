from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.test import SimpleTestCase
from django.urls import reverse

from sales.models import (
    AccessoryLine,
    BrandRegistrationFeeRule,
    OtherFeeLine,
    SalesOrder,
    VehicleColor,
    VehicleModel,
)
from sales.services.registration_fee import (
    UnsupportedRegistrationFee,
    calculate_registration_fee,
    calculate_vehicle_registration_fee,
)


class RegistrationFeeCalculatorTests(SimpleTestCase):
    def test_m2_matches_july_29_monitoring_receipt(self):
        result = calculate_registration_fee(125, date(2026, 7, 29), 1)

        self.assertEqual(result.rate_class, "M2")
        self.assertEqual(result.standard_remaining_days, 152)
        self.assertEqual(result.road_maintenance_fee, 190)
        self.assertEqual(result.license_tax_fee, 0)
        self.assertEqual(result.compulsory_insurance_fee, 658)
        self.assertEqual(
            result.fixed_and_variable_total,
            1498,
        )

    def test_m2_matches_july_28_monitoring_receipt(self):
        result = calculate_registration_fee(125, date(2026, 7, 28), 1)

        self.assertEqual(result.road_maintenance_fee, 191)
        self.assertEqual(
            result.plate_fee
            + result.license_fee
            + result.inspection_fee
            + result.road_maintenance_fee
            + result.license_tax_fee,
            841,
        )

    def test_m3_license_tax_boundary(self):
        cc_150 = calculate_registration_fee(150, date(2026, 1, 1), 1)
        cc_151 = calculate_registration_fee(151, date(2026, 1, 1), 1)

        self.assertEqual(cc_150.license_tax_fee, 0)
        self.assertEqual(cc_151.license_tax_fee, 800)

    def test_m5_plate_fee_boundary(self):
        cc_549 = calculate_registration_fee(549, date(2026, 1, 1), 1)
        cc_550 = calculate_registration_fee(550, date(2026, 1, 1), 1)

        self.assertEqual(cc_549.plate_fee, 300)
        self.assertEqual(cc_550.plate_fee, 400)

    def test_large_heavy_motorcycle_insurance(self):
        one_year = calculate_registration_fee(251, date(2026, 1, 1), 1)
        two_years = calculate_registration_fee(251, date(2026, 1, 1), 2)

        self.assertEqual(one_year.compulsory_insurance_fee, 711)
        self.assertEqual(two_years.compulsory_insurance_fee, 1306)

    def test_license_tax_uses_leap_year_calendar_days(self):
        result = calculate_registration_fee(151, date(2028, 7, 1), 1)

        self.assertEqual(result.calendar_remaining_days, 184)
        self.assertEqual(result.license_tax_fee, 402)

    def test_day_31_is_treated_as_day_30_for_360_day_basis(self):
        result = calculate_registration_fee(125, date(2026, 12, 31), 1)

        self.assertEqual(result.standard_remaining_days, 1)
        self.assertEqual(result.road_maintenance_fee, 1)

    def test_out_of_scope_displacement_is_rejected(self):
        with self.assertRaises(UnsupportedRegistrationFee):
            calculate_registration_fee(50, date(2026, 7, 29), 1)


class RegistrationFeeOrderIntegrationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="fee-tester", password="test-pass-123"
        )
        self.model = VehicleModel.objects.create(
            brand="測試廠牌",
            name="通勤 125",
            energy_type=VehicleModel.EnergyType.GAS,
            displacement_cc=125,
        )
        self.color = VehicleColor.objects.create(
            vehicle_model=self.model,
            name="白",
        )

    def test_order_detail_displays_registration_fee_breakdown(self):
        order = SalesOrder.objects.create(
            owner_type=SalesOrder.OwnerType.COMPANY,
            owner_name="測試有限公司",
            owner_phone="0912345678",
            owner_address="新北市",
            owner_id_number="12345678",
            vehicle_model=self.model,
            color=self.color,
            id_verified=True,
            registration_date=date(2026, 7, 29),
            registration_rate_class="M2",
            registration_plate_fee=300,
            registration_license_fee=150,
            registration_inspection_fee=200,
            road_maintenance_fee=190,
            compulsory_insurance_fee=658,
            registration_calculated_total=1498,
            plate_insurance_fee=1498,
        )
        AccessoryLine.objects.create(
            order=order,
            name="手機架",
            quantity=1,
            amount=850,
        )
        OtherFeeLine.objects.create(order=order, name="代辦費", amount=300)
        order.calculated_balance = order.calculate_balance()
        order.actual_balance = order.calculated_balance
        order.save(update_fields=["calculated_balance", "actual_balance"])
        self.client.force_login(self.user)

        response = self.client.get(reverse("order_detail", args=[order.pk]))

        self.assertContains(response, 'class="registration-breakdown"')
        self.assertContains(response, "領牌試算")
        self.assertContains(response, "公路養管")
        self.assertContains(response, "$190")
        self.assertContains(response, "試算合計")
        self.assertContains(response, "$1,498")
        self.assertContains(response, "尾款計算")
        self.assertContains(response, "配件與其他費用均已計入")
        self.assertContains(response, "配件合計 $850")
        self.assertContains(response, "加購 · 售價 $850 ＋ 工資 $0 · 已計入尾款")

    def test_brand_fixed_fee_rule_uses_registration_date_and_displacement(self):
        BrandRegistrationFeeRule.objects.create(
            brand="測試廠牌",
            calculation_type=BrandRegistrationFeeRule.CalculationType.FIXED,
            min_cc=51,
            max_cc=125,
            fixed_total=1888,
            insurance_period_years=1,
            effective_from=date(2026, 8, 1),
        )

        before = calculate_vehicle_registration_fee(
            self.model, date(2026, 7, 31), 1
        )
        after = calculate_vehicle_registration_fee(
            self.model, date(2026, 8, 1), 1
        )

        self.assertEqual(before.pricing_method, "formula")
        self.assertEqual(after.pricing_method, "fixed")
        self.assertEqual(after.fixed_and_variable_total, 1888)

    def test_manual_brand_rule_requires_actual_receipt_entry(self):
        BrandRegistrationFeeRule.objects.create(
            brand="測試廠牌",
            calculation_type=BrandRegistrationFeeRule.CalculationType.MANUAL,
            effective_from=date(2026, 1, 1),
        )

        with self.assertRaisesMessage(UnsupportedRegistrationFee, "人工牌險"):
            calculate_vehicle_registration_fee(self.model, date(2026, 8, 1), 1)

    def test_registration_fee_rule_maintenance_page(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("brand_registration_fee_rule_list"),
            {
                "brand": "三陽",
                "calculation_type": "fixed",
                "min_cc": 51,
                "max_cc": 125,
                "fixed_total": 1600,
                "insurance_period_years": 1,
                "effective_from": "2026-08-01",
                "effective_to": "",
                "active": "on",
                "note": "依原廠總額",
            },
        )

        self.assertRedirects(response, reverse("brand_registration_fee_rule_list"))
        self.assertTrue(
            BrandRegistrationFeeRule.objects.filter(brand="三陽", fixed_total=1600).exists()
        )
