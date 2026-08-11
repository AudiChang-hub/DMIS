from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from sales.forms import SalesOrderForm
from sales.models import (
    DealerVolumeBonusRule,
    DealerVolumeBonusSettlement,
    DealerVolumeBonusTier,
    InstallmentCompany,
    InstallmentPlanOption,
    InstallmentPlanVersion,
    OrderOperationsProfile,
    SalesOrder,
    SalesSource,
    SalesSourceCategory,
    SalesSourceBrandPolicy,
    VehicleColor,
    VehicleModel,
)
from sales.services.dealer_commission import (
    apply_order_dealer_commission,
    create_volume_bonus_settlement,
    preview_volume_bonus,
    revise_volume_bonus_settlement,
)
from sales.services.installment_plan import (
    apply_order_installment_snapshot,
    resolve_installment_plan_option,
)


class ChannelFinanceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("finance", password="pass12345")
        self.model = VehicleModel.objects.create(
            brand="SUZUKI",
            name="SUI 125",
            model_number="UQ125DA",
            model_year=2026,
            model_code=VehicleModel.ModelType.FRONT_DISC_REAR_DRUM,
            energy_type=VehicleModel.EnergyType.GAS,
            displacement_cc=125,
            base_dealer_commission=Decimal("2000"),
        )
        self.color = VehicleColor.objects.create(vehicle_model=self.model, name="灰")
        self.company = InstallmentCompany.objects.create(
            name="和潤", customer_service_phone="0800-123-456"
        )
        self.plan = InstallmentPlanVersion.objects.create(
            vehicle_model=self.model,
            effective_from=date(2026, 8, 1),
        )
        self.option = InstallmentPlanOption.objects.create(
            version=self.plan,
            periods=24,
            monthly_amount=Decimal("3325"),
            company=self.company,
            opening_fee=Decimal("2500"),
            expected_disbursement_rate=Decimal("93.50"),
        )
        self.dealer = SalesSource.objects.create(
            name="冠廷",
            source_type=SalesSource.SourceType.DEALER,
            vehicle_capacity=5,
        )
        self.policy = SalesSourceBrandPolicy.objects.create(
            source=self.dealer,
            brand="SUZUKI",
            commission_adjustment=Decimal("500"),
            effective_from=date(2026, 8, 1),
        )

    def make_order(self, suffix="1", registration_date=date(2026, 8, 5)):
        return SalesOrder.objects.create(
            order_date=date(2026, 8, 2),
            source_type=SalesOrder.SourceType.DEALER,
            source=self.dealer,
            owner_name=f"測試車主{suffix}",
            owner_phone=f"091200000{suffix}",
            owner_address="新北市",
            owner_id_number=f"A12345678{suffix}",
            vehicle_model=self.model,
            color=self.color,
            vehicle_price=Decimal("70000"),
            payment_type=SalesOrder.PaymentType.INSTALLMENT,
            installment_company="和潤",
            installment_periods=24,
            installment_monthly=Decimal("3325"),
            installment_opening_fee=Decimal("2500"),
            registration_date=registration_date,
            registration_completed_at=timezone.now(),
            status=SalesOrder.Status.DELIVERY_PENDING,
        )

    def test_installment_plan_resolves_by_order_date_and_periods(self):
        self.assertEqual(
            resolve_installment_plan_option(self.model.pk, date(2026, 8, 3), 24),
            self.option,
        )
        self.assertIsNone(
            resolve_installment_plan_option(self.model.pk, date(2026, 7, 31), 24)
        )

    def test_order_form_fills_missing_installment_master_values(self):
        form = SalesOrderForm(
            data={
                "source_type": SalesOrder.SourceType.STORE,
                "owner_type": SalesOrder.OwnerType.COMPANY,
                "owner_name": "測試公司",
                "owner_phone": "0226951112",
                "owner_address": "新北市",
                "owner_id_number": "83739807",
                "id_verified": True,
                "vehicle_energy_type": VehicleModel.EnergyType.GAS,
                "vehicle_model": self.model.pk,
                "color": self.color.pk,
                "vehicle_category": SalesOrder.VehicleCategory.NEW,
                "payment_type": SalesOrder.PaymentType.INSTALLMENT,
                "vehicle_price": "77000",
                "deposit_amount": "0",
                "installment_periods": "24",
                "plate_choice": SalesOrder.PlateChoice.NONE,
                "delivery_method": SalesOrder.DeliveryMethod.STORE_PICKUP,
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["installment_company"], "和潤")
        self.assertEqual(form.cleaned_data["installment_monthly"], Decimal("3325"))

    def test_installment_snapshot_preserves_company_phone(self):
        order = self.make_order()
        apply_order_installment_snapshot(order)
        order.refresh_from_db()
        profile = OrderOperationsProfile.objects.get(order=order)
        self.assertEqual(order.installment_plan_option, self.option)
        self.assertFalse(order.installment_plan_snapshot["manual_override"])
        self.assertEqual(profile.customer_service_phone, "0800-123-456")

        self.company.customer_service_phone = "新電話"
        self.company.save()
        profile.refresh_from_db()
        self.assertEqual(profile.customer_service_phone, "0800-123-456")

    def test_dealer_commission_uses_model_base_and_brand_adjustment(self):
        order = self.make_order()
        profile = apply_order_dealer_commission(order, lock=True)
        self.assertEqual(profile.dealer_commission_base, Decimal("2000"))
        self.assertEqual(profile.dealer_commission_adjustment, Decimal("500"))
        self.assertEqual(profile.dealer_commission_expense, Decimal("2500"))
        self.assertEqual(profile.dealer_commission_policy, self.policy)
        self.assertIsNotNone(profile.dealer_commission_locked_at)

    def test_volume_bonus_is_retroactive_and_only_settled_once(self):
        orders = [self.make_order(str(index), date(2026, 8, 5 + index)) for index in range(1, 4)]
        rule = DealerVolumeBonusRule.objects.create(
            dealer=self.dealer,
            brand="SUZUKI",
            starts_on=date(2026, 8, 1),
            ends_on=date(2026, 8, 31),
        )
        DealerVolumeBonusTier.objects.create(
            rule=rule, minimum_quantity=3, bonus_per_vehicle=Decimal("500")
        )
        preview = preview_volume_bonus(rule)
        self.assertEqual(preview["quantity"], 3)
        self.assertEqual(preview["expected_amount"], Decimal("1500"))

        settlement = create_volume_bonus_settlement(rule, "finance")
        self.assertEqual(settlement.allocations.count(), 3)
        self.assertEqual(
            sum(item.amount for item in settlement.allocations.all()),
            Decimal("1500"),
        )
        for order in orders:
            self.assertEqual(
                OrderOperationsProfile.objects.get(order=order).dealer_commission_expense,
                Decimal("3000"),
            )
        with self.assertRaises(ValueError):
            create_volume_bonus_settlement(rule, "finance")

    def test_adjusted_settlement_requires_reason(self):
        settlement = DealerVolumeBonusSettlement(
            rule=DealerVolumeBonusRule(
                dealer=self.dealer,
                brand="SUZUKI",
                starts_on=date(2026, 8, 1),
                ends_on=date(2026, 8, 31),
            ),
            expected_amount=Decimal("1000"),
            actual_amount=Decimal("900"),
        )
        with self.assertRaises(Exception):
            settlement.full_clean()

    def test_settled_amount_can_be_revised_with_audited_reallocation(self):
        orders = [self.make_order(str(index), date(2026, 8, 10 + index)) for index in range(1, 3)]
        rule = DealerVolumeBonusRule.objects.create(
            dealer=self.dealer,
            brand="SUZUKI",
            starts_on=date(2026, 8, 1),
            ends_on=date(2026, 8, 31),
        )
        DealerVolumeBonusTier.objects.create(
            rule=rule, minimum_quantity=2, bonus_per_vehicle=Decimal("500")
        )
        settlement = create_volume_bonus_settlement(rule, "finance")
        revise_volume_bonus_settlement(settlement, "admin", Decimal("1201"), "原廠實際入帳")
        settlement.refresh_from_db()
        self.assertEqual(settlement.actual_amount, Decimal("1201"))
        self.assertEqual(settlement.adjustments.count(), 1)
        self.assertEqual(
            sum(item.amount for item in settlement.allocations.all()), Decimal("1201")
        )
        self.assertEqual(
            sum(
                OrderOperationsProfile.objects.get(order=order).dealer_commission_expense
                for order in orders
            ),
            Decimal("6201"),
        )

    def test_master_pages_are_available(self):
        self.client.force_login(self.user)
        for name in (
            "sales_source_list",
            "sales_source_category_list",
            "installment_company_list",
            "dealer_volume_bonus_list",
        ):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200)

    def test_source_form_derives_system_behavior_from_category(self):
        category = SalesSourceCategory.objects.get(name="本店員工")
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("sales_source_create"),
            {
                "category": category.pk,
                "name": "文傑",
                "active": "on",
                "contacts-TOTAL_FORMS": "0",
                "contacts-INITIAL_FORMS": "0",
                "contacts-MIN_NUM_FORMS": "0",
                "contacts-MAX_NUM_FORMS": "1000",
                "policies-TOTAL_FORMS": "0",
                "policies-INITIAL_FORMS": "0",
                "policies-MIN_NUM_FORMS": "0",
                "policies-MAX_NUM_FORMS": "1000",
            },
        )

        self.assertEqual(response.status_code, 302)
        source = SalesSource.objects.get(name="文傑")
        self.assertEqual(source.source_type, SalesSource.SourceType.STORE)
        self.assertEqual(source.category, category)

    def test_sales_source_list_filters_and_labels_holiday_gift_dealers(self):
        self.dealer.holiday_gift = True
        self.dealer.save(update_fields=["holiday_gift"])
        SalesSource.objects.create(
            name="一般車行",
            source_type=SalesSource.SourceType.DEALER,
            holiday_gift=False,
        )
        SalesSource.objects.create(
            name="測試平台",
            source_type=SalesSource.SourceType.PLATFORM,
            holiday_gift=True,
        )
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("sales_source_list"),
            {"type": "dealer", "holiday_gift": "yes"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "冠廷")
        self.assertNotContains(response, "一般車行")
        self.assertNotContains(response, "測試平台")
        self.assertContains(response, "目前共 1 家")
        self.assertContains(response, "需送禮")
        self.assertContains(response, "返回全部通路")
        self.assertNotContains(response, "type=dealer&amp;holiday_gift=yes")

    def test_sales_source_gift_filter_can_return_to_all_source_types(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("sales_source_list"), {"holiday_gift": "yes"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'href="/data/channels/"')
        self.assertContains(response, "← 返回全部通路")
        self.assertContains(response, "不限送禮狀態")

    def test_holiday_gift_manage_updates_complete_dealer_list(self):
        keep = SalesSource.objects.create(
            name="保留送禮車行",
            source_type=SalesSource.SourceType.DEALER,
            holiday_gift=True,
        )
        remove = SalesSource.objects.create(
            name="移出送禮車行",
            source_type=SalesSource.SourceType.DEALER,
            holiday_gift=True,
        )
        add = SalesSource.objects.create(
            name="新增送禮車行",
            source_type=SalesSource.SourceType.DEALER,
            holiday_gift=False,
        )
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("sales_source_holiday_gift_manage"),
            {"source_ids": [str(keep.pk), str(add.pk)]},
        )

        self.assertRedirects(response, f"{reverse('sales_source_list')}?holiday_gift=yes")
        keep.refresh_from_db()
        remove.refresh_from_db()
        add.refresh_from_db()
        self.assertTrue(keep.holiday_gift)
        self.assertFalse(remove.holiday_gift)
        self.assertTrue(add.holiday_gift)

    def test_holiday_gift_manage_rejects_platform_ids_without_changes(self):
        self.dealer.holiday_gift = True
        self.dealer.save(update_fields=["holiday_gift"])
        platform = SalesSource.objects.create(
            name="不適用平台",
            source_type=SalesSource.SourceType.PLATFORM,
        )
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("sales_source_holiday_gift_manage"),
            {"source_ids": [str(platform.pk)]},
            follow=True,
        )

        self.assertContains(response, "名單未更新")
        self.dealer.refresh_from_db()
        self.assertTrue(self.dealer.holiday_gift)

    def test_holiday_gift_manage_only_lists_dealers(self):
        self.dealer.holiday_gift = True
        self.dealer.save(update_fields=["holiday_gift"])
        SalesSource.objects.create(
            name="不顯示的平台",
            source_type=SalesSource.SourceType.PLATFORM,
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse("sales_source_holiday_gift_manage"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "冠廷")
        self.assertNotContains(response, "不顯示的平台")
        self.assertContains(response, "目前名單")

    def test_sales_source_full_search_understands_legacy_gift_terms(self):
        self.dealer.holiday_gift = True
        self.dealer.save(update_fields=["holiday_gift"])
        self.client.force_login(self.user)

        for keyword in ("年節送禮", "送禮", "月餅"):
            with self.subTest(keyword=keyword):
                response = self.client.get(
                    reverse("sales_source_list"), {"q": keyword}
                )
                self.assertContains(response, "冠廷")
