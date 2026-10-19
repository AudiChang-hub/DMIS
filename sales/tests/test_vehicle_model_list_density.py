"""機種總表的資訊密度：每個機種一列、主值＋一行小字，顏色只列數量與色名（可點開看全部），操作鈕橫排。"""
import re
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from sales.models import VehicleColor, VehicleModel

APP_CSS = Path(settings.BASE_DIR) / "static" / "css" / "app.css"


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

    def test_colors_show_count_and_whole_names_without_swatches(self):
        cell = re.search(r'data-label="啟用顏色">(.*?)</td>', self.row, re.S).group(1)
        names = re.search(r'<span class="color-peek__names">(.*?)</span>\s*</button>', cell, re.S).group(1)
        self.assertTrue(names.startswith("<strong>8 種</strong>"))
        # 每個色名（連同頓號）包成一段，換行時不會把「維蘇威黑」拆開。
        self.assertIn("<span>維蘇威黑、</span>", names)
        self.assertIn("<span>黑紅</span>", names)
        self.assertEqual(names.count("<span>"), 8)
        self.assertIn('title="卡拉拉白、消光黑、白、科莫藍、維蘇威黑、羅馬灰、蒙地拿紅、黑紅"', cell)
        self.assertNotIn("color-dot", self.html)
        self.assertNotIn("--hue-", self.html)
        self.assertIn(f'popovertarget="vm-colors-{self.model.pk}"', cell)
        panel = cell.split("popover>", 1)[1]
        self.assertEqual(panel.count("<li>"), 8)
        self.assertIn("<li>維蘇威黑</li>", panel)
        self.assertIn("vehicle-model-color-peek.js", self.html)
        css = APP_CSS.read_text(encoding="utf-8")
        self.assertNotIn(".color-dot", css)
        self.assertRegex(css, r"span\.color-peek__names \{[^}]*-webkit-line-clamp: 2;")

    def test_actions_sit_side_by_side_and_headers_stay_visible(self):
        css = APP_CSS.read_text(encoding="utf-8")
        self.assertIn(".vehicle-model-row-actions { display: flex; align-items: center; justify-content: flex-end;", css)
        self.assertNotRegex(css, r"\.vehicle-model-row-actions \{[^}]*flex-direction: column")
        self.assertRegex(css, r"\.master-model-table thead th \{\s*position: sticky;")
        self.assertRegex(css, r"\.vehicle-brand-group\[open\] > \.vehicle-brand-group__header \{\s*position: sticky;")
        self.assertIn('grid-template-areas: "name name status" "year power price" "color color stock" "reward reward actions";', css)
