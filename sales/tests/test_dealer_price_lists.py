from datetime import date
from decimal import Decimal
from io import BytesIO
from tempfile import TemporaryDirectory

from PIL import Image
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from sales.models import (
    DealerPriceList,
    InstallmentCompany,
    InstallmentPlanOption,
    InstallmentPlanVersion,
    VehicleBrand,
    VehicleColor,
    VehicleModel,
    VehiclePriceVersion,
)


class DealerPriceListTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="price-admin", password="test-pass-123"
        )
        self.client.force_login(self.user)
        self.brand, _ = VehicleBrand.objects.get_or_create(
            name="價目表測試品牌",
            defaults={"display_order": 900},
        )
        self.model = VehicleModel.objects.create(
            brand=self.brand.name,
            name="測試 125",
            model_number="PRICE-125",
            model_year=2026,
            model_code=VehicleModel.ModelType.FRONT_DISC_REAR_DRUM,
            energy_type=VehicleModel.EnergyType.GAS,
            displacement_cc=125,
        )
        VehicleColor.objects.create(vehicle_model=self.model, name="黑")
        VehicleColor.objects.create(vehicle_model=self.model, name="白")
        self.company = InstallmentCompany.objects.create(name="價目表分期公司")
        VehiclePriceVersion.objects.create(
            vehicle_model=self.model,
            suggested_price_including_registration=75000,
            cash_price=70000,
            effective_from=date(2026, 8, 1),
        )
        old_plan = InstallmentPlanVersion.objects.create(
            vehicle_model=self.model,
            effective_from=date(2026, 8, 1),
        )
        InstallmentPlanOption.objects.create(
            version=old_plan,
            periods=18,
            monthly_amount=3889,
            company=self.company,
            opening_fee=2500,
        )

    def create_draft(self, month="2026-09"):
        response = self.client.post(
            reverse("dealer_price_list_list"),
            {
                "brand": self.brand.pk,
                "period_month": month,
                "title": "",
                "effective_from": "",
                "copy_previous": "on",
            },
        )
        self.assertEqual(response.status_code, 302)
        return DealerPriceList.objects.latest("pk")

    def workspace_payload(self, price_list, *, action="save"):
        item = price_list.items.get(vehicle_model=self.model)
        return {
            "action": action,
            "title": "2026 年 9 月車行價格表",
            "effective_from": "2026-09-01",
            "header_note": "不含牌險，依單據收取",
            "footer_note": "分期專案開辦費另計。",
            "installment_periods_text": "18,24,36",
            f"item-{item.pk}-visible": "on",
            f"item-{item.pk}-section": "domestic",
            f"item-{item.pk}-order": "10",
            f"item-{item.pk}-model-label": "測試 125 七期",
            f"item-{item.pk}-year-label": "26’",
            f"item-{item.pk}-colors-label": "黑／白",
            f"item-{item.pk}-suggested-price": "76000",
            f"item-{item.pk}-cash-discount": "5000",
            f"item-{item.pk}-cash-price": "71000",
            f"item-{item.pk}-installment-18-amount": "4000",
            f"item-{item.pk}-installment-18-company": str(self.company.pk),
            f"item-{item.pk}-installment-18-opening-fee": "2500",
            f"item-{item.pk}-installment-24-amount": "3100",
            f"item-{item.pk}-installment-24-company": str(self.company.pk),
            f"item-{item.pk}-installment-24-opening-fee": "2500",
            f"item-{item.pk}-installment-36-amount": "",
            f"item-{item.pk}-installment-36-company": "",
            f"item-{item.pk}-installment-36-opening-fee": "",
            f"item-{item.pk}-customer-gift": "現金優惠折抵 5,000 元",
            f"item-{item.pk}-channel": "2",
            f"item-{item.pk}-note": "數量有限",
        }

    def test_create_draft_prefills_vehicle_price_color_and_installment(self):
        price_list = self.create_draft()

        self.assertEqual(price_list.period_month, date(2026, 9, 1))
        self.assertEqual(price_list.installment_periods, [18, 24, 36, 48, 60])
        item = price_list.items.get()
        self.assertEqual(item.colors_label, "白／黑")
        self.assertEqual(item.suggested_price, Decimal("75000"))
        self.assertEqual(item.cash_discount, Decimal("5000"))
        self.assertEqual(item.installments["18"]["company_name"], self.company.name)

        response = self.client.get(
            reverse("dealer_price_list_workspace", args=[price_list.pk])
        )
        self.assertContains(response, "所見即所得編輯")
        self.assertContains(response, 'data-dealer-sheet')
        self.assertContains(response, f'name="item-{item.pk}-cash-price"')
        self.assertContains(response, "現金優惠折抵 5,000 元", count=0)
        self.assertContains(response, self.company.name)

    def test_save_and_publish_updates_effective_price_and_installment_versions(self):
        price_list = self.create_draft()
        response = self.client.post(
            reverse("dealer_price_list_workspace", args=[price_list.pk]),
            self.workspace_payload(price_list, action="save_and_publish"),
        )

        self.assertRedirects(
            response, reverse("dealer_price_list_workspace", args=[price_list.pk])
        )
        price_list.refresh_from_db()
        self.assertEqual(price_list.status, DealerPriceList.Status.PUBLISHED)
        new_price = VehiclePriceVersion.objects.get(
            vehicle_model=self.model, effective_from=date(2026, 9, 1)
        )
        self.assertEqual(new_price.suggested_price_including_registration, 76000)
        self.assertEqual(new_price.cash_price, 71000)
        self.assertEqual(
            VehiclePriceVersion.objects.get(
                vehicle_model=self.model, effective_from=date(2026, 8, 1)
            ).effective_to,
            date(2026, 8, 31),
        )
        plan = InstallmentPlanVersion.objects.get(
            vehicle_model=self.model, effective_from=date(2026, 9, 1)
        )
        self.assertEqual(
            list(plan.options.values_list("periods", "monthly_amount")),
            [(18, Decimal("4000")), (24, Decimal("3100"))],
        )

        print_response = self.client.get(
            reverse("dealer_price_list_print", args=[price_list.pk])
        )
        self.assertContains(print_response, "測試 125 七期")
        self.assertContains(print_response, "現金優惠折抵 5,000 元")
        self.assertContains(print_response, "4,000")

    def test_published_list_requires_revision_for_changes(self):
        price_list = self.create_draft()
        self.client.post(
            reverse("dealer_price_list_workspace", args=[price_list.pk]),
            self.workspace_payload(price_list, action="save_and_publish"),
        )

        response = self.client.post(
            reverse("dealer_price_list_revise", args=[price_list.pk])
        )

        self.assertEqual(response.status_code, 302)
        revised = DealerPriceList.objects.exclude(pk=price_list.pk).get()
        self.assertEqual(revised.status, DealerPriceList.Status.DRAFT)
        self.assertEqual(revised.revision, 2)
        self.assertEqual(revised.items.get().customer_gift, "現金優惠折抵 5,000 元")

    def test_print_does_not_fall_back_to_hidden_rows(self):
        price_list = self.create_draft()
        item = price_list.items.get()
        item.visible = False
        item.save(update_fields=["visible", "updated_at"])

        response = self.client.get(
            reverse("dealer_price_list_print", args=[price_list.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, item.model_label)

    def test_save_and_print_persists_inline_sheet_and_uses_shared_print_layout(self):
        price_list = self.create_draft()
        payload = self.workspace_payload(price_list, action="save_and_print")
        payload["title"] = "直接編輯後的九月價目表"

        response = self.client.post(
            reverse("dealer_price_list_workspace", args=[price_list.pk]), payload
        )

        self.assertRedirects(
            response,
            reverse("dealer_price_list_print", args=[price_list.pk]),
            fetch_redirect_response=False,
        )
        price_list.refresh_from_db()
        self.assertEqual(price_list.title, "直接編輯後的九月價目表")
        print_response = self.client.get(
            reverse("dealer_price_list_print", args=[price_list.pk])
        )
        self.assertContains(print_response, "直接編輯後的九月價目表")
        self.assertContains(print_response, "data-dealer-sheet")
        self.assertNotContains(print_response, 'name="title"')

    def test_brand_logo_upload_is_available_to_price_list(self):
        with TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                buffer = BytesIO()
                Image.new("RGB", (180, 60), "white").save(buffer, format="PNG")
                upload = SimpleUploadedFile(
                    "brand-logo.png", buffer.getvalue(), content_type="image/png"
                )
                response = self.client.post(
                    reverse("vehicle_brand_list"),
                    {
                        "name": "LOGO 測試品牌",
                        "parent": "",
                        "logo": upload,
                        "aliases": "",
                        "display_order": "950",
                        "active": "on",
                        "note": "",
                    },
                )
                self.assertRedirects(response, reverse("vehicle_brand_list"))
                self.assertTrue(VehicleBrand.objects.get(name="LOGO 測試品牌").logo)
