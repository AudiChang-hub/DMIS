"""T-299（使用者 2026-11-23 選定）：營運總表「需要處理」分四類，一眼看出是誰的事。

① 收錢、對帳 ② 付錢、退錢 ③ 訂單卡住 ④ 車與進貨。類別內排序不變（紅色優先，同色依金額與件數）；
沒事的類別收成一行「✓ <類別>：目前沒有」（檢查了哪些項目放在 title 與讀螢幕文字），四類全空時整張卡仍是一行。
寬版左欄①②、右欄③④，窄版單欄①→④；DOM 順序＝閱讀順序。每一項的數字、連結都不變。
"""
import copy
import re
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from sales.models import Store
from sales.services import operations_cockpit

EXPECTED_GROUPS = {
    "collect": {"reconciliation_installment", "reconciliation_platform", "unconfirmed", "unsettled_cash",
                "unsettled_card", "unsettled_installment", "unsettled_platform", "dealer_due"},
    "pay": {"refund", "overpaid", "payouts"},
    "stuck": {"stuck"},
    "stock": {"aged", "shortage", "campaigns"},
}
ALL_FLAGS = {"dashboard": True, "operations": True, "profit": True, "reconciliation": True,
             "dealer_payouts": True, "incentives": True,
             "links": {key: True for key in (
                 "order_list", "inventory_list", "reconciliation_list", "dealer_payout_list", "report_center",
                 "dealer_volume_bonus_list", "incentive_rule_list", "operations_report_export",
                 "inventory_shortage", "operations_dealer_credit")}}


class AttentionGroupTests(TestCase):
    def setUp(self):
        cache.clear()
        Store.objects.create(name="總店", code="MAIN")
        self.root = get_user_model().objects.create_superuser("admin", password="Local-t299-groups-417!")
        self.client.force_login(self.root)
        self.base = operations_cockpit.build("month", timezone.localdate())

    def data(self, **changes):
        """空資料上改出指定的待處理事項；changes 是 money／flow／stock／payouts 的欄位。"""
        data = copy.deepcopy(self.base)
        for section, values in changes.items():
            data[section].update(values)
        return data

    def busy(self):
        return self.data(money={"unconfirmed": 3, "refund": 2, "overpaid": 1},
                         flow={"stuck": 4}, stock={"aged": 1, "oldest": 120, "shortage": ["測試車型", "另一款", "第三款"]})

    def page(self, data):
        with patch.object(operations_cockpit, "load", return_value=data):
            response = self.client.get(reverse("operations_report"))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        start = html.index('aria-labelledby="ops-attention-title"')
        return response.context["cockpit"], html[start:html.index("</section>", start)]

    def test_every_item_lands_in_its_group(self):
        items = operations_cockpit._attention_items(self.base, ALL_FLAGS)
        found = {}
        for item in items:
            found.setdefault(item["group"], set()).add(item["key"])
        self.assertEqual(found, EXPECTED_GROUPS)
        groups = operations_cockpit._attention_groups(items)
        self.assertEqual([group["key"] for group in groups], ["collect", "pay", "stuck", "stock"])
        self.assertEqual([group["label"] for group in groups], ["收錢、對帳", "付錢、退錢", "訂單卡住", "車與進貨"])

    def test_unknown_item_must_be_assigned_first(self):
        with self.assertRaises(KeyError):
            operations_cockpit._attention_group("something_new")

    def test_order_within_group_and_numbers_unchanged(self):
        cockpit, html = self.page(self.busy())
        groups = {group["key"]: group for group in cockpit["attention_groups"]}
        # 類別內：紅色優先，同色依件數（取消待退款 2 張在溢收待退 1 張前；庫齡紅色在缺貨 3 款前）。
        self.assertEqual([item["key"] for item in groups["pay"]["items"]], ["refund", "overpaid"])
        self.assertEqual([item["key"] for item in groups["stock"]["items"]], ["aged", "shortage"])
        # 四類合起來就是原本整張卡的項目，同一批 dict（數字、連結不變）。
        grouped = [item for group in cockpit["attention_groups"] for item in group["items"]]
        self.assertCountEqual([item["key"] for item in grouped], [item["key"] for item in cockpit["attention"]])
        for item in cockpit["attention"]:
            li = re.search(rf'<li [^>]*data-attention-key="{item["key"]}">(.*?)</li>', html, re.S).group(1)
            self.assertIn(f"<b>{item['value']}</b> {item['unit']}", li)
            self.assertIn(f'href="{item["url"]}"'.replace("&", "&amp;"), li)
        self.assertIn('data-attention-key="unconfirmed"', html)
        self.assertNotIn('class="ops-clear"', html)
        self.assertNotIn("目前沒有：", html)

    def test_dom_order_and_columns(self):
        _cockpit, html = self.page(self.busy())
        columns = re.findall(r'<div class="ops-attention__col">(.*?)\n        </div>', html, re.S)
        keys = [re.findall(r'id="ops-group-(\w+)"', column) for column in columns]
        self.assertEqual(keys, [["collect", "pay"], ["stuck", "stock"]])
        titles = [html.index(f">{label}</h3>") for label in ("收錢、對帳", "付錢、退錢", "訂單卡住", "車與進貨")]
        self.assertEqual(titles, sorted(titles))

    def test_clear_group_collapses_to_one_line(self):
        cockpit, html = self.page(self.data(money={"unconfirmed": 3}))
        self.assertEqual([item["key"] for item in cockpit["attention"]], ["unconfirmed"])
        self.assertIn('id="ops-group-collect"', html)
        for key, label in (("pay", "付錢、退錢"), ("stuck", "訂單卡住"), ("stock", "車與進貨")):
            group = next(group for group in cockpit["attention_groups"] if group["key"] == key)
            self.assertFalse(group["items"])
            names = "、".join(group["clear"])
            self.assertIn(f'<p class="ops-group ops-group__none" title="已檢查：{names}">'
                          f'<span class="ops-attention__ok" aria-hidden="true">✓</span>'
                          f'<span><strong>{label}</strong>：目前沒有</span>'
                          f'<span class="ops-visually-hidden">（已檢查：{names}）</span></p>', html)
            self.assertNotIn(f'id="ops-group-{key}"', html)
        self.assertIn("已檢查：流程卡關訂單", html)
        self.assertIn("取消待退款、溢收待退、車行傭金／獎金未給付", html)
        # 空的類別仍在自己的欄位：左欄收錢＋付錢、右欄訂單卡住＋車與進貨。
        columns = re.findall(r'<div class="ops-attention__col">(.*?)\n        </div>', html, re.S)
        self.assertEqual(len(columns), 2)
        self.assertIn("付錢、退錢", columns[0])
        self.assertIn("訂單卡住", columns[1])
        self.assertIn("車與進貨", columns[1])

    def test_all_clear_is_still_one_line(self):
        cockpit, html = self.page(self.data())
        self.assertEqual(cockpit["attention"], [])
        self.assertNotIn("ops-attention__groups", html)
        self.assertNotIn("ops-group", html)
        self.assertIn('<p class="ops-attention__none">', html)
        self.assertIn("已收款待確認", html)

    def test_groups_without_permission_are_left_out(self):
        flags = {**ALL_FLAGS, "dashboard": False, "incentives": False}
        groups = operations_cockpit._attention_groups(operations_cockpit._attention_items(self.base, flags))
        self.assertEqual([group["key"] for group in groups], ["collect", "pay"])
        self.assertEqual(operations_cockpit._attention_columns(groups), [groups])


class AttentionGroupStylesTests(SimpleTestCase):
    def setUp(self):
        self.css = (Path(settings.BASE_DIR) / "static" / "css" / "operations.css").read_text(encoding="utf-8")

    def test_two_columns_only_on_wide_screens(self):
        # 寬版兩欄；窄版預設單欄（.ops-attention__groups 沒有其他 grid-template-columns）。
        self.assertRegex(self.css, r"@media \(min-width: 860\.02px\) \{\n  \.ops-attention__groups \{\n"
                                   r"    grid-template-columns: repeat\(2, minmax\(0, 1fr\)\);")
        self.assertEqual(self.css.count(".ops-attention__groups {"), 1)
        # 類別內單欄清單：不再有整張卡兩欄的 .ops-todo grid；也不用 order 重排。
        self.assertNotRegex(self.css, r"\.ops-todo \{\n    display: grid;")
        self.assertNotRegex(self.css, r"\border:\s*-?\d")
