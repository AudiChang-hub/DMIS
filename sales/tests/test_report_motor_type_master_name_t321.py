"""T-321：系統開的新單，車種分類在型號（原廠代碼）比不到時，改用車型主檔名稱比對。

正式站實例：GOGORO EZZY 主檔型號 GE3GS，規則寫的是車型名稱 EZZY；新單被歸到「其他」。
"""
from django.db.models import F
from django.test import TestCase

from sales.models import (LegacyImportBatch, LegacyImportRow, LegacySalesSnapshot, SalesOrder, VehicleModel)
from sales.reporting.classification import (classification_expression, impact, initial_snapshot, inventory,
                                            published_snapshot, unclassified)
from sales.reporting.engine import card_result, drill_query
from sales.tests import test_reporting as fixtures


class MotorTypeMasterNameFallbackTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        fixtures.ReportingTests.setUpTestData.__func__(cls)

    def setUp(self):
        self.card = {**self.config["cards"][0], "dimension": "legacy_motor_type"}

    def use_master(self, name, model_number, energy_type="electric"):
        VehicleModel.objects.all().update(name=name, model_number=model_number, energy_type=energy_type)

    def rows(self):
        return [(row["label"], row["count"]) for row in card_result(self.config, self.card, {})["rows"]]

    def test_new_order_with_factory_code_uses_master_name(self):
        # 修正前：GE3GS 比不到任何規則 → 其他。
        self.use_master("EZZY", "GE3GS", "light_electric")
        self.assertEqual(self.rows(), [("綠牌電車", 3)])
        result = card_result(self.config, self.card, {})
        self.assertEqual(drill_query(self.config, self.card, {}, result["rows"][0]["key"]).count(), 3)

    def test_other_categories_unchanged(self):
        # 型號本身比得到的，結果不變，名稱不影響（型號優先）。
        for name, number, energy, label in (
            ("New NEX 125", "UT125XDA", "gas", "速克達"),
            ("SUI 125", "UQ125DA", "gas", "速克達"),
            ("V-STROM 250SX", "DS250", "gas", "擋車"),
            ("Gixxer SF 250", "GSX250F", "gas", "擋車"),
            ("Fun", "EV060L", "electric", "白牌電車"),
            ("70 Belt", "EV070V", "electric", "白牌電車"),
            ("Momi", "M02", "micro_electric", "微型電車"),
            ("小偉士", "JDL-B1", "micro_electric", "微型電車"),
            ("EZZY", "EV060L", "electric", "白牌電車"),  # 型號比得到，就不看名稱
        ):
            with self.subTest(number=number, name=name):
                self.use_master(name, number, energy)
                self.assertEqual(self.rows(), [(label, 3)])

    def test_master_name_fallback_each_category(self):
        for name, number, label in (
            ("EZ1", "EM3H1", "綠牌電車"),
            ("BOBE", "EM6D9", "微型電車"),
            ("S2 ABS", "GSB7BTJ", "白牌電車"),
            ("DS250", "", "擋車"),
            ("UQ125", "XX1", "速克達"),
            ("Gogoro Delight", "GM7R2", "其他"),  # 名稱也比不到，維持其他
        ):
            with self.subTest(name=name, number=number):
                self.use_master(name, number)
                self.assertEqual(self.rows(), [(label, 3)])

    def test_imported_order_keeps_imported_model_text(self):
        # 匯入單沿用匯入的型號文字比對（與舊報表對照），不改用主檔名稱。
        self.use_master("EZZY", "GE3GS", "light_electric")
        batch = LegacyImportBatch.objects.create(import_type="operations", source_file="t321.xlsx",
            original_filename="t321.xlsx", file_sha256="c" * 64, file_size=0, uploaded_by="tester")
        row = LegacyImportRow.objects.create(batch=batch, sheet_name="銷售", source_row=1,
            fingerprint="d" * 64, action="create", mapped_data={"model_number": "XYZ"})
        order = SalesOrder.objects.first()
        LegacySalesSnapshot.objects.create(order=order, import_row=row)
        self.assertEqual(sorted(self.rows()), [("其他", 1), ("綠牌電車", 2)])
        self.assertEqual(list(drill_query(self.config, self.card, {}, "v:其他").values_list("pk", flat=True)), [order.pk])

    def test_classification_settings_agree_with_report(self):
        self.use_master("EZZY", "GE3GS", "light_electric")
        snapshot = published_snapshot()[0]
        self.assertFalse(unclassified(snapshot).filter(report_source_model="GE3GS").exists())
        # 影響預覽：拿掉 EZZY 規則，這 3 張會從綠牌電車變其他。
        after = {**snapshot, "rules": [r for r in snapshot["rules"] if r["text"] != "EZZY"]}
        result = impact(snapshot, after)
        self.assertEqual(result["total"], 3)
        self.assertEqual({(r["before"], r["after"]) for r in result["rows"]}, {("綠牌電車", "其他")})

    def test_vehicle_model_queryset_still_classifies_by_model_number(self):
        # 盤點頁以車型主檔分組（stock_count），仍只看型號，不受本修正影響。
        self.use_master("EZZY", "GE3GS", "light_electric")
        categories = set(VehicleModel.objects.annotate(report_source_model=F("model_number"))
                         .annotate(c=classification_expression(initial_snapshot())).values_list("c", flat=True))
        self.assertEqual(categories, {"其他"})
        self.assertEqual(inventory().count(), 3)
