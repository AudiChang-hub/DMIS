"""T-192：圖表 CSV 在指標已是「訂單台數」時，不再另外補一欄「訂單台數」；其他指標照舊補台數欄。"""
import csv
import io
from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from sales.models import ReportDefinition, SalesOrder, SalesSource, VehicleColor, VehicleModel
from sales.reporting.source_templates import dealer_sales


class ChartCsvCountColumnTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser("admin", "admin@example.invalid", "Test-Only-123")
        model = VehicleModel.objects.create(brand="eReady", name="Fun", model_number="EV060L", energy_type="electric")
        dealer = SalesSource.objects.create(name="甲車行", source_type="dealer")
        for index in range(2):
            color = VehicleColor.objects.create(vehicle_model=model, name=f"白{index}")
            SalesOrder.objects.create(source_type="dealer", source=dealer, order_date=date(2026, 10, 2),
                registration_date=date(2026, 10, 3 + index), registration_completed_at=timezone.now(),
                owner_type="company", owner_name="合成車主", owner_id_number="83739807",
                vehicle_model=model, color=color, vehicle_price=10000, actual_balance=10000,
                calculated_balance=10000, payment_type="cash", status="completed")
        cls.reports = {}
        for chart in ("stacked", "bar"):
            for metric in ("count", "sale_total"):
                config = {**dealer_sales(), "audience": "team", "reader_layout": "standard"}
                card = {**config["cards"][0], "chart": chart, "metric": metric}
                if chart == "bar":
                    card.update(series="", series_limit=200, series_other=False, series_sort="value")
                config["cards"] = [card]
                cls.reports[chart, metric] = ReportDefinition.objects.create(draft=config, published=config, version=1)

    def setUp(self):
        self.client.force_login(self.admin)

    def export(self, chart, metric, **params):
        response = self.client.get(reverse("report_export", args=[self.reports[chart, metric].pk, 0]), params)
        self.assertEqual(response.status_code, 200)
        return list(csv.reader(io.StringIO(response.content.decode("utf-8-sig"))))

    def table(self, rows, header_start):
        start = next(index for index, row in enumerate(rows) if row and row[0] == header_start)
        return rows[start], [row for row in rows[start + 1:] if row and row[0] != "提醒" and row[0] != "細分系列"]

    def test_count_metric_with_notes_has_one_count_column(self):
        # 重現：正式站 r9 的表頭是「車行,月份,訂單台數,訂單台數」。
        header, data = self.table(self.export("stacked", "count"), "車行")
        self.assertEqual(header, ["車行", "月份", "訂單台數"])
        self.assertTrue(data)
        self.assertTrue(all(len(row) == 3 for row in data), data)
        header, data = self.table(self.export("bar", "count"), "車行")
        self.assertEqual(header, ["車行", "訂單台數"])
        self.assertTrue(all(len(row) == 2 for row in data), data)

    def test_count_metric_plain_csv_is_unchanged(self):
        rows = self.export("stacked", "count", format="csv")
        self.assertEqual(rows[0], ["車行", "月份", "訂單台數"])
        self.assertTrue(all(len(row) == 3 for row in rows[1:]))
        self.assertEqual(self.export("bar", "count", format="csv")[0], ["車行", "訂單台數"])

    def test_other_metrics_keep_the_count_column(self):
        for params in ({}, {"format": "csv"}):
            with self.subTest(notes=not params):
                header, data = self.table(self.export("stacked", "sale_total", **params), "車行")
                self.assertEqual(header, ["車行", "月份", "訂單車價合計", "訂單台數"])
                self.assertTrue(all(len(row) == 4 for row in data), data)
                header, data = self.table(self.export("bar", "sale_total", **params), "車行")
                self.assertEqual(header, ["車行", "訂單車價合計", "訂單台數"])
                self.assertTrue(all(len(row) == 3 for row in data), data)
