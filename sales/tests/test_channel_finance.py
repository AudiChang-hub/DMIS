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
            "installment_company_list",
            "dealer_volume_bonus_list",
        ):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200)
