"""機種總表的資訊密度：每個機種一列、主值＋一行小字，顏色用色點與點開清單，操作鈕橫排。"""
import re
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from sales.models import VehicleColor, VehicleModel
from sales.templatetags.sales_format import color_swatch_style

APP_CSS = Path(settings.BASE_DIR) / "static" / "css" / "app.css"


class ColorSwatchStyleTests(SimpleTestCase):
    def test_base_color_character_picks_the_dot_hue(self):
        self.assertEqual(color_swatch_style("維蘇威黑"), "--dot-a: var(--hue-black); --dot-b: var(--hue-black)")
        self.assertEqual(color_swatch_style("卡拉拉白"), "--dot-a: var(--hue-white); --dot-b: var(--hue-white)")

    def test_two_tone_names_split_the_dot(self):
        self.assertEqual(color_swatch_style("黑紅"), "--dot-a: var(--hue-black); --dot-b: var(--hue-red)")
        self.assertEqual(color_swatch_style("白銀藍"), "--dot-a: var(--hue-white); --dot-b: var(--hue-silver)")

    def test_metallic_is_not_read_as_gold_and_unknown_names_stay_neutral(self):
        self.assertEqual(color_swatch_style("金屬灰"), "--dot-a: var(--hue-gray); --dot-b: var(--hue-gray)")
        self.assertEqual(color_swatch_style("香榭"), "")
        self.assertEqual(color_swatch_style(None), "")


class VehicleModelListDensityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.root = get_user_model().objects.create_superuser("admin", password="Test-Only-123")
        cls.model = VehicleModel.objects.create(
            brand="SUZUKI", name="密度測試車", model_number="DN125", model_year=2026,
            model_code=VehicleModel.ModelType.FRONT_DISC_REAR_DRUM,
            energy_type=VehicleModel.EnergyType.GAS, displacement_cc=124,
        )
        for name in ("卡拉拉白", "白", "科莫藍", "維蘇威黑", "羅馬灰", "蒙地拿紅", "黑紅", "消光黑"):
            VehicleColor.objects.create(vehicle_model=cls.model, name=name)

    def setUp(self):
        self.client.force_login(self.root)
        self.html = self.client.get(reverse("vehicle_model_list")).content.decode()
        self.row = re.search(r'<tr class="vehicle-model-family-group[^"]*"[^>]*>(.*?)</tr>', self.html, re.S).group(1)

    def test_one_row_per_model_with_compact_columns(self):
        header = re.search(r"<thead>(.*?)</thead>", self.html, re.S).group(1)
        self.assertEqual(header.count("<th"), 9)
        self.assertEqual(self.row.count("<td"), 9)
        machine = re.search(r'class="vehicle-model-machine-cell">(.*?)</td>', self.row, re.S).group(1)
        self.assertIn("密度測試車", machine)
        self.assertIn("<small>DN125</small>", machine)
        self.assertIn("<strong>124 c.c.</strong>", self.row)
        self.assertNotIn("<span>排氣量</span>", self.row)

    def test_colors_show_dots_count_and_a_full_list_on_demand(self):
        cell = re.search(r'data-label="啟用顏色">(.*?)</td>', self.row, re.S).group(1)
        self.assertIn("<strong>8 種</strong>", cell)
        dots = re.search(r'class="color-peek__dots"[^>]*>(.*?)</i>\s*<small', cell, re.S).group(1)
        self.assertEqual(dots.count('class="color-dot"'), 6)
        self.assertIn("<b>+2</b>", dots)
        self.assertIn(f'popovertarget="vm-colors-{self.model.pk}"', cell)
        self.assertIn(f'id="vm-colors-{self.model.pk}" popover', cell)
        panel = cell.split("popover>", 1)[1]
        self.assertEqual(panel.count("<li>"), 8)
        self.assertIn("--dot-a: var(--hue-black); --dot-b: var(--hue-red)", panel)
        self.assertIn("vehicle-model-color-peek.js", self.html)

    def test_actions_sit_side_by_side_and_headers_stay_visible(self):
        css = APP_CSS.read_text(encoding="utf-8")
        self.assertIn(".vehicle-model-row-actions { display: flex; align-items: center; justify-content: flex-end;", css)
        self.assertNotRegex(css, r"\.vehicle-model-row-actions \{[^}]*flex-direction: column")
        self.assertRegex(css, r"\.master-model-table thead th \{\s*position: sticky;")
        self.assertRegex(css, r"\.vehicle-brand-group\[open\] > \.vehicle-brand-group__header \{\s*position: sticky;")
        self.assertIn('grid-template-areas: "name name status" "year power price" "color color stock" "reward reward actions";', css)
