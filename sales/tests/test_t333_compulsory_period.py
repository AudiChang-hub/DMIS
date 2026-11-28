"""T-333（使用者 2026-11-28）：建立訂單與訂單頁都能選強制險期間（一年／兩年）。

- 建單：期間看得到、跟牌險費放在一起；油車一、兩年，微電車固定三年，電動類依品牌固定規則的年期。
- 訂單頁：同一欄位自動儲存；強制險收入、支出、傭金照既有規則重算（人工改過的不覆寫），領牌試算卡原地換新。
- 既有訂單沒有改期間就不動金額。
前端選項與唯讀顯示見 tests/frontend/order-insurance-period-t333.test.cjs。
"""
import json
import uuid
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from sales.forms import OrderEditForm
from sales.models import BrandRegistrationFeeRule, OrderOperationsProfile, SalesOrder, VehicleColor, VehicleModel
from sales.services.registration_fee import insurance_period_options
from sales.tests import test_order_lifecycle as lifecycle
from sales.tests import test_order_wizard
from sales.tests.test_order_workspace import form_data, formset_data


def rate_data(page):
    return json.loads(page.split('<script id="vehicle-rate-data" type="application/json">', 1)[1].split("</script>", 1)[0])


class InsurancePeriodOptionsTests(TestCase):
    def model(self, energy, **extra):
        return VehicleModel.objects.create(brand="虛構牌", name=f"期間測試{energy}{len(extra)}", energy_type=energy, **extra)

    def rule(self, energy, period, **extra):
        return BrandRegistrationFeeRule.objects.create(
            brand="虛構牌", energy_type=energy, insurance_period_years=period, effective_from=date(2026, 1, 1),
            calculation_type=BrandRegistrationFeeRule.CalculationType.FIXED_BUNDLE, fixed_total=Decimal("2000"), **extra,
        )

    def test_gas_one_or_two_micro_fixed_three(self):
        gas = self.model(VehicleModel.EnergyType.GAS, displacement_cc=124)
        micro = self.model(VehicleModel.EnergyType.MICRO_ELECTRIC)
        options = insurance_period_options([gas, micro], date(2026, 11, 28))
        self.assertEqual(options[gas.pk], [1, 2])
        self.assertEqual(options[micro.pk], [3])

    def test_electric_uses_active_fixed_rule_periods_of_same_brand_and_class(self):
        heavy = self.model(VehicleModel.EnergyType.ELECTRIC, electric_registration_class="heavy")
        light = self.model(VehicleModel.EnergyType.LIGHT_ELECTRIC, electric_registration_class="light")
        self.rule(VehicleModel.EnergyType.ELECTRIC, 1, electric_registration_class="heavy")
        self.rule(VehicleModel.EnergyType.ELECTRIC, 2, electric_registration_class="heavy")
        self.rule(VehicleModel.EnergyType.ELECTRIC, 3, electric_registration_class="heavy", active=False)
        self.rule(VehicleModel.EnergyType.ELECTRIC, 3, electric_registration_class="heavy", effective_to=date(2026, 6, 30))
        # 輕型電動車相容「電動車＋輕型級別」的規則（brand_registration_rule_candidates）。
        self.rule(VehicleModel.EnergyType.ELECTRIC, 2, electric_registration_class="light")
        options = insurance_period_options([heavy, light], date(2026, 11, 28))
        self.assertEqual(options[heavy.pk], [1, 2])
        self.assertEqual(options[light.pk], [2])

    def test_electric_without_rules_is_unrestricted(self):
        other = VehicleModel.objects.create(brand="另一虛構牌", name="無規則電動", energy_type=VehicleModel.EnergyType.ELECTRIC,
                                            electric_registration_class="heavy")
        self.rule(VehicleModel.EnergyType.ELECTRIC, 2, electric_registration_class="heavy")
        self.assertEqual(insurance_period_options([other], date(2026, 11, 28))[other.pk], [])


class CreateOrderInsurancePeriodTests(TestCase):
    setUp = test_order_wizard.OrderWizardTests.setUp
    image = test_order_wizard.OrderWizardTests.image
    complete_data = test_order_wizard.OrderWizardTests.complete_data
    post = test_order_wizard.OrderWizardTests.post
    draft = test_order_wizard.OrderWizardTests.draft
    walk_to = test_order_wizard.OrderWizardTests.walk_to

    def login_admin(self):
        admin = get_user_model().objects.create_superuser("t333-admin", password="test-only-123")
        self.client.force_login(admin)
        self.model.displacement_cc = 124
        self.model.save(update_fields=["displacement_cc"])

    def test_period_is_visible_next_to_plate_fee_with_default_one_year(self):
        self.login_admin()
        page = self.client.get(reverse("order_create")).content.decode()
        block = page.split('<div class="conditional-panel plate-fee-only">', 1)[1].split("</details>", 1)[0]
        hidden, visible = block.split('<div class="form-grid" id="gas-registration-calculator">', 1)
        self.assertNotIn('name="compulsory_insurance_period"', hidden)
        self.assertIn('<label for="id_compulsory_insurance_period" data-insurance-period-label>強制險期間</label>', visible)
        self.assertLess(visible.index('name="compulsory_insurance_period"'), visible.index('name="plate_insurance_fee"'))
        self.assertRegex(visible, r'<option value="1" selected>一年</option>')
        self.assertIn('id="id_compulsory_insurance_period_fixed"', visible)
        self.assertEqual(rate_data(page)[str(self.model.pk)]["insurance_periods"], [1, 2])
        self.assertIn("js/order-insurance-period.js", page)

    def create(self, **changes):
        self.key = str(uuid.uuid4())
        draft = self.walk_to("confirm", **changes)
        response = self.post("confirm", action="submit", draft=draft, **changes)
        self.assertEqual(response.status_code, 302, response.content.decode()[:300])
        return SalesOrder.objects.get(owner_name="測試車主")

    def test_choose_two_years_when_creating(self):
        self.login_admin()
        order = self.create(compulsory_insurance_period="2", plate_insurance_fee="")
        self.assertEqual(order.compulsory_insurance_period, 2)
        self.assertEqual(order.compulsory_insurance_fee, 1200)
        profile = order.operations
        self.assertEqual((profile.compulsory_insurance_expense, profile.compulsory_insurance_income, profile.insurance_commission),
                         (Decimal("1200"), Decimal("1200"), Decimal("215")))

    def test_micro_electric_is_fixed_three_years_whatever_is_posted(self):
        self.login_admin()
        VehicleModel.objects.filter(pk=self.model.pk).update(energy_type=VehicleModel.EnergyType.MICRO_ELECTRIC)
        page = self.client.get(reverse("order_create")).content.decode()
        self.assertEqual(rate_data(page)[str(self.model.pk)]["insurance_periods"], [3])
        order = self.create(compulsory_insurance_period="1", vehicle_energy_type="micro_electric")
        self.assertEqual(order.compulsory_insurance_period, 3)
        self.assertEqual(order.operations.insurance_commission, Decimal("100"))


class OrderPageInsurancePeriodTests(TestCase):
    setUp = lifecycle.OrderLifecycleTests.setUp
    make_order = lifecycle.OrderLifecycleTests.make_order

    def admin(self):
        admin = get_user_model().objects.create_superuser("t333-page-admin", password="test-only-123")
        self.client.force_login(admin)
        return admin

    def autosave(self, order, **changes):
        order.refresh_from_db()
        form = OrderEditForm(instance=order)
        from sales.forms import OrderPageAccessoryFormSet, OrderPageOtherFeeFormSet
        data = {**form_data(form), **formset_data(OrderPageAccessoryFormSet(instance=order)),
                **formset_data(OrderPageOtherFeeFormSet(instance=order, prefix="other_fees")),
                "_order_revision": str(order.revision), **changes}
        return self.client.post(reverse("order_edit", args=[order.pk]), data, HTTP_X_ORDER_WORKSPACE="1")

    def saved_order(self):
        # 先照訂單頁存一次（牌險費留空＝照系統試算），讓收支三筆是系統帶入的正常狀態。
        order, _vehicle = self.make_order()
        response = self.autosave(order, plate_insurance_fee="", note="虛構測試單")
        self.assertTrue(response.json()["ok"], response.content.decode()[:400])
        return order

    def amounts(self, order):
        order.refresh_from_db()
        profile = OrderOperationsProfile.objects.get(order=order)
        return (order.compulsory_insurance_period, order.compulsory_insurance_fee, profile.compulsory_insurance_expense,
                profile.compulsory_insurance_income, profile.insurance_commission)

    def test_order_page_shows_editable_period(self):
        self.admin()
        order, _vehicle = self.make_order()
        page = self.client.get(reverse("order_detail", args=[order.pk]), {"tab": "order"}).content.decode()
        card = page.split('<details class="card registration-fee-card"', 1)[1].split("</details>", 1)[0]
        visible = card.split('<div class="form-grid registration-fee-card__fields">', 1)[1]
        field = visible.split('<select name="compulsory_insurance_period"', 1)[1].split(">", 1)[0]
        self.assertNotIn("disabled", field)

    def test_changing_period_recalculates_three_amounts_and_refreshes_cards(self):
        self.admin()
        order = self.saved_order()
        before = self.amounts(order)
        self.assertEqual(before, (1, 658, Decimal("658"), Decimal("658"), Decimal("145")))
        response = self.autosave(order, compulsory_insurance_period="2", plate_insurance_fee="")
        self.assertEqual(response.status_code, 200, response.content.decode()[:400])
        payload = response.json()
        self.assertTrue(payload["ok"], payload)
        self.assertEqual(self.amounts(order), (2, 1200, Decimal("1200"), Decimal("1200"), Decimal("215")))
        # 畫面局部更新：收支欄位值、訂單欄位值、領牌試算卡都在回應裡。
        operations = payload["sync"]["operations"]
        self.assertEqual(str(operations["operations-compulsory_insurance_expense"]), "1200")
        self.assertEqual(str(operations["operations-compulsory_insurance_income"]), "1200")
        self.assertEqual(str(operations["operations-insurance_commission"]), "215")
        self.assertEqual(str(payload["sync"]["order"]["compulsory_insurance_period"]), "2")
        self.assertIn("data-finance-registration", payload["finance_registration_html"])
        self.assertIn("強制險兩年", payload["finance_registration_html"])
        # 改回一年也照規則算回來。
        self.autosave(order, compulsory_insurance_period="1", plate_insurance_fee="")
        self.assertEqual(self.amounts(order), before)

    def test_manual_amounts_are_kept_like_other_fields(self):
        self.admin()
        order = self.saved_order()
        OrderOperationsProfile.objects.filter(order=order).update(
            insurance_commission=Decimal("300"), compulsory_insurance_income=Decimal("999"),
            manual_financial_fields=["insurance_commission", "compulsory_insurance_income"],
        )
        self.autosave(order, compulsory_insurance_period="2", plate_insurance_fee="")
        # 人工改過的不覆寫；沒改過的支出照新年期重算。
        self.assertEqual(self.amounts(order), (2, 1200, Decimal("1200"), Decimal("999"), Decimal("300")))

    def test_existing_orders_are_untouched(self):
        self.admin()
        edited = self.saved_order()
        other = self.saved_order()
        before = self.amounts(other)
        revision = SalesOrder.objects.get(pk=other.pk).revision
        # 開訂單頁（含建單畫面需要的車型資料）不會寫入任何金額。
        self.client.get(reverse("order_detail", args=[other.pk]), {"tab": "order"})
        self.client.get(reverse("order_detail", args=[other.pk]), {"tab": "finance"})
        self.autosave(edited, compulsory_insurance_period="2", plate_insurance_fee="")
        self.assertEqual(self.amounts(other), before)
        self.assertEqual(SalesOrder.objects.get(pk=other.pk).revision, revision)
        # 別的欄位存檔時，期間與強制險金額照原值。
        self.autosave(other, note="只改備註", plate_insurance_fee="")
        self.assertEqual(self.amounts(other), before)

    def test_cancelled_order_is_locked_like_other_fields(self):
        self.admin()
        order = self.saved_order()
        before = self.amounts(order)
        SalesOrder.objects.filter(pk=order.pk).update(status=SalesOrder.Status.CANCELLED)
        response = self.autosave(order, compulsory_insurance_period="2", plate_insurance_fee="")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.amounts(order), before)
