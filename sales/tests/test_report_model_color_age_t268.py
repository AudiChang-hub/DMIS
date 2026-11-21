"""T-268 大數據分析「車型 顏色 vs 年齡分布」（方案 B）：引擎新增「車型＋顏色」維度，一張堆疊圖，列＝車型·顏色、系列＝年齡層。

涵蓋口徑（排除狀態、期間）、T-228 合併（同車型各年式、同一廣告色）、年齡層依年齡排序與固定配色（數字不變）、
設計器用三個下拉選單組出同樣結果、起點範本、migration 0222 建立／還原。全部為合成資料。
"""
import copy
from datetime import date
from importlib import import_module
from io import StringIO
from types import SimpleNamespace

from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import connection
from django.db.models import Count
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from sales.models import ReportDefinition, ReportRevision, SalesOrder, VehicleColor, VehicleModel
from sales.reporting.demographics import AGE_GROUP_COLORS, AGE_GROUP_ORDER, demographic_query
from sales.reporting.engine import EXCLUDED_STATUSES, MAX_GROUPS, base_query, card_result, drill_query, validate_config
from sales.reporting.forms import designer_dimension_choices
from sales.reporting.source_templates import PRESET_TEMPLATES, SOURCE_TEMPLATES, age_sex_analysis, model_color_age_analysis
from sales.reporting.starters import STARTERS, starter_config
from sales.tests.test_report_designer_ux_t164 import browser_payload

TODAY = timezone.localdate()
MIGRATION = import_module("sales.migrations.0222_t268_model_color_age_report")


def born(age):
    return date(TODAY.year - age, 6, 1)


def order(model, color, birth=None, *, month=10, owner_type="local", id_number=""):
    return SalesOrder.objects.create(
        source_type="store", order_date=date(2026, month, 2), registration_date=date(2026, month, 3),
        registration_completed_at=timezone.now(), owner_type=owner_type, owner_name="合成車主", owner_id_number=id_number,
        owner_birth_date=birth, vehicle_model=model, color=color, vehicle_price=10000, actual_balance=10000,
        calculated_balance=10000, payment_type="cash", status="completed")


def chart(result):
    """{列標籤: {年齡層: 台數}}，方便比對。"""
    return {row["label"]: {segment["label"]: int(segment["value"]) for segment in row["segments"]} for row in result["rows"]}


def preset_result(filters=None):
    config = validate_config(model_color_age_analysis())
    return card_result(config, config["cards"][0], filters or {})


class ModelColorAgeT268Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser("admin", "admin@example.invalid", "Test-Only-123")
        make = VehicleModel.objects.create
        # New NEX 125 兩個年式：合併成同一個車型。
        cls.nex_2026 = make(brand="SUZUKI", name="New NEX 125", model_number="UT125XDA", model_year=2026, energy_type="gas")
        cls.nex_2022 = make(brand="SUZUKI", name="New NEX 125", model_number="UT125XZ", model_year=2022, energy_type="gas")
        # Saluto 125 盧卡綠依年式代號拆成兩個車色（T-223），報表合併成「盧卡綠」。
        cls.saluto = make(brand="SUZUKI", name="Saluto 125", model_number="UC125", model_year=2022, energy_type="gas")
        cls.fun = make(brand="eReady", name="Fun", model_number="EV060L", model_year=2024, energy_type="electric")
        color = VehicleColor.objects.create
        nex_white = color(vehicle_model=cls.nex_2026, name="白", code="RB5")
        nex_old_white = color(vehicle_model=cls.nex_2022, name="白", code="W13")
        nex_blue = color(vehicle_model=cls.nex_2026, name="藍", code="YSF")
        luca_d = color(vehicle_model=cls.saluto, name="盧卡綠（UC125D）", code="T94", active=False)
        luca_d2 = color(vehicle_model=cls.saluto, name="盧卡綠（UC125D2）", code="N34", active=False)
        fun_white = color(vehicle_model=cls.fun, name="白", code="EW1")
        # New NEX 125：白（兩個年式）25 歲 ×2、45 歲 ×1；藍 18 歲 ×1、生日未填 ×1。
        order(cls.nex_2026, nex_white, born(25))
        order(cls.nex_2022, nex_old_white, born(25))
        order(cls.nex_2026, nex_white, born(45))
        order(cls.nex_2026, nex_blue, born(18))
        order(cls.nex_2026, nex_blue, None)
        # Saluto 125：盧卡綠兩個色碼合併，35 歲 ×2、65 歲 ×1；公司 ×1。
        order(cls.saluto, luca_d, born(35))
        order(cls.saluto, luca_d2, born(35))
        order(cls.saluto, luca_d2, born(65))
        order(cls.saluto, luca_d, None, owner_type="company", id_number="83739807")
        # Fun 的白與 New NEX 125 的白不可合併：生日異常 ×1、55 歲 ×1（8 月，用來測期間）。
        order(cls.fun, fun_white, date(TODAY.year + 1, 1, 1))
        order(cls.fun, fun_white, born(55), month=8)
        # 草稿、取消、待退款、異常結案都不算；建立時給 draft 會被訂單自動推進，所以建好再直接改狀態。
        for status in EXCLUDED_STATUSES:
            SalesOrder.objects.filter(pk=order(cls.nex_2026, nex_white, born(25)).pk).update(status=status)
        assert set(SalesOrder.objects.filter(status__in=EXCLUDED_STATUSES).values_list("status", flat=True)) == set(EXCLUDED_STATUSES)

    def setUp(self):
        self.client.force_login(self.admin)

    def test_preset_is_one_stacked_chart_family_color_by_age_without_truncation(self):
        config = validate_config(PRESET_TEMPLATES["model-color-age"]())
        self.assertNotIn("model-color-age", SOURCE_TEMPLATES)  # 原報表重建 13 頁的範圍不變
        self.assertEqual((config["title"], config["navigation_group"]), ("車型 顏色 vs 年齡分布", "analysis"))
        (card,) = config["cards"]
        self.assertEqual((card["chart"], card["dimension"], card["series"]), ("stacked", "family_color", "age_group"))
        self.assertNotIn("per_model", card)
        # T-245：顯示全部列與年齡層，不合併成「其他」。
        self.assertEqual((card["limit"], card.get("series_limit", 200), card.get("series_other", False)), (MAX_GROUPS, 200, False))

    def test_rows_are_model_color_series_are_age_groups_with_merges(self):
        result = preset_result()
        # 依品牌（不分大小寫）、車型、顏色排列；同車型兩年式的白合成一列、色碼都列出（T-231）；盧卡綠兩個代號合併。
        self.assertEqual([row["label"] for row in result["rows"]],
                         ["Fun · 白 EW1", "New NEX 125 · 白 RB5／W13", "New NEX 125 · 藍 YSF", "Saluto 125 · 盧卡綠 N34／T94"])
        self.assertEqual(chart(result), {
            "Fun · 白 EW1": {"50-59歲": 1, "生日異常": 1},
            "New NEX 125 · 白 RB5／W13": {"20-29歲": 2, "40-49歲": 1},
            "New NEX 125 · 藍 YSF": {"20歲以下": 1, "生日未填": 1},
            "Saluto 125 · 盧卡綠 N34／T94": {"30-39歲": 2, "60歲以上": 1, "公司或其他": 1},
        })
        self.assertFalse(result["truncated"] or result["series_truncated"])

    def test_excluded_statuses_and_period_filter(self):
        self.assertEqual(preset_result()["count"], 11)  # 4 種排除狀態的訂單都不算
        self.assertEqual(chart(preset_result({"months": ["2026-08"]})), {"Fun · 白 EW1": {"50-59歲": 1}})
        october = chart(preset_result({"start": date(2026, 10, 1), "end": date(2026, 10, 31)}))
        self.assertEqual(october["Fun · 白 EW1"], {"生日異常": 1})

    def test_age_groups_sorted_by_age_with_fixed_colors(self):
        legend = preset_result()["series_legend"]
        self.assertEqual([item["label"] for item in legend],
                         ["20歲以下", "20-29歲", "30-39歲", "40-49歲", "50-59歲", "60歲以上", "生日未填", "生日異常", "公司或其他"])
        self.assertEqual({item["label"]: item["color"] for item in legend}, AGE_GROUP_COLORS)
        # 只看 8 月（只有 50-59 歲）時，同一年齡層仍是同一個顏色。
        self.assertEqual(preset_result({"months": ["2026-08"]})["series_legend"],
                         [{"label": "50-59歲", "color": AGE_GROUP_COLORS["50-59歲"]}])
        self.assertEqual(len(set(AGE_GROUP_COLORS.values())), len(AGE_GROUP_ORDER))

    def test_age_sex_report_rows_reordered_numbers_unchanged(self):
        """已發布的「性別 X 年齡」：列順序改成依年齡，各列台數與性別分段和直接分組計數完全相同。"""
        config = validate_config(age_sex_analysis())
        config["fixed_filters"].pop("legacy_energy")  # 合成資料有油車，只拿掉能源條件以涵蓋全部年齡層
        config["fixed_filters"].pop("model_prefix")
        result = card_result(config, config["cards"][0], {})
        labels = [row["label"] for row in result["rows"]]
        self.assertEqual(labels, sorted(labels, key=AGE_GROUP_ORDER.index))
        self.assertLess(labels.index("20-29歲"), labels.index("30-39歲"))
        expected = {}
        rows = (demographic_query(demographic_query(base_query(config, {}), "age_group", "age"), "sex", "sex_group")
                .values("age", "sex_group").annotate(total=Count("pk")))
        for row in rows:
            expected.setdefault(row["age"], {})[row["sex_group"]] = row["total"]
        self.assertEqual(chart(result), expected)
        # 20 歲以下依原報表條件排除（age_scope），其餘年齡層都在。
        self.assertNotIn("20歲以下", labels)

    def test_age_table_and_key_desc_follow_age_order(self):
        card = {"title": "年齡表", "chart": "table", "dimension": "age_group", "series": "sex", "metric": "count",
                "formula": "", "limit": 200, "sort": "key"}
        config = validate_config({**model_color_age_analysis(), "cards": [card]})
        ages = list(dict.fromkeys(row["dimension_cells"][0] for row in card_result(config, card, {})["rows"]))
        self.assertEqual(ages, [label for label in AGE_GROUP_ORDER if label in ages])
        bar = {**card, "chart": "bar", "sort": "key_desc"}
        bar.pop("series")
        labels = [row["label"] for row in card_result({**config, "cards": [bar]}, bar, {})["rows"]]
        self.assertEqual(labels, [label for label in reversed(AGE_GROUP_ORDER) if label in labels])

    def test_drill_and_csv_use_the_merged_row(self):
        config = validate_config(model_color_age_analysis())
        result = card_result(config, config["cards"][0], {})
        row = next(row for row in result["rows"] if row["label"].startswith("New NEX 125 · 白"))
        self.assertEqual(drill_query(config, config["cards"][0], {}, row["key"]).count(), 3)
        segment = next(segment for segment in row["segments"] if segment["label"] == "20-29歲")
        self.assertEqual(drill_query(config, config["cards"][0], {}, segment["key"]).count(), 2)
        report = ReportDefinition.objects.create(draft=config, published=copy.deepcopy(config), version=1)
        csv = self.client.get(reverse("report_export", args=[report.pk, 0])).content.decode("utf-8-sig")
        self.assertIn("Saluto 125 · 盧卡綠 N34／T94", csv)

    def test_reader_page_renders_one_full_width_chart(self):
        config = model_color_age_analysis()
        report = ReportDefinition.objects.create(draft=config, published=copy.deepcopy(config), version=1)
        response = self.client.get(reverse("report_display", args=[report.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["card"]["title"] for item in response.context["results"]], ["車型顏色 × 年齡層"])
        self.assertContains(response, "Saluto 125 · 盧卡綠 N34／T94")
        # 車型篩選只看 Saluto 125：列只剩該車型。
        only = self.client.get(reverse("report_display", args=[report.pk]), {"model": [str(self.saluto.pk)]})
        self.assertEqual([row["label"] for row in only.context["results"][0]["rows"]], ["Saluto 125 · 盧卡綠 N34／T94"])

    def publish_from_designer(self, start, changes=None):
        url = reverse("report_create") + f"?start={start}"
        payload = browser_payload(self.client.get(url).content.decode(), "publish")
        for key, value in (changes or {}).items():
            payload[key] = [value]
        before = set(ReportDefinition.objects.values_list("pk", flat=True))
        response = self.client.post(reverse("report_create"), payload)
        self.assertEqual(response.status_code, 302, response.content[:800])
        return ReportDefinition.objects.exclude(pk__in=before).get()

    def test_designer_builds_the_same_report_with_three_dropdowns(self):
        """設計管理從空白報表：圖表類型＝堆疊、依什麼分＝車型＋顏色、再細分＝年齡層。"""
        options = dict(choice for _, group in designer_dimension_choices() for choice in group)
        self.assertTrue(options["family_color"].startswith("車型＋顏色"))
        report = self.publish_from_designer("blank", {
            "title": "我自己組的", "cards-0-chart": "stacked", "cards-0-dimension": "family_color", "cards-0-series": "age_group"})
        mine = report.published
        self.assertEqual(chart(card_result(mine, mine["cards"][0], {})), chart(preset_result()))
        self.assertEqual(chart(card_result(mine, mine["cards"][0], {"months": ["2026-10"]})), chart(preset_result({"months": ["2026-10"]})))

    def test_designer_starter_saves_the_preset_unchanged(self):
        self.assertEqual(starter_config("model_color_age"), model_color_age_analysis())
        self.assertIn("年齡層", STARTERS["model_color_age"]["question"])
        report = self.publish_from_designer("model_color_age")
        self.assertEqual(report.published, model_color_age_analysis())

    def test_designer_hint_for_plain_color(self):
        response = self.client.get(reverse("report_create") + "?start=blank")
        self.assertContains(response, "data-family-color-hint")
        self.assertContains(response, "?start=model_color_age")

    def test_migration_creates_published_report_once_and_reverse_removes_only_it(self):
        self.assertEqual(MIGRATION.CONFIG, model_color_age_analysis())
        other = ReportDefinition.objects.create(draft=starter_config("trend"), published=starter_config("trend"), version=3)
        editor = SimpleNamespace(connection=connection)
        MIGRATION.create_report(apps, editor)
        MIGRATION.create_report(apps, editor)  # 可重跑，不重複建立
        report = ReportDefinition.objects.get(published__title="車型 顏色 vs 年齡分布")
        self.assertEqual((report.version, report.draft, report.published), (1, MIGRATION.CONFIG, MIGRATION.CONFIG))
        self.assertEqual(list(report.revisions.values_list("version", "action")), [(1, "publish")])
        self.assertEqual(self.client.get(reverse("report_display", args=[report.pk])).status_code, 200)
        MIGRATION.remove_report(apps, editor)
        self.assertFalse(ReportDefinition.objects.filter(pk=report.pk).exists())
        other.refresh_from_db()
        self.assertEqual((other.version, other.published), (3, starter_config("trend")))

    def test_migration_skips_database_without_admin(self):
        """新建或測試資料庫（沒有啟用中的 admin）不建立，避免其他測試多出一份報表。"""
        self.assertFalse(ReportDefinition.objects.filter(published__title="車型 顏色 vs 年齡分布").exists())
        get_user_model().objects.filter(pk=self.admin.pk).update(is_active=False)
        MIGRATION.create_report(apps, SimpleNamespace(connection=connection))
        self.assertFalse(ReportDefinition.objects.filter(published__title="車型 顏色 vs 年齡分布").exists())

    def test_migration_reverse_keeps_edited_or_manual_report(self):
        editor = SimpleNamespace(connection=connection)
        MIGRATION.create_report(apps, editor)
        report = ReportDefinition.objects.get(published__title="車型 顏色 vs 年齡分布")
        edited = {**MIGRATION.CONFIG, "description": "管理者改過"}
        ReportDefinition.objects.filter(pk=report.pk).update(draft=edited, published=edited, version=2)
        ReportRevision.objects.create(report=report, version=2, action="publish", config=edited, actor=self.admin)
        MIGRATION.remove_report(apps, editor)
        self.assertTrue(ReportDefinition.objects.filter(pk=report.pk).exists())
        # 已有同名報表時不另外建立。
        MIGRATION.create_report(apps, editor)
        self.assertEqual(ReportDefinition.objects.filter(published__title="車型 顏色 vs 年齡分布").count(), 1)

    def test_create_source_report_draft_command(self):
        call_command("create_source_report_draft", "--page", "model-color-age", stdout=StringIO())
        report = ReportDefinition.objects.get(draft__title="車型 顏色 vs 年齡分布")
        self.assertIsNone(report.published)
        self.assertEqual(report.draft, model_color_age_analysis())
