"""T-309（使用者 2026-11-24 定案）：在訂單配件用「贈送」選強制險、火險、失竊險。

- 不做獨立贈送區：一律從配件下拉選單選，類型用「贈送」。
- 火險、失竊險是一般配件，「贈送」0 元只是紀錄，不影響收支、淨利、應收。
- 強制險是配件主檔的特殊種類（`AccessoryProduct.Kind.COMPULSORY_INSURANCE`），只能用「贈送」選、一張單最多一筆：
  - 牌險費留空（系統計算）：牌險費＝試算合計－強制險；領牌依領牌日重算也一樣扣掉；
  - 牌險費填正數：照填，系統不另外扣；填 0 本來就全部吸收，行為照舊；
  - 收支：強制險支出照列、強制險收入 0、規費收入＝規費支出、牌險手續費＝牌險費－規費支出（填 1,142 時 427）；
  - 不標「牌險差異待確認」（門檻改成試算合計－強制險），也不標「牌險少收」；
  - 不計入配件小計，不影響配件金折抵；訂購單照贈品的方式印出來。
"""
import re
import tempfile
import uuid
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from sales.forms import AccessoryProductForm, RegistrationStageForm
from sales.models import AccessoryLine, AccessoryProduct, OrderOperationsProfile, PrintCompany, SalesOrder, SalesSource
from sales.services.order_filters import plate_fee_variance_q
from sales.tests import test_order_wizard
from sales.tests.test_order_workspace import form_data

MEDIA = tempfile.mkdtemp()
ZERO = Decimal("0")
INSTALLMENT = dict(
    payment_type="installment", installment_company="和潤", installment_periods="24",
    installment_monthly="3500", installment_opening_fee="0",
)


@override_settings(MEDIA_ROOT=MEDIA)
class CompulsoryGiftTests(TestCase):
    def setUp(self):
        test_order_wizard.OrderWizardTests.setUp(self)
        # 125cc 油車：規費 715 上下（依日期）、強制險 658（一年）。
        self.model.displacement_cc = 124
        self.model.save(update_fields=["displacement_cc"])
        self.compulsory = AccessoryProduct.objects.create(name="強制險", kind="compulsory_insurance")
        self.fire = AccessoryProduct.objects.create(name="火險")
        self.theft = AccessoryProduct.objects.create(name="失竊險")
        self.helmet = AccessoryProduct.objects.create(name="安全帽", sale_price=Decimal("1500"), labor_fee=Decimal("0"))
        self.credit = AccessoryProduct.objects.create(name="配件金 1000", kind="credit", sale_price=Decimal("-1000"))
        # 贈送要有 order_gift 權限：用 root（帳號 admin）建單與改單。
        self.client.force_login(self.admin)

    image = test_order_wizard.OrderWizardTests.image
    complete_data = test_order_wizard.OrderWizardTests.complete_data
    post = test_order_wizard.OrderWizardTests.post
    draft = test_order_wizard.OrderWizardTests.draft
    walk_to = test_order_wizard.OrderWizardTests.walk_to

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def lines_data(lines, start=0):
        data = {}
        for offset, (product, line_type) in enumerate(lines):
            index = start + offset
            data.update({
                f"accessories-{index}-id": "", f"accessories-{index}-accessory_category": "",
                f"accessories-{index}-accessory_product": str(product.pk), f"accessories-{index}-custom_name": "",
                f"accessories-{index}-quantity": "1", f"accessories-{index}-line_type": line_type,
                f"accessories-{index}-amount": "", f"accessories-{index}-labor_fee": "", f"accessories-{index}-note": "",
            })
        return data

    def create(self, lines=(), **changes):
        """建單精靈建立訂單；lines＝[(配件主檔, 類型)]。"""
        self.key = str(uuid.uuid4())
        accessory_data = {"accessories-TOTAL_FORMS": str(len(lines)), "accessories-INITIAL_FORMS": "0",
                          **self.lines_data(lines)} if lines else {}
        draft = self.walk_to("confirm", **changes, **accessory_data)
        response = self.post("confirm", action="submit", draft=draft, **changes, **accessory_data)
        self.assertEqual(response.status_code, 302, response.content.decode()[:800])
        order = SalesOrder.objects.order_by("-pk").first()
        self.client.force_login(self.admin)
        return order

    @property
    def admin(self):
        user = get_user_model().objects.filter(username="admin").first()
        return user or get_user_model().objects.create_superuser("admin", password="test-only-123")

    def page_data(self, order):
        response = self.client.get(reverse("order_detail", args=[order.pk]), {"tab": "order"})
        self.assertEqual(response.status_code, 200)
        context = response.context
        order.refresh_from_db()
        data = {**form_data(context["form"]), "_order_revision": order.revision, "_workspace": "1"}
        fee_formset = context["fee_formset"]
        data.update(form_data(fee_formset.management_form))
        for form in fee_formset:
            data.update(form_data(form))
        return data, context["formset"]

    def save_lines(self, order, lines, *, expect=200, keep=False, **changes):
        """訂單頁自動儲存：配件改成 lines（[(配件主檔, 類型)]）；keep＝既有的列原樣保留，否則全部刪掉。"""
        data, formset = self.page_data(order)
        existing = [form for form in formset.forms if form.instance.pk]
        for index, form in enumerate(existing):
            row = form_data(form)
            data.update({key.replace(form.prefix, f"accessories-{index}", 1): value for key, value in row.items()})
            data[f"accessories-{index}-id"] = str(form.instance.pk)
            if not keep:
                data[f"accessories-{index}-DELETE"] = "on"
        data.update({"accessories-TOTAL_FORMS": str(len(existing) + len(lines)),
                     "accessories-INITIAL_FORMS": str(len(existing)),
                     "accessories-MIN_NUM_FORMS": "0", "accessories-MAX_NUM_FORMS": "1000"})
        data.update(self.lines_data(lines, start=len(existing)))
        data.update(changes)
        response = self.client.post(reverse("order_edit", args=[order.pk]), data, HTTP_X_ORDER_WORKSPACE="1")
        self.assertEqual(response.status_code, expect, response.content.decode()[:800])
        order.refresh_from_db()
        return response

    def gift_compulsory(self, order, **changes):
        return self.save_lines(order, [(self.compulsory, "gift")], **changes)

    def profile(self, order):
        return OrderOperationsProfile.objects.get(order=order)

    def confirm_registration(self, order):
        SalesOrder.objects.filter(pk=order.pk).update(
            registration_date=date(2026, 11, 20), registration_completed_at=timezone.now(), final_plate_number="ABC-1234")
        order.refresh_from_db()

    def flagged_variance(self, order):
        return SalesOrder.objects.filter(plate_fee_variance_q(), pk=order.pk).exists()

    def assert_gifted_income(self, order):
        profile = self.profile(order)
        self.assertGreater(profile.compulsory_insurance_expense, 0)
        self.assertEqual(profile.compulsory_insurance_income, 0)
        self.assertEqual(profile.registration_tax_income, profile.registration_tax_expense)
        self.assertEqual(profile.agency_fee_income, order.plate_insurance_fee - profile.registration_tax_expense)
        return profile

    def typed_fee(self):
        """使用者的例子：規費 715 時填 1,142，牌險手續費 427；規費依日期預估，這裡用「規費＋427」。"""
        from sales.services.registration_fee import calculate_vehicle_registration_fee

        result = calculate_vehicle_registration_fee(self.model, timezone.localdate(), 1)
        return result.fixed_and_variable_total - result.compulsory_insurance_fee + 427

    # ------------------------------------------------------------------ 主檔
    def test_master_kind_is_gift_only_with_zero_price(self):
        form = AccessoryProductForm({"name": "強制險 一年", "kind": "compulsory_insurance", "sale_price": "0", "labor_fee": "",
                                     "cost": "", "active": "on", "note": ""})
        self.assertTrue(form.is_valid(), form.errors)
        product = form.save()
        self.assertEqual((product.sale_price, product.labor_fee, product.is_compulsory_insurance), (ZERO, ZERO, True))
        form = AccessoryProductForm({"name": "強制險 收費", "kind": "compulsory_insurance", "sale_price": "658", "labor_fee": "100",
                                     "cost": "", "active": "on", "note": ""})
        self.assertIn("強制險只能贈送，售價請填 0。", form.errors["sale_price"])
        self.assertIn("強制險沒有安裝工資，請留 0。", form.errors["labor_fee"])

    def test_database_keeps_compulsory_at_zero(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            AccessoryProduct.objects.create(name="強制險 錯價", kind="compulsory_insurance", sale_price=Decimal("658"))
        order = self.create()
        with self.assertRaises(IntegrityError), transaction.atomic():
            AccessoryLine.objects.create(order=order, name="強制險", amount=Decimal("658"), is_compulsory_insurance=True,
                                         line_type="gift")
        with self.assertRaises(IntegrityError), transaction.atomic():
            AccessoryLine.objects.create(order=order, name="強制險", is_compulsory_insurance=True, line_type="purchase")

    # ------------------------------------------------------------------ 留空（系統計算）× 現金
    def test_cash_blank_with_gifted_compulsory_charges_registration_fee_only(self):
        order = self.create(plate_insurance_fee="")
        self.assertTrue(order.plate_insurance_auto)
        calculated = order.registration_calculated_total
        self.assertEqual(order.compulsory_insurance_fee, 658)
        self.assertEqual(order.plate_insurance_fee, calculated)
        balance_before = order.actual_balance
        self.gift_compulsory(order)
        self.assertTrue(order.plate_insurance_auto)
        self.assertEqual(order.plate_insurance_fee, calculated - 658)
        self.assertEqual(order.plate_insurance_fee, order.registration_tax_total)
        self.assertEqual(order.actual_balance, balance_before - 658)
        profile = self.assert_gifted_income(order)
        self.assertEqual(profile.agency_fee_income, 0)
        self.assertFalse(order.plate_fee_shortfall)
        self.confirm_registration(order)
        self.assertFalse(self.flagged_variance(order))

    def test_wizard_gift_deducts_compulsory_at_creation(self):
        order = self.create(lines=[(self.compulsory, "gift"), (self.fire, "gift"), (self.theft, "gift")], plate_insurance_fee="")
        line = order.accessories.get(accessory_product=self.compulsory)
        self.assertEqual((line.is_compulsory_insurance, line.line_type, line.amount, line.quantity), (True, "gift", ZERO, 1))
        self.assertTrue(order.plate_insurance_auto)
        self.assertEqual(order.plate_insurance_fee, order.registration_calculated_total - 658)
        self.assertEqual(order.calculated_balance, order.calculate_balance())
        self.assert_gifted_income(order)

    def test_removing_gifted_compulsory_restores_system_estimate(self):
        order = self.create(plate_insurance_fee="")
        self.gift_compulsory(order)
        self.save_lines(order, [])
        self.assertFalse(order.accessories.exists())
        self.assertEqual(order.plate_insurance_fee, order.registration_calculated_total)
        profile = self.profile(order)
        self.assertEqual(profile.compulsory_insurance_income, profile.compulsory_insurance_expense)

    def test_order_form_resave_keeps_deduction(self):
        order = self.create(plate_insurance_fee="")
        self.gift_compulsory(order)
        self.save_lines(order, [], keep=True, note="再存一次")
        self.assertEqual((order.note, order.plate_insurance_fee), ("再存一次", order.registration_tax_total))
        self.assertTrue(order.accessories.filter(is_compulsory_insurance=True).exists())

    def test_registration_recalculation_still_deducts_gifted_compulsory(self):
        order = self.create(plate_insurance_fee="")
        self.gift_compulsory(order)
        form = RegistrationStageForm({"registration_date": "2026-11-20", "final_plate_number": "ABC-1234"}, instance=order)
        self.assertTrue(form.is_valid(), form.errors)
        order = form.save()
        order.refresh_from_db()
        self.assertTrue(order.plate_insurance_auto)
        self.assertEqual(order.plate_insurance_fee, order.registration_calculated_total - order.compulsory_insurance_fee)
        self.assertEqual(order.actual_balance, order.calculate_balance())
        self.assert_gifted_income(order)

    def test_registration_recalculation_without_gift_is_unchanged(self):
        order = self.create(plate_insurance_fee="")
        form = RegistrationStageForm({"registration_date": "2026-11-20", "final_plate_number": "ABC-1234"}, instance=order)
        self.assertTrue(form.is_valid(), form.errors)
        order = form.save()
        self.assertEqual(order.plate_insurance_fee, order.registration_calculated_total)

    # ------------------------------------------------------------------ 火險、失竊險＝紀錄
    def test_blank_with_fire_and_theft_only_is_unchanged(self):
        order = self.create(plate_insurance_fee="")
        profile = self.profile(order)
        before = (order.plate_insurance_fee, order.actual_balance, order.accessory_total, profile.compulsory_insurance_income,
                  profile.agency_fee_income, profile.registration_tax_income)
        self.save_lines(order, [(self.fire, "gift"), (self.theft, "gift")])
        order = SalesOrder.objects.get(pk=order.pk)
        profile = self.profile(order)
        after = (order.plate_insurance_fee, order.actual_balance, order.accessory_total, profile.compulsory_insurance_income,
                 profile.agency_fee_income, profile.registration_tax_income)
        self.assertEqual(before, after)
        self.assertEqual(sorted(order.accessories.values_list("name", "line_type", "amount")),
                         [("失竊險", "gift", ZERO), ("火險", "gift", ZERO)])
        self.assertFalse(order.accessories.filter(is_compulsory_insurance=True).exists())

    # ------------------------------------------------------------------ 填正數
    def test_cash_typed_fee_with_gifted_compulsory_is_not_deducted_again(self):
        fee = self.typed_fee()
        order = self.create(plate_insurance_fee=str(fee))
        self.gift_compulsory(order)
        self.assertFalse(order.plate_insurance_auto)
        self.assertEqual(order.plate_insurance_fee, fee)
        profile = self.assert_gifted_income(order)
        self.assertEqual(profile.agency_fee_income, 427)
        self.assertFalse(order.plate_fee_shortfall)
        self.confirm_registration(order)
        self.assertFalse(self.flagged_variance(order))

    def test_cash_typed_fee_without_gift_still_flags_variance_and_shortfall(self):
        order = self.create(plate_insurance_fee=str(self.typed_fee()))
        profile = self.profile(order)
        self.assertEqual(profile.compulsory_insurance_income, profile.compulsory_insurance_expense)
        self.assertLess(profile.agency_fee_income, 0)
        self.assertTrue(order.plate_fee_shortfall)
        self.confirm_registration(order)
        self.assertTrue(self.flagged_variance(order))

    def test_typed_fee_below_registration_fee_still_flags_variance_when_gifted(self):
        fee = self.typed_fee() - 427 - 15
        order = self.create(plate_insurance_fee=str(fee))
        self.gift_compulsory(order)
        self.confirm_registration(order)
        self.assertTrue(self.flagged_variance(order))
        self.assertTrue(order.plate_fee_shortfall)
        # 差異卡比較的系統金額是試算合計－強制險（＝規費）。
        from sales.forms import OrderOperationsForm
        from sales.services.order_workspace import finance_overview_context
        profile = self.profile(order)
        variance = finance_overview_context(OrderOperationsForm(instance=profile, prefix="operations"), profile, order)["plate_variance"]
        self.assertEqual((variance["calculated"], variance["difference"]), (order.registration_tax_total, -15))

    # ------------------------------------------------------------------ 填 0
    def test_zero_fee_with_gifted_compulsory_is_unchanged(self):
        order = self.create(plate_insurance_fee="0")
        self.gift_compulsory(order)
        self.assertFalse(order.plate_insurance_auto)
        self.assertEqual(order.plate_insurance_fee, 0)
        profile = self.profile(order)
        self.assertEqual((profile.registration_tax_income, profile.compulsory_insurance_income, profile.agency_fee_income),
                         (0, 0, 0))
        self.assertFalse(order.plate_fee_shortfall)

    def test_zero_fee_without_gift(self):
        order = self.create(plate_insurance_fee="0")
        profile = self.profile(order)
        self.assertEqual((profile.registration_tax_income, profile.compulsory_insurance_income, profile.agency_fee_income),
                         (0, 0, 0))

    # ------------------------------------------------------------------ 分期
    def test_installment_blank_stays_store_absorbed_with_gift(self):
        order = self.create(plate_insurance_fee="", **INSTALLMENT)
        self.gift_compulsory(order)
        self.assertEqual((order.plate_insurance_auto, order.plate_insurance_fee), (False, 0))
        profile = self.profile(order)
        self.assertEqual((profile.registration_tax_income, profile.compulsory_insurance_income), (0, 0))

    def test_installment_typed_fee_with_and_without_gifted_compulsory(self):
        fee = self.typed_fee()
        plain = self.create(plate_insurance_fee=str(fee), **INSTALLMENT)
        self.assertLess(self.profile(plain).agency_fee_income, 0)
        order = self.create(plate_insurance_fee=str(fee), **INSTALLMENT)
        self.gift_compulsory(order)
        self.assertEqual(order.plate_insurance_fee, fee)
        self.assertEqual(self.assert_gifted_income(order).agency_fee_income, 427)
        self.assertFalse(order.plate_fee_shortfall)

    def test_installment_legacy_auto_order_deducts_when_gifted(self):
        # 既有照系統試算的分期單（T-195 之前）存檔維持原狀：一樣適用扣強制險。
        order = self.create(plate_insurance_fee="")
        SalesOrder.objects.filter(pk=order.pk).update(**{k: v for k, v in INSTALLMENT.items() if k != "installment_periods"},
                                                      installment_periods=24)
        order.refresh_from_db()
        self.gift_compulsory(order)
        self.assertTrue(order.plate_insurance_auto)
        self.assertEqual(order.plate_insurance_fee, order.registration_calculated_total - 658)

    # ------------------------------------------------------------------ 車行
    def test_dealer_cash_blank_with_gift_settles_registration_fee_only(self):
        from sales.services.dealer_settlement import dealer_settlement

        dealer = SalesSource.objects.create(name="T309 車行", source_type="dealer")
        order = self.create(plate_insurance_fee="", source_type="dealer", source=str(dealer.pk))
        self.gift_compulsory(order)
        self.assertEqual(order.plate_insurance_fee, order.registration_tax_total)
        self.assert_gifted_income(order)
        settlement = dealer_settlement(order, self.profile(order))
        plate = next(row for row in settlement["terms"] if row["key"] == "plate_insurance")
        self.assertEqual(plate["amount"], order.registration_tax_total)

    def test_dealer_cash_blank_without_gift_settles_full_estimate(self):
        from sales.services.dealer_settlement import dealer_settlement

        dealer = SalesSource.objects.create(name="T309 車行乙", source_type="dealer")
        order = self.create(plate_insurance_fee="", source_type="dealer", source=str(dealer.pk))
        settlement = dealer_settlement(order, self.profile(order))
        plate = next(row for row in settlement["terms"] if row["key"] == "plate_insurance")
        self.assertEqual(plate["amount"], order.registration_calculated_total)

    def test_dealer_typed_fee_and_zero_with_gift(self):
        dealer = SalesSource.objects.create(name="T309 分期車行", source_type="dealer")
        order = self.create(plate_insurance_fee=str(self.typed_fee()), source_type="dealer", source=str(dealer.pk), **INSTALLMENT)
        self.gift_compulsory(order)
        self.assertEqual(self.assert_gifted_income(order).agency_fee_income, 427)
        zero = self.create(plate_insurance_fee="0", source_type="dealer", source=str(dealer.pk))
        self.gift_compulsory(zero)
        self.assertEqual((zero.plate_insurance_fee, self.profile(zero).compulsory_insurance_income), (0, 0))

    # ------------------------------------------------------------------ 明細規則
    def test_compulsory_cannot_be_sold_as_purchase(self):
        order = self.create(plate_insurance_fee="")
        response = self.save_lines(order, [(self.compulsory, "purchase")], expect=400)
        self.assertIn("強制險只能用「贈送」選", str(response.json()["errors"]))
        self.assertFalse(order.accessories.exists())

    def test_only_one_compulsory_per_order(self):
        order = self.create(plate_insurance_fee="")
        response = self.save_lines(order, [(self.compulsory, "gift"), (self.compulsory, "gift")], expect=400)
        self.assertIn("每張訂單最多送 1 筆強制險", str(response.json()["errors"]))
        self.assertFalse(order.accessories.exists())

    def test_purchase_only_user_cannot_add_compulsory_gift(self):
        from sales.forms import AccessoryLineForm

        order = self.create(plate_insurance_fee="")
        form = AccessoryLineForm({"accessory_category": "", "accessory_product": str(self.compulsory.pk), "custom_name": "",
                                  "quantity": "1", "line_type": "", "amount": "", "labor_fee": "", "note": ""},
                                 instance=AccessoryLine(order=order), purchase_only=True)
        self.assertFalse(form.is_valid())
        self.assertIn("沒有新增或變更贈送配件的權限", str(form.errors["line_type"]))

    def test_accessory_subtotal_and_credit_are_unaffected(self):
        order = self.create(plate_insurance_fee="")
        self.save_lines(order, [(self.helmet, "purchase"), (self.credit, "purchase")])
        before_total, before_credit = order.accessory_total, order.accessory_credit
        self.assertEqual((before_total, before_credit.credit_applied), (Decimal("500"), Decimal("1000")))
        self.save_lines(order, [(self.compulsory, "gift")], keep=True)
        order = SalesOrder.objects.get(pk=order.pk)
        credit = order.accessory_credit
        self.assertEqual(order.accessory_total, before_total)
        self.assertEqual((credit.subtotal, credit.credit_applied, credit.credit_void),
                         (before_credit.subtotal, before_credit.credit_applied, before_credit.credit_void))
        # 交車核對的實物配件不列強制險。
        self.assertNotIn("強制險", [line.name for line in order.delivery_accessory_lines])

    # ------------------------------------------------------------------ 訂購單、列表
    def test_contract_prints_compulsory_as_gift(self):
        from sales.services.order_contract_pdf import build_order_contract_pdf, contract_payment_amounts, printed_detail_total
        from sales.tests.test_order_fixes_1622 import pdf_text

        PrintCompany.objects.update_or_create(key="home", defaults=dict(
            legal_name="測試機車行", tax_id="12345678", address="測試地址", phone="02-1234"))
        order = self.create(plate_insurance_fee=str(self.typed_fee()))
        self.save_lines(order, [(self.compulsory, "gift"), (self.theft, "gift")])
        order = SalesOrder.objects.get(pk=order.pk)
        self.assertEqual(contract_payment_amounts(order)["total"], printed_detail_total(order))
        text = pdf_text(build_order_contract_pdf(order))
        # 照贈品的方式印：0 元一列（訂購單不印說明欄），客人只看得到送給他的項目。
        self.assertIn("配件 強制險 1 0 0", text)
        self.assertIn("配件 失竊險 1 0 0", text)
        self.assertNotIn("火險", text)
        self.assertNotIn("應收調整", text)

    def test_contract_blank_fee_with_gift_keeps_payment_amounts_consistent(self):
        from sales.services.order_contract_pdf import build_order_contract_pdf, contract_payment_amounts, printed_detail_total
        from sales.tests.test_order_fixes_1622 import pdf_text

        PrintCompany.objects.update_or_create(key="home", defaults=dict(
            legal_name="測試機車行", tax_id="12345678", address="測試地址", phone="02-1234"))
        order = self.create(plate_insurance_fee="")
        self.gift_compulsory(order)
        order = SalesOrder.objects.get(pk=order.pk)
        self.assertEqual(contract_payment_amounts(order)["total"], printed_detail_total(order))
        text = pdf_text(build_order_contract_pdf(order))
        self.assertIn("配件 強制險 1 0 0", text)
        self.assertIn("另計", text)

    def test_order_list_does_not_mark_shortfall_for_gifted_order(self):
        order = self.create(plate_insurance_fee=str(self.typed_fee()))
        page = self.client.get(reverse("order_list"), {"tab": "all"}).content.decode()
        self.assertIn("order-plate-shortfall", page)
        self.gift_compulsory(order)
        page = self.client.get(reverse("order_list"), {"tab": "all"}).content.decode()
        self.assertIn(order.number, page)
        self.assertNotIn("order-plate-shortfall", page)

    # 驗收後使用者決定（2026-11-24）：建單畫面客人看得到，BUSINESS_RULES 規定客人看得到的畫面不露出牌險算法，
    # 選了強制險的配件列不再顯示「只能贈送；牌險費留空時扣掉強制險」。自動改成贈送、鎖 0 元的行為照舊。
    PLATE_RULE_HINT = "牌險費留空時扣掉強制險"

    @staticmethod
    def visible(html):
        """只看畫面上的標記；行內 <script> 的程式註解不會顯示在畫面上。"""
        return re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.S)

    def test_wizard_accessory_step_does_not_show_plate_fee_rule(self):
        lines = {"accessories-TOTAL_FORMS": "1", "accessories-INITIAL_FORMS": "0",
                 **self.lines_data([(self.compulsory, "gift")])}
        self.key = str(uuid.uuid4())
        draft = self.walk_to("deposit", plate_insurance_fee="", **lines)
        response = self.client.get(reverse("order_create"), {"draft": draft.pk, "step": "accessories"})
        self.assertEqual(response.status_code, 200)
        page = response.content.decode()
        self.assertIn("訂單精靈・第 5／7 步", page)
        self.assertTrue(any(str(form["accessory_product"].value()) == str(self.compulsory.pk)
                            for form in response.context["formset"].forms))
        self.assertIn('input.dataset.compulsoryLocked = "1"', page)
        self.assertNotIn(self.PLATE_RULE_HINT, self.visible(page))
        self.assertNotIn("data-accessory-compulsory-note", page)

    def test_order_page_does_not_show_plate_fee_rule(self):
        order = self.create(lines=[(self.compulsory, "gift")], plate_insurance_fee="")
        self.assertTrue(order.accessories.filter(is_compulsory_insurance=True, line_type="gift", amount=0).exists())
        page = self.client.get(reverse("order_detail", args=[order.pk]), {"tab": "order"}).content.decode()
        self.assertIn(f'value="{self.compulsory.pk}" selected', page)
        self.assertNotIn(self.PLATE_RULE_HINT, self.visible(page))
        self.assertNotIn("data-accessory-compulsory-note", page)
