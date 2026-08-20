import tempfile
from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from sales.forms import (
    BrandRegistrationFeeRuleForm,
    DealerVolumeBonusRuleForm,
    SalesSourceBrandPolicyForm,
    VehicleModelMasterForm,
)
from sales.models import SalesSourceBrandPolicy, VehicleBrand, VehicleModel
from sales.services.brand_logo import build_brand_logo
from sales.services.vehicle_brands import (
    canonical_vehicle_brand_name,
    vehicle_brand_search_names,
)


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
                self.assertIn(
                    ("eMOVING", "SUZUKI｜eMOVING"),
                    list(form.fields["brand"].choices),
                )

    def test_emoving_is_grouped_under_suzuki_without_changing_its_name(self):
        emoving = VehicleBrand.objects.select_related("parent").get(name="eMOVING")

        self.assertEqual(emoving.parent.name, "SUZUKI")
        self.assertEqual(emoving.hierarchy_label, "SUZUKI｜eMOVING")
        self.assertEqual(
            vehicle_brand_search_names("SUZUKI"), ["SUZUKI", "eMOVING"]
        )
        self.assertEqual(vehicle_brand_search_names("eMOVING"), ["eMOVING"])

    def test_parent_brand_search_includes_child_vehicle_models(self):
        child_model = VehicleModel.objects.create(
            brand="eMOVING",
            name="品牌階層測試車",
            model_number="HIERARCHY-01",
            model_year=2026,
            model_code=VehicleModel.ModelType.DRUM,
            energy_type=VehicleModel.EnergyType.ELECTRIC,
        )

        response = self.client.get(reverse("vehicle_model_list"), {"q": "SUZUKI"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, child_model.name)

    def test_vehicle_model_list_uses_root_brand_logo_with_initial_fallback(self):
        with tempfile.TemporaryDirectory() as media_root, override_settings(
            MEDIA_ROOT=media_root
        ):
            suzuki = VehicleBrand.objects.get(name="SUZUKI")
            suzuki.logo = SimpleUploadedFile(
                "suzuki-logo.png",
                b"test-suzuki-logo",
                content_type="image/png",
            )
            suzuki.save(update_fields=["logo", "updated_at"])
            VehicleModel.objects.create(
                brand="SUZUKI",
                name="LOGO 顯示測試車",
                model_number="LOGO-01",
                model_year=2026,
                model_code=VehicleModel.ModelType.DRUM,
                energy_type=VehicleModel.EnergyType.GAS,
            )
            VehicleModel.objects.create(
                brand="SYM",
                name="首字備援測試車",
                model_number="FALLBACK-01",
                model_year=2026,
                model_code=VehicleModel.ModelType.DRUM,
                energy_type=VehicleModel.EnergyType.GAS,
            )

            response = self.client.get(reverse("vehicle_model_list"))

            logo_url = reverse("vehicle_brand_logo", args=[suzuki.pk])
            suzuki_group = next(
                group
                for group in response.context["vehicle_model_groups"]
                if group["name"] == "SUZUKI"
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(suzuki_group["logo_brand"], suzuki)
            self.assertContains(response, logo_url)
            self.assertContains(response, "vehicle-brand-group__mark has-logo")
            self.assertNotContains(response, f'src="{suzuki.logo.url}')

            sym_group = next(
                group
                for group in response.context["vehicle_model_groups"]
                if group["name"] == "SYM"
            )
            self.assertIsNone(sym_group["logo_brand"])

    def test_vehicle_model_list_keeps_two_visual_levels_for_child_brand(self):
        root_model = VehicleModel.objects.create(
            brand="SUZUKI",
            name="主品牌車型",
            model_number="ROOT-01",
            model_year=2026,
            model_code=VehicleModel.ModelType.DRUM,
            energy_type=VehicleModel.EnergyType.GAS,
        )
        child_model = VehicleModel.objects.create(
            brand="eMOVING",
            name="子品牌車型",
            model_number="CHILD-01",
            model_year=2026,
            model_code=VehicleModel.ModelType.DRUM,
            energy_type=VehicleModel.EnergyType.ELECTRIC,
        )

        response = self.client.get(reverse("vehicle_model_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-brand-group="SUZUKI"')
        self.assertNotContains(response, 'data-brand-group="eMOVING"')
        self.assertNotContains(
            response,
            '<details class="vehicle-brand-group"',
            html=False,
        )
        self.assertContains(response, "包含 eMOVING")
        self.assertContains(
            response,
            '<span class="vehicle-model-brand-badge">eMOVING</span>',
            html=True,
        )
        suzuki_group = next(
            group
            for group in response.context["vehicle_model_groups"]
            if group["name"] == "SUZUKI"
        )
        self.assertEqual(
            [model.pk for model in suzuki_group["models"]],
            [child_model.pk, root_model.pk],
        )

    def test_vehicle_models_sort_electric_by_power_then_gas_by_displacement(self):
        brand = VehicleBrand.objects.create(name="動力排序測試", display_order=950)
        specifications = [
            ("油車 125", VehicleModel.EnergyType.GAS, 125, None, True),
            ("電車 3KW", VehicleModel.EnergyType.ELECTRIC, None, 3, True),
            ("油車 50", VehicleModel.EnergyType.GAS, 50, None, True),
            ("電車 1KW", VehicleModel.EnergyType.ELECTRIC, None, 1, True),
            ("微電車 2KW", VehicleModel.EnergyType.MICRO_ELECTRIC, None, 2, True),
            ("電車待補功率", VehicleModel.EnergyType.ELECTRIC, None, None, True),
            ("停用電車", VehicleModel.EnergyType.ELECTRIC, None, 0.5, False),
        ]
        for index, (name, energy, displacement, motor_power, active) in enumerate(specifications):
            VehicleModel.objects.create(
                brand=brand.name,
                name=name,
                model_number=f"SORT-{index}",
                model_year=2026,
                model_code=VehicleModel.ModelType.DRUM,
                energy_type=energy,
                displacement_cc=displacement,
                motor_power_kw=motor_power,
                active=active,
            )

        response = self.client.get(reverse("vehicle_model_list"))

        group = next(
            item
            for item in response.context["vehicle_model_groups"]
            if item["name"] == brand.name
        )
        self.assertEqual(
            [family["name"] for family in group["families"]],
            [
                "電車 1KW",
                "微電車 2KW",
                "電車 3KW",
                "電車待補功率",
                "油車 50",
                "油車 125",
                "停用電車",
            ],
        )

    def test_new_parent_child_brand_is_grouped_without_ui_special_case(self):
        parent = VehicleBrand.objects.get(name="SYM")
        child = VehicleBrand.objects.create(
            name="未來子品牌",
            parent=parent,
            display_order=901,
        )
        child_model = VehicleModel.objects.create(
            brand=child.name,
            name="自動歸類車型",
            model_number="AUTO-GROUP-01",
            model_year=2026,
            model_code=VehicleModel.ModelType.DRUM,
            energy_type=VehicleModel.EnergyType.ELECTRIC,
        )

        response = self.client.get(reverse("vehicle_model_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-brand-group="SYM"')
        self.assertNotContains(response, 'data-brand-group="未來子品牌"')
        sym_group = next(
            group
            for group in response.context["vehicle_model_groups"]
            if group["name"] == "SYM"
        )
        self.assertEqual([model.pk for model in sym_group["models"]], [child_model.pk])

    def test_filtered_vehicle_model_groups_remain_visible_without_brand_folding(self):
        VehicleModel.objects.create(
            brand="eMOVING",
            name="搜尋後展開車型",
            model_number="SEARCH-OPEN-01",
            model_year=2026,
            model_code=VehicleModel.ModelType.DRUM,
            energy_type=VehicleModel.EnergyType.ELECTRIC,
        )

        response = self.client.get(reverse("vehicle_model_list"), {"q": "eMOVING"})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["filters_applied"])
        self.assertContains(response, 'data-filtered="true"')
        self.assertContains(response, 'data-brand-group="SUZUKI"')
        self.assertNotContains(
            response,
            '<details class="vehicle-brand-group"',
            html=False,
        )

    def test_brand_page_shows_parent_brand_and_keeps_child_record(self):
        response = self.client.get(reverse("vehicle_brand_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "品牌關係")
        self.assertIn("logo", response.context["form"].fields)
        self.assertContains(response, "品牌 LOGO")
        self.assertContains(response, "主品牌")
        self.assertContains(response, "子品牌")
        self.assertContains(response, "隸屬 SUZUKI")
        self.assertContains(response, "brand-hierarchy__branch")

    def test_brand_logo_uses_authenticated_media_route(self):
        with tempfile.TemporaryDirectory() as media_root, override_settings(
            MEDIA_ROOT=media_root
        ):
            brand = VehicleBrand.objects.create(
                name="LOGO 測試品牌",
                display_order=910,
                logo=SimpleUploadedFile(
                    "brand-logo.png",
                    b"test-logo-bytes",
                    content_type="image/png",
                ),
            )
            logo_url = reverse("vehicle_brand_logo", args=[brand.pk])

            page = self.client.get(reverse("vehicle_brand_list"))
            self.assertContains(page, logo_url)
            self.assertNotContains(page, brand.logo.url)

            response = self.client.get(logo_url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response["Content-Type"], "image/png")
            self.assertEqual(response["Cache-Control"], "private, max-age=3600")
            self.assertEqual(b"".join(response.streaming_content), b"test-logo-bytes")

            self.client.logout()
            anonymous = self.client.get(logo_url)
            self.assertRedirects(anonymous, f"{reverse('login')}?next={logo_url}")

    def test_brand_logo_returns_not_found_when_no_file_is_configured(self):
        brand = VehicleBrand.objects.create(name="無 LOGO 品牌", display_order=911)

        response = self.client.get(reverse("vehicle_brand_logo", args=[brand.pk]))

        self.assertEqual(response.status_code, 404)

    def test_brand_logo_upload_keeps_original_and_generates_cropped_preview(self):
        with tempfile.TemporaryDirectory() as media_root, override_settings(
            MEDIA_ROOT=media_root
        ):
            brand = VehicleBrand.objects.create(name="裁切測試品牌", display_order=912)
            buffer = BytesIO()
            Image.new("RGB", (400, 400), "red").save(buffer, format="PNG")
            upload = SimpleUploadedFile(
                "square-logo.png", buffer.getvalue(), content_type="image/png"
            )

            response = self.client.post(
                f"{reverse('vehicle_brand_list')}?edit={brand.pk}",
                {
                    "name": brand.name,
                    "parent": "",
                    "aliases": "",
                    "display_order": 912,
                    "active": "on",
                    "note": "",
                    "logo_crop_x": 0,
                    "logo_crop_y": 0.25,
                    "logo_crop_width": 1,
                    "logo_crop_height": 0.5,
                    "logo_crop_changed": "1",
                    "logo": upload,
                },
            )

            self.assertRedirects(response, reverse("vehicle_brand_list"))
            brand.refresh_from_db()
            self.assertTrue(brand.logo)
            self.assertTrue(brand.logo_original)
            self.assertEqual(brand.logo_crop_data["y"], 0.25)
            with brand.logo.open("rb") as rendered:
                with Image.open(rendered) as image:
                    self.assertEqual(image.size, (800, 400))
                    self.assertEqual(image.format, "PNG")
            with brand.logo_original.open("rb") as original:
                with Image.open(original) as image:
                    self.assertEqual(image.size, (400, 400))
            source_response = self.client.get(
                reverse("vehicle_brand_logo_source", args=[brand.pk])
            )
            self.assertEqual(source_response.status_code, 200)
            self.assertTrue(b"".join(source_response.streaming_content))
            source_response.close()

    def test_brand_logo_default_fit_keeps_complete_square_image(self):
        source = BytesIO()
        Image.new("RGBA", (400, 400), (255, 0, 0, 255)).save(source, format="PNG")

        rendered, crop = build_brand_logo(source.getvalue())

        self.assertEqual(crop, {"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0})
        with Image.open(BytesIO(rendered)) as image:
            self.assertEqual(image.size, (800, 400))
            self.assertEqual(image.getpixel((0, 200))[3], 0)
            self.assertEqual(image.getpixel((200, 200)), (255, 0, 0, 255))
            self.assertEqual(image.getpixel((599, 200)), (255, 0, 0, 255))
            self.assertEqual(image.getpixel((799, 200))[3], 0)

    def test_brand_page_exposes_logo_crop_editor_and_global_previews(self):
        response = self.client.get(reverse("vehicle_brand_list"))

        self.assertContains(response, "data-brand-logo-editor")
        self.assertContains(response, "電腦版品牌標頭")
        self.assertContains(response, "手機版品牌標頭")
        self.assertContains(response, "品牌維護列表")
        self.assertContains(response, "恢復完整顯示")
        self.assertContains(response, "上傳後會等比例縮放並完整顯示")
        self.assertContains(response, "brand-logo-editor.js")

    def test_dealer_price_list_entry_points_are_removed(self):
        for route_name in ("data_maintenance", "vehicle_model_list"):
            with self.subTest(route=route_name):
                response = self.client.get(reverse(route_name))
                self.assertEqual(response.status_code, 200)
                self.assertNotContains(response, "每月車行價目表")

    def test_brand_page_creates_brand_and_rejects_ambiguous_alias(self):
        response = self.client.post(
            reverse("vehicle_brand_list"),
            {
                "name": "New Brand",
                "parent": "",
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
                "parent": "",
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
                "parent": "",
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
                "parent": "",
                "aliases": "尚未使用品牌",
                "display_order": 801,
                "active": "on",
                "note": "",
            },
        )
        self.assertRedirects(response, reverse("vehicle_brand_list"))
        brand.refresh_from_db()
        self.assertEqual(brand.name, "新的品牌名稱")

    def test_child_brand_cannot_become_a_third_level_parent(self):
        emoving = VehicleBrand.objects.get(name="eMOVING")
        response = self.client.post(
            reverse("vehicle_brand_list"),
            {
                "name": "第三層品牌",
                "parent": emoving.pk,
                "aliases": "",
                "display_order": 802,
                "active": "on",
                "note": "",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors.get("parent"))
        self.assertFalse(VehicleBrand.objects.filter(name="第三層品牌").exists())

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
