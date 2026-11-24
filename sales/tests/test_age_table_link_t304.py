"""T-304：營運總表「貨」卡庫齡長條和車型表連動（使用者 2026-11-24 選 A＋措辭甲）。

1. 每個庫齡區間列出有哪些車型、各幾台（加總＝區間台數），表格沒列的車型也列出並標「表外」；預設顯示最久那段。
2. 表格裡有這段車的列標出來，車名下寫「已放 區間 N 台」。
3. 車型小卡與那行字都連到車輛庫存，只列「該車型＋該庫齡區間」那幾台（model／age_min／age_max），台數與小卡一致。
4. 庫齡寫「實際已放多久」，可銷天數寫「預估」、數字前加「約」（沒有庫存的 0 天不加）。
"""
import re
from datetime import timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from sales.models import VehicleColor, VehicleModel
from sales.services import operations_cockpit
from sales.tests.test_operations_cockpit import make_vehicle

ROOT = Path(settings.BASE_DIR)


class AgeBucketModelsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser("t304-admin", password="test-only")
        cls.models = {}
        for index in range(8):
            model = VehicleModel.objects.create(brand="測試", name=f"T304 機種{index}", energy_type="gas")
            cls.models[index] = (model, VehicleColor.objects.create(vehicle_model=model, name="白"))

    def setUp(self):
        cache.clear()
        today = timezone.localdate()
        self.number = 0

        def add(index, *ages, status="available"):
            model, color = self.models[index]
            for age in ages:
                self.number += 1
                make_vehicle(model, color, status, self.number, received_on=today - timedelta(days=age))

        add(0, 0, 29, 30, 59, 60, 89, 90, 200)   # 區間邊界各一台
        add(0, 45, status="reserved")
        for index in range(1, 7):                  # 機種1～6 在庫比較多，排進表格前 6 列
            add(index, *([5] * (10 - index)))
        add(7, 120)                                # 機種7 只有 1 台，排不進表格

    def stock(self):
        return operations_cockpit.build("month", timezone.localdate())["stock"]

    def test_bucket_models_sum_to_bucket_count_and_include_outside_models(self):
        stock = self.stock()
        for bucket in stock["aging"]:
            with self.subTest(bucket=bucket["label"]):
                self.assertEqual(sum(model["count"] for model in bucket["models"]), bucket["count"])
        oldest = stock["aging"][3]
        self.assertEqual([(m["name"], m["count"], m["in_table"]) for m in oldest["models"]],
                         [("T304 機種0", 2, True), ("T304 機種7", 1, False)])
        self.assertEqual(oldest["outside"], 1)
        self.assertEqual([(m["name"], m["count"]) for m in stock["aging"][1]["models"]], [("T304 機種0", 3)])
        self.assertEqual(stock["age_default"], 4)
        self.assertNotIn("T304 機種7", [row["name"] for row in stock["models"]])

    def test_links_carry_model_and_age_range(self):
        stock = self.stock()
        model0 = self.models[0][0].pk
        expected = [{"age_min": ["0"], "age_max": ["29"]}, {"age_min": ["30"], "age_max": ["59"]},
                    {"age_min": ["60"], "age_max": ["89"]}, {"age_min": ["90"]}]
        for bucket, params in zip(stock["aging"], expected):
            entry = next(model for model in bucket["models"] if model["name"] == "T304 機種0")
            query = parse_qs(urlsplit(entry["url"]).query)
            with self.subTest(bucket=bucket["label"]):
                self.assertEqual(urlsplit(entry["url"]).path, reverse("inventory_list"))
                self.assertEqual(query, {"model": [str(model0)], "sort": ["received_asc"], **params})
        row = next(row for row in stock["models"] if row["name"] == "T304 機種0")
        self.assertEqual([(hit["key"], hit["count"], hit["alert"]) for hit in row["age_hits"]],
                         [(1, 2, False), (2, 3, False), (3, 2, False), (4, 2, True)])

    def test_inventory_list_count_matches_every_card_link(self):
        """點小卡到庫存列表，列出的台數＝小卡上的台數（含 0／29／30／59／60／89／90 天邊界）。"""
        self.client.force_login(self.admin)
        for bucket in self.stock()["aging"]:
            for model in bucket["models"]:
                with self.subTest(bucket=bucket["label"], model=model["name"]):
                    response = self.client.get(model["url"])
                    self.assertEqual(response.context["page_obj"].paginator.count, model["count"])

    def test_inventory_list_age_range_boundaries(self):
        self.client.force_login(self.admin)
        model0 = self.models[0][0]
        url = reverse("inventory_list")
        cases = {(0, 29): 2, (30, 59): 3, (60, 89): 2, (30, 30): 1, (89, 90): 2, (0, 0): 1}
        for (low, high), count in cases.items():
            with self.subTest(low=low, high=high):
                response = self.client.get(url, {"model": model0.pk, "age_min": low, "age_max": high})
                self.assertEqual(response.context["page_obj"].paginator.count, count)
        response = self.client.get(url, {"model": model0.pk, "age_min": 90})
        self.assertEqual(response.context["page_obj"].paginator.count, 2)
        # 上限比下限小就不套上限；沒有車型參數就是全部車型
        response = self.client.get(url, {"model": model0.pk, "age_min": 60, "age_max": 30})
        self.assertEqual(response.context["page_obj"].paginator.count, 4)
        response = self.client.get(url, {"age_min": 90})
        self.assertEqual(response.context["page_obj"].paginator.count, 3)
        response = self.client.get(url, {"model": "x", "age_max": "y"})
        self.assertEqual(response.context["page_obj"].paginator.count, 9 + sum(10 - index for index in range(1, 7)) + 1)

    def test_inventory_list_ignores_bad_age_max_and_model(self):
        """QA 退件：age_max 超出日期範圍、或 age_max／model 是上標數字「²」（isdigit 為真但 int 失敗）時不可 500。

        行為：age_max 只收 ASCII 數字且不超過 36500 天（100 年），否則當作沒帶上限；model 只收 ASCII 數字，否則當作沒帶車型。
        """
        self.client.force_login(self.admin)
        model0 = self.models[0][0]
        url = reverse("inventory_list")
        everything = 9 + sum(10 - index for index in range(1, 7)) + 1
        cases = {
            "age_max 一百萬天": ({"model": model0.pk, "age_min": 30, "age_max": "1000000"}, 7),   # 等於只帶 age_min=30
            "age_max 上標數字": ({"model": model0.pk, "age_min": 30, "age_max": "²"}, 7),
            "model 上標數字": ({"model": "²", "age_min": 90}, 3),                                  # 等於只帶 age_min=90
            "只帶過大的 age_max": ({"age_max": "1000000"}, everything),
        }
        for name, (params, count) in cases.items():
            with self.subTest(name):
                response = self.client.get(url, params)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context["page_obj"].paginator.count, count)
        response = self.client.get(url, {"model": model0.pk, "age_min": 30, "age_max": "1000000"})
        self.assertNotContains(response, 'name="age_max"')
        # 上限 36500 天本身照常套用（剛好在範圍內，不會被忽略）
        response = self.client.get(url, {"model": model0.pk, "age_min": 0, "age_max": "36500"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<input type="hidden" name="age_max" value="36500">')
        self.assertEqual(response.context["page_obj"].paginator.count, 9)
        response = self.client.get(url, {"model": model0.pk, "age_min": 0, "age_max": "36501"})
        self.assertNotContains(response, 'name="age_max"')

    def test_inventory_list_says_what_is_filtered(self):
        self.client.force_login(self.admin)
        model0 = self.models[0][0]
        html = self.client.get(reverse("inventory_list"), {"model": model0.pk, "age_min": 30, "age_max": 59}).content.decode()
        self.assertIn("只列 T304 機種0・庫齡 30–59 天（", html)
        self.assertIn('<input type="hidden" name="age_max" value="59">', html)
        self.assertIn(f'<input type="hidden" name="model" value="{model0.pk}">', html)
        html = self.client.get(reverse("inventory_list"), {"model": model0.pk, "age_min": 0, "age_max": 29}).content.decode()
        self.assertIn("只列 T304 機種0・庫齡 未滿 30 天（", html)
        html = self.client.get(reverse("inventory_list"), {"model": model0.pk, "age_min": 90}).content.decode()
        self.assertIn("只列 T304 機種0・庫齡 90 天以上（", html)
        html = self.client.get(reverse("inventory_list"), {"age_min": 90}).content.decode()
        self.assertIn("只列庫齡 90 天以上（", html)   # T-275 原本的寫法照舊

    def card(self):
        self.client.force_login(self.admin)
        html = self.client.get(reverse("operations_report")).content.decode()
        start = html.index('aria-labelledby="ops-stock-title"')
        return html[start:html.index("</section>", start)]

    def test_card_lists_models_per_bucket_and_marks_table_rows(self):
        html = self.card()
        self.assertIn('<div class="ops-age-models" data-ops-age-models aria-live="polite">', html)
        groups = re.findall(r'<div class="ops-age-models__group[^"]*" id="ops-age-models-(\d)" data-ops-age-group="\d"( hidden)?>', html)
        self.assertEqual(groups, [("1", " hidden"), ("2", " hidden"), ("3", " hidden"), ("4", "")])
        self.assertIn('<span>已放 90 天以上：2 款 3 台</span><small>含表格沒列的 1 款</small>', html)
        self.assertRegex(html, r'<a href="/data/inventory/\?model=\d+&amp;age_min=90&amp;sort=received_asc">T304 機種7 <b>1 台</b><small>表外</small></a>')
        self.assertIn('aria-describedby="ops-age-models-4"', html)
        self.assertRegex(html, r'<tr data-ops-age-row class="is-age-hit is-alert">\s*<th data-label="車型"><a [^>]*>T304 機種0</a>')
        self.assertRegex(html, r'<a class="ops-age-hit is-alert" href="[^"]*age_min=90[^"]*" data-ops-age-group="4">已放 90 天以上 2 台</a>')
        self.assertRegex(html, r'<a class="ops-age-hit" href="[^"]*age_max=59" data-ops-age-group="2" hidden>已放 30–59 天 3 台</a>')

    def test_cover_wording_marks_estimate(self):
        html = self.card()
        self.assertIn('<div class="ops-subhead ops-cover__head">預估可銷天數 <small>照近 90 天賣速推估，不是實際天數</small></div>', html)
        self.assertIn('<th>預估可銷天數<small class="ops-cover__th-note">推估值</small></th>', html)
        self.assertIn('data-label="預估可銷天數"', html)
        self.assertNotIn("90 天未售", html)

    def test_estimate_prefix_skips_zero_days(self):
        from sales.models import SalesOrder
        today = timezone.localdate()
        model, color = self.models[1]
        for offset in (1, 2, 3):
            SalesOrder.objects.create(
                owner_name="T304 合成", owner_phone="0912345678", owner_address="合成地址", owner_id_number="A123456789",
                vehicle_model=model, color=color, registration_date=today - timedelta(days=offset),
                established_on=today - timedelta(days=offset), status="completed", vehicle_price=80000,
                registration_completed_at=timezone.now())
        self.assertIn('<b class="ops-cover__value">約 270 天</b>', self.card())


class EmptyStockCardTests(TestCase):
    def test_no_stock_renders_no_model_panel(self):
        cache.clear()
        admin = get_user_model().objects.create_superuser("t304-empty", password="test-only")
        self.client.force_login(admin)
        html = self.client.get(reverse("operations_report")).content.decode()
        self.assertNotIn("data-ops-age-models", html)
        self.assertIsNone(operations_cockpit.build("month", timezone.localdate())["stock"]["age_default"])


class AgeTableLinkAssetTests(SimpleTestCase):
    def test_css_hides_inactive_groups_and_respects_reduced_motion(self):
        css = (ROOT / "static/css/operations.css").read_text(encoding="utf-8").replace("\r\n", "\n")
        self.assertIn(".ops-age-models__group[hidden],\n.ops-age-hit[hidden] {\n  display: none;", css)
        self.assertIn("@media (prefers-reduced-motion: reduce) {\n  .ops-age-models__list a {\n    transition: none;", css)
        self.assertIn(".ops-cover-table tr.is-age-hit.is-alert {\n  box-shadow: inset 3px 0 0 var(--red);", css)

    def test_js_switches_groups_rows_and_moves_focus_on_enter(self):
        js = (ROOT / "static/js/operations.js").read_text(encoding="utf-8")
        for snippet in ('card.querySelector("[data-ops-age-models]")', "showModels(seg ? key : null);",
                        'row.classList.toggle("is-age-hit", !!note);', 'event.key !== "Enter" && event.key !== " "',
                        "link.focus();", "leaveTimer = setTimeout(function () { hoverKey = null; activate(pinned); }, 300);",
                        "hoverTimer = setTimeout(function () { activate(hoverKey = key); }, 150);"):
            self.assertIn(snippet, js)
