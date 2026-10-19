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
    registration_rate_label,
)
from sales.forms import BrandRegistrationFeeRuleForm, RegistrationStageForm


class RegistrationFeeCalculatorTests(SimpleTestCase):
    def test_internal_rate_code_is_displayed_as_displacement_range(self):
        self.assertEqual(registration_rate_label("M2"), "51～125 c.c.")
        self.assertEqual(registration_rate_label("M5"), "501～600 c.c.")
        self.assertEqual(
            registration_rate_label("FIXED-BUNDLE-1", 249),
            "126～250 c.c.",
        )
        self.assertEqual(registration_rate_label("EV-LIGHT"), "")

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
        self.assertContains(response, "51～125 c.c.")
        self.assertNotContains(response, " · M2 · ")
        self.assertContains(response, "公路養管")
        self.assertContains(response, "$190")
        self.assertContains(response, "試算合計")
        self.assertContains(response, "$1,498")
        self.assertContains(response, "尾款計算")
        self.assertContains(response, "配件與其他費用均已計入")
        # 1.82.0：配件改在訂單頁的訂單表單直接編輯，原本的唯讀配件卡由表單取代。
        self.assertContains(response, 'id="order-form"')
        self.assertContains(response, 'value="850"')

    def test_brand_fixed_fee_rule_uses_registration_date_and_displacement(self):
        BrandRegistrationFeeRule.objects.create(
            brand="測試廠牌",
            calculation_type=BrandRegistrationFeeRule.CalculationType.FIXED_BUNDLE,
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
        self.assertEqual(after.pricing_method, "fixed_bundle")
        self.assertEqual(after.fixed_and_variable_total, 1888)

    def test_fixed_rule_rate_class_fits_order_field_for_large_rule_ids(self):
        # 查修 08AF2319AB18：規則編號兩位數時舊代碼「FIXED-BUNDLE-10」超過 10 字，儲存領牌資料 500。
        max_length = SalesOrder._meta.get_field("registration_rate_class").max_length
        for calculation_type, extra in (
            (BrandRegistrationFeeRule.CalculationType.FIXED_BUNDLE, {"fixed_total": 1888}),
            (BrandRegistrationFeeRule.CalculationType.FIXED_COMPONENTS, {"fixed_registration_fee": 900, "fixed_compulsory_insurance_fee": 500}),
        ):
            with self.subTest(calculation_type=calculation_type):
                BrandRegistrationFeeRule.objects.all().delete()
                rule = BrandRegistrationFeeRule.objects.create(
                    pk=12345, brand="測試廠牌", calculation_type=calculation_type, min_cc=51, max_cc=125,
                    insurance_period_years=1, effective_from=date(2026, 8, 1), **extra,
                )
                result = calculate_vehicle_registration_fee(self.model, date(2026, 8, 1), 1)
                self.assertLessEqual(len(result.rate_class), max_length)
                self.assertTrue(result.rate_class.endswith(str(rule.pk)))

    def test_manual_brand_rule_requires_actual_receipt_entry(self):
        BrandRegistrationFeeRule.objects.create(
            brand="測試廠牌",
            calculation_type=BrandRegistrationFeeRule.CalculationType.MANUAL,
            effective_from=date(2026, 1, 1),
        )

        for insurance_period in (1, 2):
            with self.subTest(insurance_period=insurance_period):
                with self.assertRaisesMessage(UnsupportedRegistrationFee, "人工牌險"):
                    calculate_vehicle_registration_fee(
                        self.model, date(2026, 8, 1), insurance_period
                    )

    def test_manual_brand_rule_allows_registration_and_preserves_actual_amount(self):
        BrandRegistrationFeeRule.objects.create(
            brand="測試廠牌",
            calculation_type=BrandRegistrationFeeRule.CalculationType.MANUAL,
            effective_from=date(2026, 1, 1),
        )
        order = SalesOrder.objects.create(
            owner_name="人工牌險測試",
            owner_phone="0911222333",
            owner_address="新北市",
            owner_id_number="A123456789",
            vehicle_model=self.model,
            color=self.color,
            plate_insurance_fee=1358,
            balance_adjustment_reason="人工牌險依單據輸入",
        )
        form = RegistrationStageForm(
            {
                "registration_date": "2026-08-13",
                "registration_county": "新北市",
                "final_plate_number": "abc-1234",
            },
            instance=order,
        )

        self.assertTrue(form.is_valid(), form.errors)
        saved = form.save()
        self.assertEqual(saved.registration_rate_class, "MANUAL")
        self.assertEqual(saved.registration_calculated_total, 0)
        self.assertEqual(saved.plate_insurance_fee, 1358)

    def test_electric_fixed_rule_uses_registration_class_and_splits_fees(self):
        electric_model = VehicleModel.objects.create(
            brand="Gogoro",
            name="VIVA",
            energy_type=VehicleModel.EnergyType.ELECTRIC,
            electric_registration_class=VehicleModel.ElectricRegistrationClass.LIGHT,
        )
        rule = BrandRegistrationFeeRule.objects.create(
            brand="Gogoro",
            energy_type=VehicleModel.EnergyType.ELECTRIC,
            electric_registration_class=VehicleModel.ElectricRegistrationClass.LIGHT,
            calculation_type=BrandRegistrationFeeRule.CalculationType.FIXED_COMPONENTS,
            fixed_registration_fee=550,
            fixed_compulsory_insurance_fee=658,
            insurance_period_years=1,
            effective_from=date(2026, 1, 1),
        )

        result = calculate_vehicle_registration_fee(
            electric_model, date(2026, 8, 13), 1
        )

        rule.refresh_from_db()
        self.assertEqual(result.rate_class, "EV-LIGHT")
        self.assertEqual(result.plate_fee, 550)
        self.assertEqual(result.compulsory_insurance_fee, 658)
        self.assertEqual(result.fixed_and_variable_total, 1208)
        self.assertEqual(rule.fixed_total, 1208)

    def test_light_electric_vehicle_can_reuse_existing_light_electric_rule(self):
        light_electric_model = VehicleModel(
            brand="Gogoro",
            name="輕型電動測試",
            energy_type=VehicleModel.EnergyType.LIGHT_ELECTRIC,
        )
        light_electric_model.full_clean()
        light_electric_model.save()
        BrandRegistrationFeeRule.objects.create(
            brand="Gogoro",
            energy_type=VehicleModel.EnergyType.ELECTRIC,
            electric_registration_class=VehicleModel.ElectricRegistrationClass.LIGHT,
            calculation_type=BrandRegistrationFeeRule.CalculationType.FIXED_COMPONENTS,
            fixed_registration_fee=550,
            fixed_compulsory_insurance_fee=658,
            effective_from=date(2026, 1, 1),
        )

        result = calculate_vehicle_registration_fee(
            light_electric_model, date(2026, 8, 13), 1
        )

        self.assertEqual(result.rate_class, "EV-LIGHT")
        self.assertEqual(result.fixed_and_variable_total, 1208)

    def test_light_electric_specific_rule_takes_priority_over_generic_electric_rule(self):
        light_electric_model = VehicleModel(
            brand="Gogoro",
            name="輕型電動專屬規則測試",
            energy_type=VehicleModel.EnergyType.LIGHT_ELECTRIC,
        )
        light_electric_model.full_clean()
        light_electric_model.save()
        for energy_type, registration_fee in (
            (VehicleModel.EnergyType.ELECTRIC, 550),
            (VehicleModel.EnergyType.LIGHT_ELECTRIC, 600),
        ):
            BrandRegistrationFeeRule.objects.create(
                brand="Gogoro",
                energy_type=energy_type,
                electric_registration_class=VehicleModel.ElectricRegistrationClass.LIGHT,
                calculation_type=BrandRegistrationFeeRule.CalculationType.FIXED_COMPONENTS,
                fixed_registration_fee=registration_fee,
                fixed_compulsory_insurance_fee=658,
                effective_from=date(2026, 1, 1),
            )

        result = calculate_vehicle_registration_fee(
            light_electric_model, date(2026, 8, 13), 1
        )

        self.assertEqual(result.plate_fee, 600)
        self.assertEqual(result.fixed_and_variable_total, 1258)

    def test_electric_rule_does_not_cross_light_and_heavy_classes(self):
        electric_model = VehicleModel.objects.create(
            brand="Gogoro",
            name="SuperSport",
            energy_type=VehicleModel.EnergyType.ELECTRIC,
            electric_registration_class=VehicleModel.ElectricRegistrationClass.HEAVY,
        )
        BrandRegistrationFeeRule.objects.create(
            brand="Gogoro",
            energy_type=VehicleModel.EnergyType.ELECTRIC,
            electric_registration_class=VehicleModel.ElectricRegistrationClass.LIGHT,
            calculation_type=BrandRegistrationFeeRule.CalculationType.FIXED_COMPONENTS,
            fixed_registration_fee=550,
            fixed_compulsory_insurance_fee=658,
            effective_from=date(2026, 1, 1),
        )

        with self.assertRaisesMessage(UnsupportedRegistrationFee, "尚未建立有效牌險規則"):
            calculate_vehicle_registration_fee(
                electric_model, date(2026, 8, 13), 1
            )

    def test_parent_brand_fee_rule_does_not_cross_into_child_brand(self):
        electric_model = VehicleModel.objects.create(
            brand="eMOVING",
            name="EZ1",
            energy_type=VehicleModel.EnergyType.ELECTRIC,
            electric_registration_class=VehicleModel.ElectricRegistrationClass.LIGHT,
        )
        BrandRegistrationFeeRule.objects.create(
            brand="SUZUKI",
            energy_type=VehicleModel.EnergyType.ELECTRIC,
            electric_registration_class=VehicleModel.ElectricRegistrationClass.LIGHT,
            calculation_type=BrandRegistrationFeeRule.CalculationType.FIXED_COMPONENTS,
            fixed_registration_fee=550,
            fixed_compulsory_insurance_fee=658,
            effective_from=date(2026, 1, 1),
        )

        with self.assertRaisesMessage(UnsupportedRegistrationFee, "尚未建立有效牌險規則"):
            calculate_vehicle_registration_fee(
                electric_model, date(2026, 8, 13), 1
            )

    def test_electric_registration_stage_saves_split_fee_snapshot(self):
        electric_model = VehicleModel.objects.create(
            brand="Gogoro",
            name="VIVA MIX",
            energy_type=VehicleModel.EnergyType.ELECTRIC,
            electric_registration_class=VehicleModel.ElectricRegistrationClass.LIGHT,
        )
        color = VehicleColor.objects.create(vehicle_model=electric_model, name="白")
        BrandRegistrationFeeRule.objects.create(
            brand="Gogoro",
            energy_type=VehicleModel.EnergyType.ELECTRIC,
            electric_registration_class=VehicleModel.ElectricRegistrationClass.LIGHT,
            calculation_type=BrandRegistrationFeeRule.CalculationType.FIXED_COMPONENTS,
            fixed_registration_fee=550,
            fixed_compulsory_insurance_fee=658,
            effective_from=date(2026, 1, 1),
        )
        order = SalesOrder.objects.create(
            owner_name="電動車領牌測試",
            owner_phone="0911222333",
            owner_address="新北市",
            owner_id_number="A123456789",
            vehicle_model=electric_model,
            color=color,
            vehicle_price=50000,
            plate_insurance_auto=True,
        )
        form = RegistrationStageForm(
            {
                "registration_date": "2026-08-13",
                "registration_county": "新北市",
                "final_plate_number": "abc-1234",
            },
            instance=order,
        )

        self.assertTrue(form.is_valid(), form.errors)
        saved = form.save()

        self.assertEqual(saved.registration_rate_class, "EV-LIGHT")
        self.assertEqual(saved.registration_plate_fee, 550)
        self.assertEqual(saved.compulsory_insurance_fee, 658)
        self.assertEqual(saved.registration_calculated_total, 1208)
        self.assertEqual(saved.plate_insurance_fee, 1208)

    def micro_electric_order(self, brand="BOBE", **extra):
        model = VehicleModel.objects.create(
            brand=brand,
            name="微電測試",
            energy_type=VehicleModel.EnergyType.MICRO_ELECTRIC,
        )
        color = VehicleColor.objects.create(vehicle_model=model, name="白")
        reason = "人工牌險依單據輸入" if extra else ""
        # 沒有指定牌險費＝建單時留空、照系統試算（使用者 2026-10-19）。
        extra.setdefault("plate_insurance_auto", "plate_insurance_fee" not in extra)
        return SalesOrder.objects.create(
            owner_name="微電車領牌測試",
            owner_phone="0911222333",
            owner_address="新北市",
            owner_id_number="A123456789",
            vehicle_model=model,
            color=color,
            vehicle_price=30000,
            balance_adjustment_reason=reason,
            **extra,
        )

    def register(self, order):
        form = RegistrationStageForm(
            {
                "registration_date": "2026-10-14",
                "registration_county": "新北市",
                "final_plate_number": "abc-1234",
            },
            instance=order,
        )
        self.assertTrue(form.is_valid(), form.errors)
        return form.save()

    def test_micro_electric_registration_stage_uses_brand_rule(self):
        order = self.micro_electric_order()
        BrandRegistrationFeeRule.objects.create(
            brand="BOBE",
            energy_type=VehicleModel.EnergyType.MICRO_ELECTRIC,
            calculation_type=BrandRegistrationFeeRule.CalculationType.FIXED_COMPONENTS,
            fixed_registration_fee=300,
            fixed_compulsory_insurance_fee=500,
            insurance_period_years=3,  # 微電車一定保三年（2026-10-15）
            effective_from=date(2026, 1, 1),
        )

        saved = self.register(order)

        self.assertEqual(saved.registration_rate_class, "EV-MICRO")
        self.assertLessEqual(
            len(saved.registration_rate_class),
            SalesOrder._meta.get_field("registration_rate_class").max_length,
        )
        self.assertEqual(saved.registration_plate_fee, 300)
        self.assertEqual(saved.compulsory_insurance_fee, 500)
        self.assertEqual(saved.registration_calculated_total, 800)
        self.assertEqual(saved.plate_insurance_fee, 800)

    def test_micro_electric_fixed_bundle_rate_class_fits_order_field(self):
        order = self.micro_electric_order()
        BrandRegistrationFeeRule.objects.create(
            brand="BOBE",
            energy_type=VehicleModel.EnergyType.MICRO_ELECTRIC,
            calculation_type=BrandRegistrationFeeRule.CalculationType.FIXED_BUNDLE,
            fixed_total=900,
            insurance_period_years=3,  # 微電車一定保三年（2026-10-15）
            effective_from=date(2026, 1, 1),
        )

        saved = self.register(order)

        self.assertEqual(saved.registration_rate_class, "EV-MICRO")
        self.assertEqual(saved.plate_insurance_fee, 900)

    def test_micro_electric_without_rule_keeps_manual_plate_fee(self):
        order = self.micro_electric_order(plate_insurance_fee=1500)
        # 其他品牌或尚未生效的規則都不算符合。
        BrandRegistrationFeeRule.objects.create(
            brand="eMOVING",
            energy_type=VehicleModel.EnergyType.MICRO_ELECTRIC,
            calculation_type=BrandRegistrationFeeRule.CalculationType.FIXED_BUNDLE,
            fixed_total=900,
            insurance_period_years=1,
            effective_from=date(2026, 1, 1),
        )
        BrandRegistrationFeeRule.objects.create(
            brand="BOBE",
            energy_type=VehicleModel.EnergyType.MICRO_ELECTRIC,
            calculation_type=BrandRegistrationFeeRule.CalculationType.FIXED_BUNDLE,
            fixed_total=1200,
            insurance_period_years=1,
            effective_from=date(2027, 1, 1),
        )

        saved = self.register(order)

        self.assertEqual(saved.registration_rate_class, "")
        self.assertEqual(saved.registration_calculated_total, 0)
        self.assertEqual(saved.plate_insurance_fee, 1500)
        self.assertEqual(saved.compulsory_insurance_period, 3, "微電車一定保三年")

    def test_micro_electric_adopts_the_only_rule_period(self):
        order = self.micro_electric_order()
        BrandRegistrationFeeRule.objects.create(
            brand="BOBE",
            energy_type=VehicleModel.EnergyType.MICRO_ELECTRIC,
            calculation_type=BrandRegistrationFeeRule.CalculationType.FIXED_BUNDLE,
            fixed_total=2300,
            insurance_period_years=3,
            effective_from=date(2026, 10, 1),
        )

        saved = self.register(order)

        self.assertEqual(saved.compulsory_insurance_period, 3)
        self.assertEqual(saved.get_compulsory_insurance_period_display(), "三年")
        self.assertEqual(saved.plate_insurance_fee, 2300)
        self.assertEqual(saved.registration_bundle_fee, 2300)

    def test_rule_period_is_not_guessed_when_brand_has_several_periods(self):
        # 微電車固定三年（2026-10-15），改以重型電動車驗證多種年期時不猜年期。
        model = VehicleModel.objects.create(
            brand="BOBE", name="重型電動測試", energy_type=VehicleModel.EnergyType.ELECTRIC,
            electric_registration_class=VehicleModel.ElectricRegistrationClass.HEAVY,
        )
        color = VehicleColor.objects.create(vehicle_model=model, name="白")
        order = SalesOrder.objects.create(
            owner_name="電動車領牌測試", owner_phone="0911222333", owner_address="新北市",
            owner_id_number="A123456789", vehicle_model=model, color=color, vehicle_price=30000,
            plate_insurance_fee=1500, balance_adjustment_reason="人工牌險依單據輸入",
        )
        for years, total in ((2, 1800), (3, 2300)):
            BrandRegistrationFeeRule.objects.create(
                brand="BOBE",
                energy_type=VehicleModel.EnergyType.ELECTRIC,
                electric_registration_class=VehicleModel.ElectricRegistrationClass.HEAVY,
                calculation_type=BrandRegistrationFeeRule.CalculationType.FIXED_BUNDLE,
                fixed_total=total,
                insurance_period_years=years,
                effective_from=date(2026, 1, 1),
            )

        from sales.services.registration_fee import registration_period_for

        self.assertEqual(registration_period_for(model, date(2026, 10, 14), 1), 1)
        self.assertEqual(order.plate_insurance_fee, 1500)

    def test_micro_electric_rule_keeps_existing_manual_plate_fee(self):
        order = self.micro_electric_order(plate_insurance_fee=1500)
        BrandRegistrationFeeRule.objects.create(
            brand="BOBE",
            energy_type=VehicleModel.EnergyType.MICRO_ELECTRIC,
            calculation_type=BrandRegistrationFeeRule.CalculationType.FIXED_BUNDLE,
            fixed_total=900,
            insurance_period_years=3,  # 微電車一定保三年（2026-10-15）
            effective_from=date(2026, 1, 1),
        )

        saved = self.register(order)

        self.assertEqual(saved.registration_calculated_total, 900)
        self.assertEqual(saved.plate_insurance_fee, 1500)

    def edit_order(self, order, **changes):
        from sales.forms import SalesOrderForm
        from sales.tests.test_order_workspace import form_data

        data = form_data(SalesOrderForm(instance=order))
        data.update(changes)
        form = SalesOrderForm(data=data, instance=order)
        return form

    def gas_order(self, **extra):
        fields = dict(
            owner_type=SalesOrder.OwnerType.COMPANY, owner_name="油車手填測試", owner_phone="0912345678",
            owner_address="新北市", owner_id_number="12345678", vehicle_model=self.model, color=self.color,
            vehicle_price=70000, order_date=date(2026, 10, 14),
        )
        fields.update(extra)
        return SalesOrder.objects.create(**fields)

    def test_gas_plate_fee_is_manual_and_insurance_follows_period(self):
        order = self.gas_order()
        form = self.edit_order(order, plate_insurance_fee="3000", compulsory_insurance_period="2",
                               plate_choice="watch", plate_selection_fee="1500")
        self.assertTrue(form.is_valid(), form.errors)
        saved = form.save(commit=False)
        # 未排領牌日：規費依訂單日預估、強制險依排氣量與年期（使用者 2026-10-19）；牌險照人員輸入，選號費另收。
        self.assertEqual(saved.compulsory_insurance_fee, 1200)
        self.assertGreater(saved.registration_calculated_total, 1200)
        self.assertEqual(saved.plate_insurance_fee, 3000)
        self.assertFalse(saved.plate_insurance_auto)
        self.assertEqual(saved.plate_selection_fee, 1500)
        form = self.edit_order(order, plate_insurance_fee="3000", registration_date="2026-10-14")
        self.assertTrue(form.is_valid(), form.errors)
        saved = form.save(commit=False)
        self.assertGreater(saved.registration_calculated_total, 0)
        self.assertEqual(saved.plate_insurance_fee, 3000, "油車試算不覆蓋人員輸入的牌險")

    @staticmethod
    def save_with_balance(form):
        # 與訂單編輯頁相同：存檔前依新金額重算尾款。
        order = form.save(commit=False)
        order.calculated_balance = order.actual_balance = order.calculate_balance()
        order.save()
        return order

    def test_gas_plate_fee_three_states(self):
        """牌險費空白＝照系統試算、0＝不向客人收、正數＝照填（使用者 2026-10-19）。"""
        from sales.forms import SalesOrderForm

        order = self.gas_order()
        form = self.edit_order(order, plate_insurance_fee="")
        self.assertTrue(form.is_valid(), form.errors)
        saved = self.save_with_balance(form)
        # 沒有領牌日：依訂單日 2026-10-14 預估，牌險費＝規費＋強制險。
        self.assertTrue(saved.plate_insurance_auto)
        self.assertGreater(saved.registration_calculated_total, 0)
        self.assertEqual(saved.plate_insurance_fee, saved.registration_calculated_total)
        estimated = saved.plate_insurance_fee
        self.assertEqual(saved.calculate_balance(), 70000 + estimated)
        # 照試算的訂單編輯時欄位留空，試算值只當提示。
        page_form = SalesOrderForm(instance=saved)
        self.assertIsNone(page_form.initial["plate_insurance_fee"])
        self.assertIn(f"{estimated:,.0f}", page_form.fields["plate_insurance_fee"].widget.attrs["placeholder"])
        # 領牌時依領牌日重算（年底領牌，牌照稅與養管費天數較少）。
        registered = RegistrationStageForm(
            {"registration_date": "2026-12-20", "final_plate_number": "abc-1234"}, instance=saved,
        )
        self.assertTrue(registered.is_valid(), registered.errors)
        registered = registered.save()
        self.assertEqual(registered.plate_insurance_fee, registered.registration_calculated_total)
        self.assertLess(registered.plate_insurance_fee, estimated)
        self.assertEqual(registered.actual_balance, 70000 + registered.plate_insurance_fee)

        waived = self.gas_order()
        form = self.edit_order(waived, plate_insurance_fee="0")
        self.assertTrue(form.is_valid(), form.errors)
        waived = self.save_with_balance(form)
        self.assertFalse(waived.plate_insurance_auto)
        self.assertEqual(waived.plate_insurance_fee, 0)
        self.assertEqual(SalesOrderForm(instance=waived).initial["plate_insurance_fee"], 0)
        registered = RegistrationStageForm(
            {"registration_date": "2026-10-20", "final_plate_number": "abc-5678"}, instance=waived,
        )
        self.assertTrue(registered.is_valid(), registered.errors)
        registered = registered.save()
        self.assertGreater(registered.registration_calculated_total, 0)
        self.assertEqual(registered.plate_insurance_fee, 0, "填 0 不向客人收，領牌時不被試算蓋掉")

    def test_micro_electric_insurance_period_is_always_three_years(self):
        order = self.micro_electric_order(order_date=date(2026, 10, 14))
        form = self.edit_order(order, compulsory_insurance_period="1", plate_insurance_fee="2300")
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save(commit=False).compulsory_insurance_period, 3)

    def test_order_edit_fills_micro_electric_plate_fee_before_registration(self):
        BrandRegistrationFeeRule.objects.create(
            brand="BOBE",
            energy_type=VehicleModel.EnergyType.MICRO_ELECTRIC,
            calculation_type=BrandRegistrationFeeRule.CalculationType.FIXED_BUNDLE,
            fixed_total=2300,
            insurance_period_years=3,
            effective_from=date(2026, 1, 1),
        )
        for registration_date in ("", "2026-10-14"):
            with self.subTest(registration_date=registration_date):
                order = self.micro_electric_order(order_date=date(2026, 10, 14))
                form = self.edit_order(
                    order,
                    registration_date=registration_date,
                    plate_choice="watch",
                    plate_selection_fee="1200",
                    plate_insurance_fee="",
                )

                self.assertTrue(form.is_valid(), form.errors)
                saved = form.save(commit=False)
                self.assertEqual(saved.compulsory_insurance_period, 3)
                # 牌險不含選號（2026-10-15）：選號 1,200 另收、另計入總價。
                self.assertEqual(saved.registration_calculated_total, 2300)
                self.assertEqual(saved.plate_insurance_fee, 2300)
                self.assertEqual(saved.registration_extra_fee_total, 1200)
                self.assertEqual(saved.registration_rate_class, "EV-MICRO")

    def test_order_edit_keeps_manual_micro_electric_plate_fee(self):
        BrandRegistrationFeeRule.objects.create(
            brand="BOBE",
            energy_type=VehicleModel.EnergyType.MICRO_ELECTRIC,
            calculation_type=BrandRegistrationFeeRule.CalculationType.FIXED_BUNDLE,
            fixed_total=2300,
            insurance_period_years=3,
            effective_from=date(2026, 1, 1),
        )
        order = self.micro_electric_order(order_date=date(2026, 10, 14))
        form = self.edit_order(order, plate_insurance_fee="2600")

        self.assertTrue(form.is_valid(), form.errors)
        saved = form.save(commit=False)
        self.assertEqual(saved.registration_calculated_total, 2300)
        self.assertEqual(saved.plate_insurance_fee, 2600)

    def test_order_edit_without_micro_rule_keeps_selection_fee_separate(self):
        order = self.micro_electric_order(order_date=date(2026, 10, 14))
        form = self.edit_order(
            order, plate_choice="watch", plate_selection_fee="1200", plate_insurance_fee="0"
        )

        self.assertTrue(form.is_valid(), form.errors)
        saved = form.save(commit=False)
        self.assertEqual(saved.registration_rate_class, "")
        # 沒有規則時牌險依人員輸入；選號不再併進牌險（2026-10-15）。
        self.assertEqual(saved.plate_insurance_fee, 0)
        self.assertEqual(saved.registration_calculated_total, 0)
        self.assertEqual(saved.plate_selection_fee, 1200)

    def test_electric_fixed_rule_fills_before_registration_date(self):
        electric_model = VehicleModel.objects.create(
            brand="Gogoro",
            name="建單帶入測試",
            energy_type=VehicleModel.EnergyType.ELECTRIC,
            electric_registration_class=VehicleModel.ElectricRegistrationClass.LIGHT,
        )
        color = VehicleColor.objects.create(vehicle_model=electric_model, name="白")
        BrandRegistrationFeeRule.objects.create(
            brand="Gogoro",
            energy_type=VehicleModel.EnergyType.ELECTRIC,
            electric_registration_class=VehicleModel.ElectricRegistrationClass.LIGHT,
            calculation_type=BrandRegistrationFeeRule.CalculationType.FIXED_COMPONENTS,
            fixed_registration_fee=550,
            fixed_compulsory_insurance_fee=658,
            insurance_period_years=1,
            effective_from=date(2026, 1, 1),
        )
        order = SalesOrder.objects.create(
            owner_name="電動車建單測試",
            owner_phone="0911222333",
            owner_address="新北市",
            owner_id_number="A123456789",
            vehicle_model=electric_model,
            color=color,
            vehicle_price=50000,
            order_date=date(2026, 10, 14),
        )
        form = self.edit_order(order, plate_insurance_fee="")

        self.assertTrue(form.is_valid(), form.errors)
        saved = form.save(commit=False)
        self.assertEqual(saved.registration_rate_class, "EV-LIGHT")
        self.assertEqual(saved.plate_insurance_fee, 1208)

    def test_gas_order_cannot_choose_three_year_insurance(self):
        order = SalesOrder.objects.create(
            owner_name="油車三年測試",
            owner_phone="0911222333",
            owner_address="新北市",
            owner_id_number="A123456789",
            vehicle_model=self.model,
            color=self.color,
            vehicle_price=50000,
        )
        form = self.edit_order(order, compulsory_insurance_period="3")

        self.assertFalse(form.is_valid())
        self.assertIn("compulsory_insurance_period", form.errors)

    def test_registration_fee_rule_maintenance_page(self):
        self.client.force_login(self.user)

        page = self.client.get(reverse("brand_registration_fee_rule_list"))
        self.assertContains(page, "公式計算")
        self.assertContains(page, "固定整包金額")
        self.assertContains(page, "固定分項金額")
        self.assertContains(page, "人工輸入")

        response = self.client.post(
            reverse("brand_registration_fee_rule_list"),
            {
                "brand": "SYM",
                "energy_type": "gas",
                "electric_registration_class": "",
                "calculation_type": "fixed_bundle",
                "min_cc": 51,
                "max_cc": 125,
                "fixed_total": 1600,
                "fixed_registration_fee": 0,
                "fixed_compulsory_insurance_fee": 0,
                "insurance_period_years": 1,
                "effective_from": "2026-08-01",
                "effective_to": "",
                "active": "on",
                "note": "依原廠總額",
            },
        )

        self.assertRedirects(response, reverse("brand_registration_fee_rule_list"))
        self.assertTrue(
            BrandRegistrationFeeRule.objects.filter(brand="SYM", fixed_total=1600).exists()
        )

    def test_registration_fee_rule_list_uses_readable_summary_cards(self):
        BrandRegistrationFeeRule.objects.create(
            brand="eMOVING",
            energy_type=VehicleModel.EnergyType.MICRO_ELECTRIC,
            calculation_type=BrandRegistrationFeeRule.CalculationType.FIXED_BUNDLE,
            fixed_total=2300,
            insurance_period_years=3,
            effective_from=date(2026, 1, 1),
            note="微型電動二輪車固定牌險",
        )
        BrandRegistrationFeeRule.objects.create(
            brand="Gogoro",
            energy_type=VehicleModel.EnergyType.ELECTRIC,
            electric_registration_class=VehicleModel.ElectricRegistrationClass.LIGHT,
            calculation_type=BrandRegistrationFeeRule.CalculationType.FIXED_COMPONENTS,
            fixed_registration_fee=550,
            fixed_compulsory_insurance_fee=658,
            insurance_period_years=1,
            effective_from=date(2026, 1, 1),
        )
        BrandRegistrationFeeRule.objects.create(
            brand="SYM",
            energy_type=VehicleModel.EnergyType.GAS,
            calculation_type=BrandRegistrationFeeRule.CalculationType.FORMULA,
            min_cc=51,
            max_cc=125,
            insurance_period_years=1,
            effective_from=date(2026, 1, 1),
        )
        BrandRegistrationFeeRule.objects.create(
            brand="人工測試",
            energy_type=VehicleModel.EnergyType.MICRO_ELECTRIC,
            calculation_type=BrandRegistrationFeeRule.CalculationType.MANUAL,
            effective_from=date(2026, 1, 1),
            active=False,
        )
        self.client.force_login(self.user)

        page = self.client.get(reverse("brand_registration_fee_rule_list"))

        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'class="registration-rule-card')
        self.assertContains(page, "牌險總額")
        self.assertContains(page, "$2,300")
        self.assertContains(page, "強制險 3 年")
        self.assertContains(page, 'class="registration-rule-card__insurance-badge"', count=3)
        self.assertContains(page, 'class="registration-rule-card__insurance-badge is-manual"', count=1)
        self.assertContains(page, '<strong class="registration-rule-card__insurance-years">3 <b>年</b></strong>', html=True)
        self.assertContains(page, "計算方式：固定整包金額")
        self.assertContains(page, "強制險年期依單據")
        self.assertContains(page, "領牌規費 <b>$550</b>", html=True)
        self.assertContains(page, "強制險 <b>$658</b>", html=True)
        self.assertContains(page, "合計 $1,208")
        self.assertContains(page, "依公式試算")
        self.assertContains(page, "訂單依正式單據輸入")
        self.assertContains(page, "已停用")
        self.assertContains(page, "持續有效，未設定結束日")
        self.assertContains(page, "刪除這筆規則")
        self.assertContains(page, "51～125 c.c.")
        self.assertNotContains(page, "不分級")
        html = page.content.decode()
        gogoro_header = html.split("<h3>Gogoro</h3>", 1)[1].split("</header>", 1)[0]
        emoving_header = html.split("<h3>eMOVING</h3>", 1)[1].split("</header>", 1)[0]
        self.assertNotIn("輕型電動機車", gogoro_header)
        self.assertNotIn("不分級", emoving_header)

    def test_fixed_bundle_requires_total_and_clears_component_amounts(self):
        form = BrandRegistrationFeeRuleForm(
            {
                "brand": "SYM",
                "energy_type": "gas",
                "electric_registration_class": "",
                "calculation_type": "fixed_bundle",
                "min_cc": 51,
                "max_cc": 125,
                "fixed_total": 1600,
                "fixed_registration_fee": 550,
                "fixed_compulsory_insurance_fee": 658,
                "insurance_period_years": 1,
                "effective_from": "2026-08-01",
                "effective_to": "",
                "active": "on",
                "note": "",
            }
        )

        self.assertTrue(form.is_valid(), form.errors)
        rule = form.save()
        self.assertEqual(rule.fixed_total, 1600)
        self.assertEqual(rule.fixed_registration_fee, 0)
        self.assertEqual(rule.fixed_compulsory_insurance_fee, 0)

    def test_fixed_components_requires_both_amounts_and_calculates_total(self):
        base_payload = {
            "brand": "Gogoro",
            "energy_type": "electric",
            "electric_registration_class": "light",
            "calculation_type": "fixed_components",
            "min_cc": "",
            "max_cc": "",
            "fixed_total": "",
            "fixed_registration_fee": "",
            "fixed_compulsory_insurance_fee": "",
            "insurance_period_years": 1,
            "effective_from": "2026-08-01",
            "effective_to": "",
            "active": "on",
            "note": "",
        }
        invalid_form = BrandRegistrationFeeRuleForm(base_payload)

        self.assertFalse(invalid_form.is_valid())
        self.assertIn("fixed_registration_fee", invalid_form.errors)
        self.assertIn("fixed_compulsory_insurance_fee", invalid_form.errors)

        valid_form = BrandRegistrationFeeRuleForm(
            {
                **base_payload,
                "fixed_registration_fee": 550,
                "fixed_compulsory_insurance_fee": 658,
            }
        )
        self.assertTrue(valid_form.is_valid(), valid_form.errors)
        rule = valid_form.save()
        self.assertEqual(rule.fixed_total, 1208)

    def test_manual_mode_saves_without_default_amounts(self):
        form = BrandRegistrationFeeRuleForm(
            {
                "brand": "Gogoro",
                "energy_type": "electric",
                "electric_registration_class": "heavy",
                "calculation_type": "manual",
                "min_cc": "",
                "max_cc": "",
                "fixed_total": 9999,
                "fixed_registration_fee": 550,
                "fixed_compulsory_insurance_fee": 658,
                "insurance_period_years": 1,
                "effective_from": "2026-08-01",
                "effective_to": "",
                "active": "on",
                "note": "",
            }
        )

        self.assertTrue(form.is_valid(), form.errors)
        rule = form.save()
        self.assertEqual(rule.fixed_total, 0)
        self.assertEqual(rule.fixed_registration_fee, 0)
        self.assertEqual(rule.fixed_compulsory_insurance_fee, 0)
