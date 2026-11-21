"""T-274 堆疊圖的系列是車色時，每段顏色對應車色名稱；同一張圖不重複、圖例一致；其他報表顏色不變。全部為合成資料。"""
import colorsys
from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from sales.models import ReportDefinition, SalesOrder, VehicleColor, VehicleModel
from sales.reporting.engine import PALETTE, card_result, validate_config
from sales.reporting.source_templates import model_color_age_analysis
from sales.reporting.tree_filter import expand_cards

TODAY = timezone.localdate()
COLORS = ("紅", "藍", "金", "白", "珍珠白", "消光黑", "特殊色")


def hue_family(color):
    """hex → (色相角度, 飽和度, 亮度)。"""
    assert color.startswith("#") and len(color) == 7, color
    r, g, b = (int(color[index:index + 2], 16) / 255 for index in (1, 3, 5))
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    return h * 360, s, l


class CarSeriesColorT274Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser("admin", "admin@example.invalid", "Test-Only-123")
        cls.model = VehicleModel.objects.create(brand="eReady", name="示範車", model_number="DEMO1", energy_type="electric")
        for index, name in enumerate(COLORS):
            color = VehicleColor.objects.create(vehicle_model=cls.model, name=name, code=f"C{index}")
            for age in (25, 35):
                SalesOrder.objects.create(
                    source_type="store", order_date=date(2026, 10, 2), registration_date=date(2026, 10, 3),
                    registration_completed_at=timezone.now(), owner_type="local", owner_name="合成車主", owner_id_number="",
                    owner_birth_date=date(TODAY.year - age, 6, 1), vehicle_model=cls.model, color=color,
                    vehicle_price=10000, actual_balance=10000, calculated_balance=10000, payment_type="cash", status="completed")
        # PM 要在設計器存的設定：每個車型一張堆疊圖，列＝年齡層、系列＝車色。
        cls.config = validate_config({**model_color_age_analysis(), "cards": [
            {"title": "年齡層 × 車色", "chart": "stacked", "dimension": "age_group", "series": "color", "metric": "count",
             "formula": "", "limit": 200, "sort": "key", "series_sort": "value", "per_model": True}]})

    def result(self, config=None):
        config, _ = expand_cards(config or self.config, {})
        return card_result(config, config["cards"][0], {})

    def legend(self):
        return {item["label"].split(" ")[0]: item["color"] for item in self.result()["series_legend"]}

    def test_red_is_red_and_blue_differs_from_gold(self):
        """重現：原本依序輪流配色（紅→綠、白→黃），同圖的藍與金都成粉紅。"""
        legend = self.legend()
        hue, saturation, _ = hue_family(legend["紅"])
        self.assertTrue(hue <= 15 or hue >= 345, hue)
        self.assertGreater(saturation, .5)
        self.assertNotEqual(legend["藍"], legend["金"])
        self.assertTrue(200 <= hue_family(legend["藍"])[0] <= 235)
        self.assertTrue(35 <= hue_family(legend["金"])[0] <= 52)

    def test_white_black_shades_and_unmatched_are_distinct(self):
        legend = self.legend()
        self.assertEqual(len(set(legend.values())), len(COLORS))  # 同一張圖不重複
        white, pearl, black = (hue_family(legend[name]) for name in ("白", "珍珠白", "消光黑"))
        self.assertGreater(white[2], .85)
        self.assertGreater(pearl[2], .8)  # 白與珍珠白同色系，以深淺區分
        self.assertLess(black[2], .25)
        self.assertNotIn(legend["特殊色"], set(legend.values()) - {legend["特殊色"]})

    def test_legend_matches_segments_and_light_colors_are_outlined(self):
        result = self.result()
        legend = {item["label"]: item for item in result["series_legend"]}
        for row in result["rows"]:
            for segment in row["segments"]:
                self.assertEqual(segment["color"], legend[segment["label"]]["color"])
                self.assertEqual(segment["outline"], legend[segment["label"]]["outline"])
        self.assertTrue(legend["白 C3"]["outline"])
        self.assertFalse(legend["紅 C0"]["outline"])

    def test_reader_page_marks_series_and_outline(self):
        report = ReportDefinition.objects.create(draft=self.config, published=self.config, version=1)
        self.client.force_login(self.admin)
        response = self.client.get(reverse("report_display", args=[report.pk]))
        self.assertContains(response, 'data-series="color"')
        self.assertContains(response, "data-outline")

    def test_non_stacked_chart_does_not_mark_series(self):
        """長條圖存了「再細分＝車色」也不輸出 data-series，前端照舊用版型配色。"""
        bar = {**self.config["cards"][0], "chart": "bar"}
        config = validate_config({**self.config, "cards": [bar]})
        report = ReportDefinition.objects.create(draft=config, published=config, version=1)
        self.client.force_login(self.admin)
        response = self.client.get(reverse("report_display", args=[report.pk]))
        self.assertContains(response, 'data-chart="bar"')
        self.assertNotContains(response, "data-series=")

    def test_other_reports_keep_their_colors(self):
        """依車色分組的長條圖（車型 X 顏色）與系列是性別的堆疊圖，顏色和以前一樣依序輪流。"""
        bar = {"title": "顏色", "chart": "bar", "dimension": "color", "metric": "count", "formula": "", "limit": 100, "sort": "value"}
        result = card_result(validate_config({**self.config, "cards": [bar]}), bar, {})
        self.assertEqual([row["color"] for row in result["rows"]], [PALETTE[index % len(PALETTE)] for index in range(len(COLORS))])
        stacked = {**bar, "chart": "stacked", "series": "sex", "series_sort": "value"}
        result = card_result(validate_config({**self.config, "cards": [stacked]}), stacked, {})
        self.assertEqual(result["series_legend"], [{"label": "公司或其他", "color": "var(--chart-other)"}])
        self.assertNotIn("outline", result["rows"][0]["segments"][0])
