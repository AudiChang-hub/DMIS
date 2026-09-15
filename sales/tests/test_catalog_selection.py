from datetime import timedelta
from django.core.exceptions import ValidationError
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from sales.models import (VehicleCatalogEntry, VehicleModel, VehicleColor, VehiclePriceVersion,
    InstallmentCompany, InstallmentPlanVersion, InstallmentPlanOption, SalesOrder, OrderDraft)
from sales.services.catalog_selection import selection_data, sign_selection, validate_selection
from sales.tests import test_reception_entry as reception_fixture


class CatalogSelectionTests(TestCase):
    image = reception_fixture.ReceptionEntryTests.image
    complete_data = reception_fixture.ReceptionEntryTests.complete_data
    submit = reception_fixture.ReceptionEntryTests.submit

    def setUp(self):
        reception_fixture.ReceptionEntryTests.setUp(self)
        self.client.force_login(self.root)
        self.entry = VehicleCatalogEntry.objects.create(vehicle_model=self.model, published=True)
        self.company = InstallmentCompany.objects.create(name="有效分期公司")
        self.plan = InstallmentPlanVersion.objects.create(vehicle_model=self.model, effective_from=timezone.localdate() - timedelta(days=30))
        self.option = InstallmentPlanOption.objects.create(version=self.plan, company=self.company, periods=24, monthly_amount=3500, opening_fee=500)

    def token(self, installment=False):
        return sign_selection(selection_data(self.model, self.color, "installment" if installment else "cash", self.option if installment else None))

    def test_detail_selected_color_payment_and_bottom_action(self):
        page = self.client.get(reverse("catalog_detail", args=[self.model.pk]), {"color": self.color.pk})
        self.assertContains(page, "已選車色")
        self.assertContains(page, "更換車色")
        self.assertNotContains(page, 'name="color"')
        self.assertEqual(len(page.context["payment_choices"]), 2)
        self.assertEqual(set(page.context["options"][0]), {"company", "periods", "monthly_amount", "opening_fee"})
        body = page.content.decode()
        self.assertGreater(body.index("確認選擇，接續填單"), body.index("售價與分期"))
        for choice in page.context["payment_choices"]:
            self.assertNotIn("expected_disbursement", validate_selection(choice["token"]))
        self.assertNotContains(page, "expected_disbursement")

    def test_cash_and_installment_prefill_and_submit_server_amounts(self):
        for installment in (False, True):
            with self.subTest(installment=installment):
                token = self.token(installment)
                page = self.client.get(reverse("order_start"), {"selection": token})
                form = page.context["form"]
                self.assertEqual(str(form["color"].value()), str(self.color.pk))
                self.assertEqual(form["payment_type"].value(), "installment" if installment else "cash")
                self.assertEqual(form["catalog_selection"].value(), token)
                self.assertContains(page, "已選車款與付款方案")
                response = self.submit(catalog_selection=token, payment_type="installment" if installment else "cash",
                    installment_company=self.company.name if installment else "", installment_periods=24 if installment else 0,
                    installment_monthly=1, installment_opening_fee=1, vehicle_price=1)
                self.assertEqual(response.status_code, 302, response.context and response.context["form"].errors)
                order = SalesOrder.objects.latest("pk")
                self.assertEqual(order.vehicle_price, 79800)
                self.assertEqual(order.installment_monthly, 3500 if installment else 0)
                self.assertEqual(order.installment_opening_fee, 500 if installment else 0)

    def test_draft_resume_preserves_choice_and_rejects_changed_plan(self):
        token = self.token(True)
        payload = {**self.complete_data(), "catalog_selection": token, "payment_type": "installment",
                   "installment_company": self.company.name, "installment_periods": "24"}
        result = self.client.post(reverse("intake_draft_save"), payload)
        self.assertEqual(result.status_code, 200)
        draft = OrderDraft.objects.get()
        self.assertEqual(draft.data["catalog_selection"], token)
        resumed = self.client.get(reverse("order_start"), {"draft": draft.pk})
        self.assertEqual(resumed.context["form"]["installment_periods"].value(), "24")
        self.option.monthly_amount = 3700
        self.option.save()
        response = self.submit(**{k:v for k,v in payload.items() if k not in {"id_front", "id_back"}})
        self.assertEqual(response.status_code, 200)
        self.assertIn("catalog_selection", response.context["form"].errors)
        self.assertEqual(response.context["form"]["owner_name"].value(), payload["owner_name"])
        self.assertFalse(SalesOrder.objects.exists())

    def test_changed_price_disabled_color_company_and_expired_version(self):
        token = self.token(True)
        changes = [(self.color, "active", False), (self.company, "active", False),
                   (self.plan, "effective_to", timezone.localdate() - timedelta(days=1)),
                   (VehiclePriceVersion.objects.get(vehicle_model=self.model), "cash_price", 80000)]
        for instance, field, value in changes:
            original = getattr(instance, field)
            setattr(instance, field, value)
            instance.save()
            with self.assertRaises(ValidationError):
                validate_selection(token)
            setattr(instance, field, original)
            instance.save()
        with self.assertRaises(ValidationError):
            validate_selection(token + "tamper")
        self.assertEqual(self.client.get(reverse("order_start"), {"selection": "tamper"}).status_code, 302)

    def test_foreign_color_or_payment_tamper_requires_reconfirm(self):
        response = self.submit(catalog_selection=self.token(True), payment_type="cash")
        self.assertIn("catalog_selection", response.context["form"].errors)
        another = VehicleColor.objects.create(vehicle_model=self.model, name="另一色")
        response = self.submit(catalog_selection=self.token(), color=another.pk)
        self.assertIn("catalog_selection", response.context["form"].errors)

    def test_login_return_keeps_selection_and_dealer_receives_same_terms(self):
        token = self.token(True)
        response = Client().get(reverse("order_start"), {"selection": token})
        self.assertEqual(response.status_code, 302)
        self.assertIn("selection", response.url)
        self.client.force_login(self.dealer_user)
        page = self.client.get(reverse("order_start"), {"selection": token})
        self.assertEqual(page.context["form"]["payment_type"].value(), "installment")
        response = self.submit(catalog_selection=token, payment_type="installment", installment_periods=24, installment_company=self.company.name)
        self.assertEqual(response.status_code, 302, response.context and response.context["form"].errors)
        self.profile.can_submit_orders = False
        self.profile.save()
        self.assertEqual(self.client.get(reverse("order_start"), {"selection": token}).status_code, 403)

    def test_shared_filters_intersection_scope_order_and_old_model_link(self):
        other = VehicleModel.objects.create(brand="另一品牌", name="另一車型", model_number="E-100", energy_type="electric")
        VehicleColor.objects.create(vehicle_model=other, name="黑")
        VehicleCatalogEntry.objects.create(vehicle_model=other, published=False)
        public = self.client.get(reverse("catalog"))
        manage = self.client.get(reverse("catalog_manage"), {"energy": "electric"})
        self.assertNotIn("另一品牌", public.context["brands"])
        self.assertEqual(list(manage.context["page_obj"]), [other])
        for route in ("catalog", "catalog_manage"):
            page = self.client.get(reverse(route))
            body = page.content.decode()
            indexes = [body.index(f'name="{field}"') for field in ("brand", "model_name", "model_number", "energy")]
            self.assertEqual(indexes, sorted(indexes))
        empty = self.client.get(reverse("catalog"), {"brand": self.model.brand, "energy": "electric"})
        self.assertEqual(empty.context["page_obj"].paginator.count, 0)
        self.assertEqual(self.client.get(reverse("catalog"), {"model": self.model.pk}).context["model_count"], 1)
