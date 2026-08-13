from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from sales.forms import (
    BrandRegistrationFeeRuleForm,
    DealerVolumeBonusRuleForm,
    SalesSourceBrandPolicyForm,
    VehicleModelMasterForm,
)
from sales.models import SalesSourceBrandPolicy, VehicleBrand, VehicleModel
from sales.services.vehicle_brands import canonical_vehicle_brand_name


class VehicleBrandMasterTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="brand-admin", password="test-pass-123"
        )
        self.client.force_login(self.user)

    def test_common_brands_are_seeded_and_brand_fields_are_dropdowns(self):
        self.assertTrue(VehicleBrand.objects.filter(name="SUZUKI").exists())
        self.assertTrue(VehicleBrand.objects.filter(name="Gogoro").exists())

        for form_class in (
            VehicleModelMasterForm,
            SalesSourceBrandPolicyForm,
            DealerVolumeBonusRuleForm,
            BrandRegistrationFeeRuleForm,
        ):
            with self.subTest(form=form_class.__name__):
                form = form_class()
                self.assertEqual(form.fields["brand"].widget.input_type, "select")
                self.assertIn(
                    ("SUZUKI", "SUZUKI"), list(form.fields["brand"].choices)
                )

    def test_brand_page_creates_brand_and_rejects_ambiguous_alias(self):
        response = self.client.post(
            reverse("vehicle_brand_list"),
            {
                "name": "New Brand",
                "aliases": "新品牌、NEWBRAND",
                "display_order": 300,
                "active": "on",
                "note": "測試",
            },
        )
        self.assertRedirects(response, reverse("vehicle_brand_list"))
        self.assertTrue(VehicleBrand.objects.filter(name="New Brand").exists())

        response = self.client.post(
            reverse("vehicle_brand_list"),
            {
                "name": "Another Brand",
                "aliases": "新品牌",
                "display_order": 301,
                "active": "on",
                "note": "",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "名稱或別名已由")

    def test_used_brand_name_is_locked_but_other_fields_can_be_updated(self):
        brand = VehicleBrand.objects.create(name="測試舊品牌", display_order=800)
        vehicle_model = VehicleModel.objects.create(
            brand=brand.name,
            name="TEST 125",
            model_number="T125",
            model_year=2026,
            model_code=VehicleModel.ModelType.DRUM,
            energy_type=VehicleModel.EnergyType.GAS,
            displacement_cc=125,
        )
        response = self.client.post(
            f"{reverse('vehicle_brand_list')}?edit={brand.pk}",
            {
                "name": "測試新品牌",
                "aliases": "測試舊品牌",
                "display_order": 800,
                "active": "on",
                "note": "保留歷史關聯",
            },
        )
        self.assertRedirects(response, reverse("vehicle_brand_list"))
        vehicle_model.refresh_from_db()
        brand.refresh_from_db()
        self.assertEqual(vehicle_model.brand, "測試舊品牌")
        self.assertEqual(brand.name, "測試舊品牌")
        self.assertEqual(brand.note, "保留歷史關聯")

    def test_unused_brand_can_be_renamed(self):
        brand = VehicleBrand.objects.create(name="尚未使用品牌", display_order=801)
        response = self.client.post(
            f"{reverse('vehicle_brand_list')}?edit={brand.pk}",
            {
                "name": "新的品牌名稱",
                "aliases": "尚未使用品牌",
                "display_order": 801,
                "active": "on",
                "note": "",
            },
        )
        self.assertRedirects(response, reverse("vehicle_brand_list"))
        brand.refresh_from_db()
        self.assertEqual(brand.name, "新的品牌名稱")

    def test_alias_is_normalized_for_imports(self):
        self.assertEqual(
            canonical_vehicle_brand_name("台鈴 Suzuki", create_missing=True),
            "SUZUKI",
        )
        self.assertEqual(
            canonical_vehicle_brand_name("GOGORO", create_missing=True),
            "Gogoro",
        )

    def test_maintenance_hub_links_to_brand_master(self):
        response = self.client.get(reverse("data_maintenance"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("vehicle_brand_list"))
        self.assertContains(response, "品牌資料")
