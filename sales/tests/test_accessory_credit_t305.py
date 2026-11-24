"""T-305 配件金（折抵型配件，方案 A）。

使用者 2026-11-24：客人有一筆配件金（例 1,000 元）可折抵配件；在訂單配件區直接選，帶出 −1,000，配件小計與總價自動少這筆；
店家吸收、不走折扣核准、不影響淨利；只折配件、最多折到配件小計 0 元，多的作廢；一般配件與自行填寫仍不能填負數；
只有能維護配件主檔的人能新增或修改配件金，金額由主檔帶出；訂單明細、訂購單、報表看得出是配件金。

前半是漏洞重現（修正前：主檔存得進負數，沒有調價權限的人在建單精靈套用就把負數帶進訂單），現在都要被擋。
"""
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from sales.access.models import ScreenAccessGrant, UserAccessState
from sales.forms import (
    AccessoryLineForm, AccessoryProductBulkForm, AccessoryProductForm, AccessoryProductMergeForm, OrderPageAccessoryFormSet,
)
from sales.models import AccessoryLine, AccessoryProduct, SalesOrder
from sales.services import accessory_credit
from sales.tests import test_order_lifecycle as lifecycle

ZERO = Decimal("0")


def product_payload(**data):
    payload = {"name": "配件金 1000", "kind": "accessory", "sale_price": "0", "labor_fee": "0", "cost": "", "active": "on", "note": ""}
    payload.update(data)
    return payload


class AccessoryCreditBase(TestCase):
    setUp_base = lifecycle.OrderLifecycleTests.setUp
    make_order = lifecycle.OrderLifecycleTests.make_order

    def setUp(self):
        self.setUp_base()
        self.order, _vehicle = self.make_order()
        self.credit = AccessoryProduct.objects.create(name="配件金 1000", kind="credit", sale_price=Decimal("-1000"))
        self.helmet = AccessoryProduct.objects.create(name="安全帽", sale_price=Decimal("500"), labor_fee=Decimal("100"))

    def line_form(self, product, allow_manual=False, instance=None, **extra):
        payload = {"accessory_category": "", "accessory_product": str(product.pk), "custom_name": "", "quantity": "1",
                   "line_type": "purchase", "amount": "", "labor_fee": "", "note": ""}
        payload.update(extra)
        return AccessoryLineForm(payload, instance=instance or AccessoryLine(order=self.order), allow_manual=allow_manual)

    def add_line(self, product, quantity=1, line_type="purchase"):
        return AccessoryLine.objects.create(
            order=self.order, accessory_product=product, name=product.name, quantity=quantity, line_type=line_type,
            amount=ZERO if line_type == "gift" else product.sale_price, labor_fee=ZERO if line_type == "gift" else product.labor_fee,
            is_credit=product.is_credit,
        )

    def reload(self):
        return SalesOrder.objects.get(pk=self.order.pk)


class NegativePriceLoopholeTests(AccessoryCreditBase):
    """修正前的漏洞（T-305 調查時以重現測試證實），現在都要被擋。"""

    def test_master_form_rejects_negative_price_for_normal_accessory(self):
        form = AccessoryProductForm(product_payload(name="負數測試", sale_price="-1000"))
        self.assertFalse(form.is_valid())
        self.assertIn("金額不可小於零。", form.errors["sale_price"])
        form = AccessoryProductForm(product_payload(name="負工資", sale_price="0", labor_fee="-200"))
        self.assertFalse(form.is_valid())
        self.assertIn("金額不可小於零。", form.errors["labor_fee"])

    def test_bulk_edit_rejects_negative_values(self):
        form = AccessoryProductBulkForm({"p-name": self.helmet.name, "p-sale_price": "-500", "p-labor_fee": "-200", "p-cost": "", "p-active": "on"},
                                        instance=self.helmet, prefix="p")
        self.assertFalse(form.is_valid())
        self.assertIn("sale_price", form.errors)
        self.assertIn("labor_fee", form.errors)

    def test_database_rejects_negative_normal_accessory(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            AccessoryProduct.objects.create(name="繞過表單", sale_price=Decimal("-1000"))
        with self.assertRaises(IntegrityError), transaction.atomic():
            AccessoryProduct.objects.create(name="繞過表單工資", labor_fee=Decimal("-1"))

    def test_database_rejects_negative_order_line_that_is_not_credit(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            AccessoryLine.objects.create(order=self.order, name="負數配件", amount=Decimal("-1000"))
        with self.assertRaises(IntegrityError), transaction.atomic():
            AccessoryLine.objects.create(order=self.order, name="負工資", amount=ZERO, labor_fee=Decimal("-300"))

    def test_without_pricing_permission_normal_accessory_stays_positive(self):
        line = self.line_form(self.helmet, allow_manual=False, quantity="3").save()
        self.assertEqual((line.amount, line.labor_fee, line.is_credit), (Decimal("500"), Decimal("100"), False))
        self.assertEqual(self.reload().accessory_total, Decimal("1800"))

    def test_custom_name_still_cannot_be_negative(self):
        for allow_manual in (False, True):
            form = AccessoryLineForm({"accessory_category": "", "accessory_product": "other", "custom_name": "手機架", "quantity": "1",
                                      "line_type": "gift", "amount": "-1000", "labor_fee": "", "note": ""},
                                     instance=AccessoryLine(order=self.order), allow_manual=allow_manual)
            form.data = {**form.data, "line_type": "purchase"}
            self.assertFalse(form.is_valid())
            self.assertIn("金額不可小於零。", form.errors["amount"])

    def test_with_pricing_permission_normal_accessory_cannot_be_negative(self):
        form = self.line_form(self.helmet, allow_manual=True, amount="-500")
        self.assertFalse(form.is_valid())
        self.assertIn("金額不可小於零。", form.errors["amount"])


class CreditMasterTests(AccessoryCreditBase):
    def test_credit_is_entered_as_positive_amount_and_stored_negative(self):
        form = AccessoryProductForm(product_payload(name="配件金 2000", kind="credit", sale_price="2000", labor_fee=""))
        self.assertTrue(form.is_valid(), form.errors)
        product = form.save()
        self.assertEqual((product.kind, product.sale_price, product.labor_fee, product.credit_amount),
                         ("credit", Decimal("-2000"), ZERO, Decimal("2000")))
        self.assertEqual(AccessoryProductForm(instance=product).initial["sale_price"], Decimal("2000"))

    def test_credit_needs_amount_and_has_no_labor_or_cost(self):
        form = AccessoryProductForm(product_payload(name="配件金 0", kind="credit", sale_price="0"))
        self.assertIn("請填配件金金額（大於 0）。", form.errors["sale_price"])
        form = AccessoryProductForm(product_payload(name="配件金工資", kind="credit", sale_price="1000", labor_fee="200"))
        self.assertIn("配件金沒有安裝工資，請留 0。", form.errors["labor_fee"])
        form = AccessoryProductForm(product_payload(name="配件金成本", kind="credit", sale_price="1000", cost="300"))
        self.assertIn("配件金沒有成本，請留空。", form.errors["cost"])

    def test_old_form_without_kind_keeps_existing_kind(self):
        form = AccessoryProductForm({"name": self.credit.name, "sale_price": "1500", "labor_fee": "0", "cost": "", "active": "on", "note": ""},
                                    instance=self.credit)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual((form.save().kind, self.credit.sale_price), ("credit", Decimal("-1500")))

    def test_kind_cannot_change_once_used_by_an_order(self):
        self.add_line(self.helmet)
        form = AccessoryProductForm(product_payload(name=self.helmet.name, kind="credit", sale_price="500"), instance=self.helmet)
        self.assertIn("已有訂單使用這一項，不能改種類；請另外新增一筆。", form.errors["kind"])
        unused = AccessoryProduct.objects.create(name="還沒用過", sale_price=Decimal("300"))
        form = AccessoryProductForm(product_payload(name=unused.name, kind="credit", sale_price="300"), instance=unused)
        self.assertTrue(form.is_valid(), form.errors)

    def test_bulk_edit_shows_credit_as_positive_and_keeps_it_negative(self):
        form = AccessoryProductBulkForm(instance=self.credit, prefix="p")
        self.assertEqual(form.initial["sale_price"], Decimal("1000"))
        form = AccessoryProductBulkForm({"p-name": self.credit.name, "p-sale_price": "1000", "p-labor_fee": "0", "p-cost": "", "p-active": "on"},
                                        instance=self.credit, prefix="p")
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().sale_price, Decimal("-1000"))

    def test_credit_and_normal_accessory_cannot_be_merged(self):
        other_credit = AccessoryProduct.objects.create(name="配件金 500", kind="credit", sale_price=Decimal("-500"))
        targets = list(AccessoryProductMergeForm(source=self.credit).fields["target"].queryset)
        self.assertEqual(targets, [other_credit])
        self.assertNotIn(self.credit, AccessoryProductMergeForm(source=self.helmet).fields["target"].queryset)

    def test_database_keeps_credit_negative_without_labor(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            AccessoryProduct.objects.create(name="正的配件金", kind="credit", sale_price=Decimal("1000"))
        with self.assertRaises(IntegrityError), transaction.atomic():
            AccessoryProduct.objects.create(name="有工資的配件金", kind="credit", sale_price=Decimal("-1000"), labor_fee=Decimal("100"))

    def test_only_accessory_maintainers_can_create_credit(self):
        clerk = get_user_model().objects.create_user("t305-clerk")
        UserAccessState.objects.create(user=clerk, configured=True)
        ScreenAccessGrant.objects.create(user=clerk, screen_key="orders", view=True, operate=True)
        self.client.force_login(clerk)
        response = self.client.post(reverse("accessory_product_create"), product_payload(name="偷建配件金", kind="credit", sale_price="9999"))
        self.assertNotEqual(response.status_code, 302)
        self.assertFalse(AccessoryProduct.objects.filter(name="偷建配件金").exists())
        ScreenAccessGrant.objects.create(user=clerk, screen_key="accessories", view=True, operate=True)
        response = self.client.post(reverse("accessory_product_create"), product_payload(name="店長配件金", kind="credit", sale_price="800"))
        self.assertRedirects(response, reverse("accessory_product_list"), fetch_redirect_response=False)
        self.assertEqual(AccessoryProduct.objects.get(name="店長配件金").sale_price, Decimal("-800"))


class CreditLineTests(AccessoryCreditBase):
    def test_amount_always_comes_from_master_even_with_pricing_permission(self):
        for allow_manual in (False, True):
            form = self.line_form(self.credit, allow_manual=allow_manual, amount="-500", labor_fee="300", quantity="3")
            self.assertTrue(form.is_valid(), form.errors)
            line = form.save()
            self.assertEqual((line.amount, line.labor_fee, line.quantity, line.line_type, line.is_credit, line.name),
                             (Decimal("-1000"), ZERO, 1, "purchase", True, "配件金 1000"))
            line.delete()

    def test_credit_cannot_be_a_gift(self):
        form = self.line_form(self.credit, allow_manual=True, line_type="gift")
        self.assertFalse(form.is_valid())
        self.assertIn("配件金不能設為贈送。", form.errors["line_type"])

    def test_saved_credit_keeps_its_face_value_when_master_changes(self):
        line = self.line_form(self.credit).save()
        AccessoryProduct.objects.filter(pk=self.credit.pk).update(sale_price=Decimal("-2000"))
        self.credit.refresh_from_db()
        form = self.line_form(self.credit, allow_manual=True, instance=line, amount="-1000")
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().amount, Decimal("-1000"))

    def test_switching_credit_line_to_normal_accessory_clears_flag(self):
        line = self.line_form(self.credit).save()
        form = self.line_form(self.helmet, allow_manual=True, instance=line, amount="500", labor_fee="100")
        self.assertTrue(form.is_valid(), form.errors)
        line = form.save()
        self.assertEqual((line.is_credit, line.amount), (False, Decimal("500")))

    def test_unlinked_historic_credit_line_is_kept(self):
        line = self.add_line(self.credit)
        AccessoryLine.objects.filter(pk=line.pk).update(accessory_product=None)
        line.refresh_from_db()
        form = AccessoryLineForm({"accessory_category": "", "accessory_product": "other", "custom_name": line.name, "quantity": "1",
                                  "line_type": "purchase", "amount": "-1000", "labor_fee": "0", "note": ""},
                                 instance=line, allow_manual=True)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual((form.save().amount, line.is_credit), (Decimal("-1000"), True))


class CreditCapTests(AccessoryCreditBase):
    """只折配件、最多折到配件小計 0 元，多的作廢；車價、牌險等不折。"""

    def test_credit_larger_than_accessories_stops_at_zero(self):
        before = self.reload().calculate_balance()
        cheap = AccessoryProduct.objects.create(name="手機架", sale_price=Decimal("500"), labor_fee=Decimal("100"))
        self.add_line(cheap)
        self.add_line(self.credit)
        order = self.reload()
        credit = order.accessory_credit
        self.assertEqual((credit.subtotal, credit.credit_face, credit.credit_applied, credit.credit_void, order.accessory_total),
                         (Decimal("600"), Decimal("1000"), Decimal("600"), Decimal("400"), ZERO))
        self.assertEqual(order.calculate_balance(), before)  # 只少配件那 600，車價等不動

    def test_credit_smaller_than_accessories_is_fully_used(self):
        before = self.reload().calculate_balance()
        self.add_line(self.helmet, quantity=3)  # 1,800
        self.add_line(self.credit)
        order = self.reload()
        self.assertEqual(order.accessory_total, Decimal("800"))
        self.assertEqual(order.calculate_balance(), before + Decimal("800"))
        self.assertEqual(order.accessory_credit.credit_void, ZERO)

    def test_credit_alone_is_zero_and_gifts_do_not_count(self):
        self.add_line(self.credit)
        self.assertEqual(self.reload().accessory_total, ZERO)
        self.add_line(self.helmet, line_type="gift")
        self.assertEqual(self.reload().accessory_total, ZERO)

    def test_labor_is_covered_by_default(self):
        self.assertTrue(accessory_credit.CREDIT_COVERS_LABOR)
        cheap = AccessoryProduct.objects.create(name="腳踏墊", sale_price=Decimal("700"), labor_fee=Decimal("300"))
        self.add_line(cheap)
        self.add_line(self.credit)
        self.assertEqual(self.reload().accessory_total, ZERO)

    def test_rule_switch_price_only(self):
        cheap = AccessoryProduct.objects.create(name="腳踏墊", sale_price=Decimal("700"), labor_fee=Decimal("300"))
        self.add_line(cheap)
        self.add_line(self.credit)
        with mock.patch.object(accessory_credit, "CREDIT_COVERS_LABOR", False):
            order = self.reload()
            self.assertEqual((order.accessory_credit.credit_applied, order.accessory_total), (Decimal("700"), Decimal("300")))

    def test_display_lines_show_applied_amount(self):
        self.add_line(self.helmet)
        self.add_line(self.credit)
        lines = self.reload().accessory_lines
        self.assertEqual([line.effective_total for line in lines], [Decimal("600"), Decimal("-600")])
        self.assertEqual((lines[1].credit_face, lines[1].credit_void), (Decimal("1000"), Decimal("400")))
        self.assertEqual(sum(line.effective_total for line in lines), self.reload().accessory_total)

    def test_discount_basis_follows_credit_but_net_profit_ignores_accessories(self):
        from sales.services import finance_ledger, operations_sync

        self.add_line(self.helmet)
        self.add_line(self.credit)
        order = self.reload()
        self.assertEqual(order.pre_discount_total, order.vehicle_price + order.plate_insurance_fee + order.registration_extra_fee_total
                         + order.effective_installment_fee + order.other_fee_total + order.old_vehicle_tax)
        # 收支與淨利本來就不讀配件（T-202）；配件金也不會進收支。
        for module in (finance_ledger, operations_sync):
            source = open(module.__file__, encoding="utf-8").read()
            self.assertNotIn("accessor", source)


class CreditFormsetRuleTests(AccessoryCreditBase):
    def formset(self, *products, order=None):
        order = order or self.order
        data = {"accessories-TOTAL_FORMS": str(len(products)), "accessories-INITIAL_FORMS": "0",
                "accessories-MIN_NUM_FORMS": "0", "accessories-MAX_NUM_FORMS": "1000"}
        for index, product in enumerate(products):
            data.update({f"accessories-{index}-{key}": value for key, value in {
                "accessory_category": "", "accessory_product": str(product.pk), "custom_name": "", "quantity": "1",
                "line_type": "purchase", "amount": "", "labor_fee": "", "note": ""}.items()})
        return OrderPageAccessoryFormSet(data, instance=order, prefix="accessories", form_kwargs={"allow_manual": True})

    def test_wizard_preview_uses_the_same_cap(self):
        from sales.forms import AccessoryFormSet

        formset = self.formset(self.helmet, self.credit)
        data = {key: value for key, value in formset.data.items()}
        wizard = AccessoryFormSet(data, prefix="accessories", form_kwargs={"allow_manual": False})
        self.assertTrue(wizard.is_valid(), wizard.errors)
        result = accessory_credit.breakdown(accessory_credit.form_lines(wizard))
        self.assertEqual((result.subtotal, result.credit_applied, result.total), (Decimal("600"), Decimal("600"), ZERO))

    def test_one_credit_per_order(self):
        self.assertEqual(accessory_credit.MAX_CREDIT_LINES_PER_ORDER, 1)
        self.assertTrue(self.formset(self.helmet, self.credit).is_valid())
        formset = self.formset(self.credit, self.helmet, self.credit)
        self.assertFalse(formset.is_valid())
        self.assertEqual(formset.forms[0].errors, {})
        self.assertIn("每張訂單最多 1 筆配件金。", formset.forms[2].errors["accessory_product"])

    def test_rule_switch_unlimited_credits(self):
        with mock.patch.object(accessory_credit, "MAX_CREDIT_LINES_PER_ORDER", None):
            self.assertTrue(self.formset(self.credit, self.credit).is_valid())

    def test_dealer_orders_can_use_credit_by_default(self):
        dealer_order, _vehicle = self.make_order(dealer=True)
        self.assertTrue(accessory_credit.ALLOW_DEALER_ORDERS)
        self.assertTrue(self.formset(self.credit, order=dealer_order).is_valid())

    def test_rule_switch_dealer_orders_cannot_use_credit(self):
        dealer_order, _vehicle = self.make_order(dealer=True)
        with mock.patch.object(accessory_credit, "ALLOW_DEALER_ORDERS", False):
            formset = self.formset(self.credit, order=dealer_order)
            self.assertFalse(formset.is_valid())
            self.assertIn("車行單不能使用配件金。", formset.forms[0].errors["accessory_product"])
            self.assertTrue(self.formset(self.credit).is_valid())


class CreditOutputTests(AccessoryCreditBase):
    """訂單明細、訂購單、匯出、收款摘要看得出是配件金；交車清單不列。"""

    def setUp(self):
        super().setUp()
        self.add_line(self.helmet)
        self.add_line(self.credit)
        self.order = self.reload()

    def test_contract_pdf_rows_add_up_to_total(self):
        from sales.services.order_contract_pdf import printed_detail_total

        self.assertEqual(printed_detail_total(self.order) - self.order.vehicle_price - (self.order.plate_insurance_fee or ZERO)
                         - self.order.registration_extra_fee_total - self.order.other_fee_total, ZERO)

    def test_payment_summary_lists_credit_with_applied_amount(self):
        from sales.services.payment_summary import balance_breakdown

        self.add_line(self.helmet, quantity=2)  # 小計 1,800，配件金全額折 1,000
        accessories = next(row for row in balance_breakdown(self.reload())["charges"] if row["label"] == "配件")
        self.assertEqual(accessories["amount"], Decimal("800"))
        self.assertIn(("配件金 1000（配件金）", Decimal("-1000")), accessories["items"])
        self.assertEqual(sum(amount for _name, amount in accessories["items"]), accessories["amount"])

    def test_overview_marks_credit(self):
        from sales.services.order_overview import build_order_overview

        table = next(table for table in build_order_overview(self.order)["tables"] if table["key"] == "accessories")
        row = next(row for row in table["rows"] if row[0] == "配件金 1000")
        self.assertEqual(row[1], "配件金")
        self.assertIn("400 元作廢", row[6])

    def test_export_column_marks_credit(self):
        from sales.order_exchange.columns import _accessories

        self.assertIn("配件金 1000（配件金）-1,000，實際折抵 -600", _accessories(self.order))

    def test_delivery_checklist_skips_credit(self):
        self.assertEqual([line.name for line in self.order.delivery_accessory_lines], ["安全帽"])

    def test_order_detail_page_marks_credit(self):
        self.client.force_login(get_user_model().objects.create_superuser("t305-root", password="testing-only-123"))
        page = self.client.get(reverse("order_detail", args=[self.order.pk]))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "data-accessory-credit-note")
        self.assertContains(page, '"credit": true')
