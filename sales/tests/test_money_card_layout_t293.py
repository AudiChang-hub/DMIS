"""T-293（使用者 2026-11-23「照你的建議全部做」）：營運總表「錢」卡片只改呈現，數字一律不變。

- 新結構：三張小卡＋色帶、0 張「—」、預估寫「約」、分段長條、算式收進「怎麼算的」、撥款待入帳小表；T-301 起車行未付不再加「已含在交車後未結清」標籤；
  CSS 用容器查詢，卡片變寬也成立。
- 數字不變：同一組資料，卡片上看得到的每個金額、張數、帳齡、撥款待入帳、車行未付，改版前後完全相同。
  這組測試在改版前的模板上先跑過（全過）才動模板；值為 0 的拆列改顯示「—」，比對時當 0。
"""
import re
from decimal import Decimal
from html.parser import HTMLParser
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase
from django.utils import timezone

from sales.models import OrderOperationsProfile, PaymentRecord, SalesOrder
from sales.services.dealer_commission import apply_order_dealer_commission
from sales.services.operations_sync import sync_order_operations
from sales.tests.test_money_card_t278 import MoneyCardTestBase

AMOUNT = re.compile(r"\$[\d,]+")
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


class MoneyCardParser(HTMLParser):
    """收「錢」卡片（aria-labelledby=ops-money-title 的 section）裡看得到的文字，不含屬性。"""

    def __init__(self):
        super().__init__()
        self.stack = []            # [(tag, classes)]
        self.depth = None          # 進入錢卡片時的 stack 深度
        self.text = []
        self.cards = []            # .ops-fig 裡 <strong> 的文字
        self.splits = []           # 每個 ul.ops-split：[[span, b, small, parts], ...]
        self.legend = []           # ul.ops-legend 每一列文字
        self.recon = []            # .ops-recon 裡的文字
        self._li = None
        self._legend_li = None

    def inside(self, cls):
        return any(cls in classes for _, classes in self.stack[self.depth or 0:])

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = (attrs.get("class") or "").split()
        if self.depth is None and tag == "section" and attrs.get("aria-labelledby") == "ops-money-title":
            self.depth = len(self.stack)
        if tag in VOID:
            return
        self.stack.append((tag, classes))
        if self.depth is None:
            return
        if tag == "ul" and "ops-split" in classes:
            self.splits.append([])
        elif tag == "li" and self.inside("ops-split") and self._li is None:
            self._li = {"span": "", "b": "", "small": "", "parts": ""}
            self.splits[-1].append(self._li)
        elif tag == "li" and self.inside("ops-legend"):
            self._legend_li = []

    def handle_endtag(self, tag):
        if tag in VOID or not self.stack:
            return
        while self.stack:
            closed, _ = self.stack.pop()
            if closed == tag:
                break
        if self.depth is not None and len(self.stack) <= self.depth:
            self.depth = -1        # 錢卡片結束，後面的區塊不收
        if tag == "li" and self._li is not None and not self.inside("ops-split__parts") and self.inside("ops-split"):
            if not any(t == "li" for t, _ in self.stack[self.depth:]):
                self._li = None
        if tag == "li" and self._legend_li is not None:
            self.legend.append(squash(" ".join(self._legend_li)))
            self._legend_li = None

    def handle_data(self, data):
        if self.depth is None or self.depth < 0:
            return
        self.text.append(data)
        tags = [t for t, _ in self.stack[self.depth:]]
        if tags and tags[-1] == "strong" and self.inside("ops-fig"):
            self.cards.append(data.strip())
        if self._li is not None:
            if self.inside("ops-split__parts"):
                self._li["parts"] += data
            elif "small" in tags:
                self._li["small"] += data
            elif "b" in tags:
                self._li["b"] += data
            elif "span" in tags and not self._li["span"]:
                self._li["span"] += data
        if self._legend_li is not None:
            self._legend_li.append(data)
        if self.inside("ops-recon"):
            self.recon.append(data)


def count(value):
    value = value.strip()
    return 0 if value in ("—", "") else int(value)


def amount(value):
    found = AMOUNT.search(value)
    return found.group() if found else None


def squash(value):
    return re.sub(r"\s+", " ", value).strip()


class MoneyCardScenario(MoneyCardTestBase):
    """同一組資料涵蓋三格、四種付款方式、撥款＋客人、平台預估、帳齡、撥款待入帳、車行未付。"""

    maxDiff = None

    def scenario(self):
        # 交車後未結清：平台單（撥款預估 61,277）、本店現金單付了一部分、車行現金單掛帳。
        unsettled = self.order("completed", timezone.now(), source_type="platform", source=self.platform,
                               vehicle_price=Decimal("0"))
        OrderOperationsProfile.objects.filter(order=unsettled).update(actual_disbursement=Decimal("61277"))
        partial = self.order("completed", timezone.now(), source_type="store", source=self.staff)
        PaymentRecord.objects.create(order=partial, expected_amount=500, received_amount=100, confirmed=True)
        dealer = self.make_order(source=self.dealer, cash_receivable_v2=True)
        apply_order_dealer_commission(dealer)
        sync_order_operations(dealer.pk)
        SalesOrder.all_objects.filter(pk=dealer.pk).update(status="completed", delivered_at=timezone.now())
        # 未交車・尾款待收：本店現金單、平台單（預估 70,000）、分期單（撥款 188,160＋客人尾款）。
        self.order("delivery_pending", source_type="store", source=self.staff)
        before_platform = self.order("delivery_pending", source_type="platform", source=self.platform,
                                     vehicle_price=Decimal("0"))
        self.settle(before_platform)
        OrderOperationsProfile.objects.filter(order=before_platform).update(actual_disbursement=Decimal("70000"))
        self.lender_pending(self.order("delivery_pending", source_type="store", source=self.staff,
                                       payment_type="installment"), amount=188160)
        # 已交車待撥款：分期單客人已收清，只差撥款 72,300。
        self.settle(self.lender_pending(
            self.order("completed", timezone.now(), source_type="store", source=self.staff, payment_type="installment"),
            amount=72300))

    def card(self):
        self.scenario()
        response, cockpit = self.cockpit()
        parser = MoneyCardParser()
        parser.feed(response.content.decode())
        self.assertGreater(len(parser.text), 0, "找不到錢卡片")
        return cockpit["money"], cockpit, parser


class MoneyCardNumbersUnchangedTests(MoneyCardScenario):
    """改版前後同一組資料的金額、張數完全相同（先在舊模板上跑過）。"""

    def test_amount_set_is_unchanged(self):
        money, _, parser = self.card()
        text = squash(" ".join(parser.text))
        self.assertEqual(sorted(set(AMOUNT.findall(text))), [
            "$0", "$131,277", "$133,627", "$162,400", "$164,750", "$188,160", "$2,350", "$244,550", "$260,460",
            "$270,310", "$342,610", "$422,460", "$61,277", "$63,627", "$70,000", "$72,300", "$720,787", "$79,850",
            "$82,150",
        ])  # T-296 新增四個：三列合計 $244,550／$342,610／$133,627、怎麼算的 $63,627
        expected = {money["unsettled_amount"], money["before_delivery_amount"], money["awaiting_payout_amount"],
                    money["outstanding_amount"], money["unsettled_payout_amount"], money["dealer_credit_total"]}
        self.assertTrue({f"${int(value):,}" for value in expected} <= set(AMOUNT.findall(text)))

    def test_three_card_counts_and_split_rows_are_unchanged(self):
        money, _, parser = self.card()
        self.assertEqual([count(value) for value in parser.cards], [3, 1, 3])
        self.assertEqual(parser.cards and [money["before_delivery_count"], money["awaiting_payout_count"],
                                           money["unsettled_count"]], [3, 1, 3])
        rows = [[(row["span"].strip(), count(row["b"]), amount(row["small"]), AMOUNT.findall(row["parts"]))
                 for row in split] for split in parser.splits]
        self.assertEqual(rows, [
            [("現金", 1, "$82,150", []), ("刷卡", 0, None, []), ("分期", 1, "$270,310", ["$188,160", "$82,150"]),
             ("平台", 1, "$70,000", ["$70,000", "$0"])],
            [("現金", 0, None, []), ("刷卡", 0, None, []), ("分期", 1, "$72,300", []), ("平台", 0, None, [])],
            [("現金", 2, "$162,400", []), ("刷卡", 0, None, []), ("分期", 0, None, []), ("平台", 1, "$2,350", [])],
        ])
        for split, bucket in zip(rows, ("before_delivery", "awaiting_payout", "unsettled")):
            self.assertEqual([(label, number, value) for label, number, value, _ in split],
                             [(row["label"], row["count"], f"${int(row['amount']):,}" if row["amount"] else None)
                              for row in money["split"][bucket]])

    def test_total_aging_recon_and_dealer_credit_are_unchanged(self):
        money, cockpit, parser = self.card()
        text = squash(" ".join(parser.text))
        total = re.search(r"待收合計（(\d+) 張）\D*?(\$[\d,]+)", text)
        self.assertEqual(total.groups(), ("7", "$720,787"))
        self.assertEqual((money["outstanding_count"], money["outstanding_amount"]), (7, Decimal("720787")))
        self.assertEqual(len(parser.legend), len(money["aging"]))
        legend = []
        for row, bucket in zip(parser.legend, money["aging"]):
            self.assertTrue(row.startswith(bucket["label"]), row)
            rest = row[len(bucket["label"]):]
            legend.append((bucket["label"], int(re.search(r"\d+", rest).group()), amount(rest)))
        self.assertEqual(legend, [("0–7 天", 3, "$164,750"), ("8–30 天", 0, None), ("30 天以上", 0, None)])
        recon = squash(" ".join(parser.recon))
        found = [re.search(re.escape(row["label"]) + r"[^$\d]*?(\d+)[^$]*?(\$[\d,]+)", recon).groups()
                 for row in cockpit["reconciliation"]["channels"]]
        self.assertEqual(found, [(str(row["pending"]), f"${int(row['expected']):,}")
                                 for row in cockpit["reconciliation"]["channels"]])
        self.assertEqual(found, [("2", "$260,460"), ("2", "$131,277")])
        self.assertEqual(re.search(r"(\d+) 家共 (\d+) 張", text).groups(), ("1", "1"))
        self.assertEqual(re.search(r"車行未付[^$]*?(\$[\d,]+)", text).group(1),
                         f"${int(money['dealer_credit_total']):,}")


class MoneyCardLayoutTests(MoneyCardScenario):
    """新結構：三張小卡＋色帶、四列固定、0 張「—」、預估寫「約」、分段長條、算式收進「怎麼算的」、撥款待入帳小表、車行未付標籤。"""

    def section(self):
        self.scenario()
        response, cockpit = self.cockpit()
        html = response.content.decode()
        start = html.index('aria-labelledby="ops-money-title"')
        return cockpit["money"], cockpit, html[start:html.index("</section>", start)]

    def test_three_cards_with_colour_bands_in_order(self):
        _money, _cockpit, html = self.section()
        cards = re.findall(r'<div class="ops-fig ops-money__card ops-money__card--(\w+)"><h3 class="ops-money__label">'
                           r'<span>([^<]+)</span></h3>', html)
        self.assertEqual(cards, [("before", "未交車・尾款待收"), ("awaiting", "已交車待撥款"),
                                 ("unsettled", "交車後未結清")])
        self.assertIn('<span class="ops-money__amount">約 $422,460</span>', html)     # 未交車含平台預估
        self.assertIn('<span class="ops-money__amount">$164,750</span>', html)

    def test_four_rows_fixed_zero_rows_show_dash(self):
        _money, _cockpit, html = self.section()
        lists = html.split('<ul class="ops-split"')[1:]
        self.assertEqual(len(lists), 3)
        for chunk in lists:
            chunk = chunk.split("</ul>")[0]
            positions = [chunk.index(f"<span>{label}</span>") for label in ("現金", "刷卡", "分期", "平台")]
            self.assertEqual(positions, sorted(positions))
            self.assertNotIn("<b>0</b>", chunk)
        self.assertIn('<li class="is-zero" title="已交車待撥款（現金）"><span>現金</span><b aria-hidden="true">—</b>'
                      '<span class="ops-visually-hidden">0 張</span></li>', html)
        self.assertEqual(html.count('<b aria-hidden="true">—</b>'), 6)
        # 預估金額加「約」；撥款＋客人附註保留。
        self.assertIn("<small>約 $70,000</small>", html)
        self.assertIn('<small class="ops-split__parts" data-split-parts><span class="ops-split__part">撥款 約 $70,000</span>'
                      '<span class="ops-split__part">＋客人 $0</span></small>', html)
        self.assertNotIn("預估 $", html.split('<div class="ops-money__total">')[0])

    def test_total_has_stacked_bar_and_formula_folded_into_details(self):
        money, _cockpit, html = self.section()
        self.assertIn('<strong class="ops-money__total-amount">約 $720,787</strong>', html)
        segments = re.findall(r'<span class="ops-money__seg ops-money__seg--(\w+)[^"]*" style="flex-grow: (\d+)"></span>',
                              html)
        self.assertEqual(segments, [("before", "422460"), ("awaiting", "72300"), ("unsettled", "164750"),
                                    ("unsettled", "61277")])
        self.assertEqual(sum(int(value) for _key, value in segments), int(money["outstanding_amount"]))
        details = re.findall(r'<details class="ops-money__how"><summary>怎麼算的 <span class="ops-money__i" '
                             r'aria-hidden="true">ⓘ</span></summary>(.*?)</details>', html, re.S)
        self.assertEqual(len(details), 2)
        self.assertIn("data-outstanding-formula", details[0])
        self.assertIn("「約」：含平台撥款預估", details[0])
        self.assertEqual(html.count("data-outstanding-formula"), 1)
        self.assertEqual(html.count("data-recon-terms"), details[1].count("data-recon-terms"))
        self.assertIn('data-recon-terms="installment"', details[1])

    def test_reconciliation_is_a_small_table(self):
        _money, _cockpit, html = self.section()
        self.assertIn(">待收合計依付款方式拆開</p>", html)
        self.assertNotIn("已含在上面三格", html)
        self.assertIn('<thead><tr><th scope="col"><span class="ops-visually-hidden">付款方式</span></th>'
                      '<th scope="col">張數</th><th scope="col">金額</th></tr></thead>', html)
        table = html.split('id="ops-recon-title"')[1].split("</table>")[0]
        self.assertEqual(re.findall(r'<th scope="row">([^<]+)</th>', table),
                         ["現金未結清", "刷卡未結清", "分期待撥款", "平台待撥款"])
        self.assertRegex(html, r'<th scope="row">現金未結清</th>\s*<td>.*?>3 張</a></td>\s*<td>\$244,550</td>')
        self.assertRegex(html, r'<th scope="row">分期待撥款</th>\s*<td>.*?>2 張</a></td>\s*<td>\$342,610<small')
        self.assertRegex(html, r'<th scope="row">平台待撥款</th>\s*<td>.*?>2 張</a></td>\s*<td>約 \$133,627<small')
        self.assertRegex(html, r'對帳頁的分期撥款待入帳 <a [^>]*>2 張</a> · \$260,460')
        self.assertRegex(html, r'對帳頁的平台撥款待入帳 <a [^>]*>2 張</a> · 約 \$131,277')

    def test_dealer_credit_note_has_no_tag(self):
        _money, _cockpit, html = self.section()
        self.assertIn('車行未付<small class="ops-facts__note">'
                      '<span class="ops-facts__note-count">1 家共 1 張</span></small>', html)
        self.assertNotIn("已含在交車後未結清", html)

    def test_blocks_keep_order(self):
        _money, _cockpit, html = self.section()
        order = [html.index(marker) for marker in ('class="ops-money__cards"', 'class="ops-money__total"',
                                                   'id="ops-recon-title"', 'class="ops-money__aging"', "車行未付")]
        self.assertEqual(order, sorted(order))
        self.assertEqual(len(re.findall(r'class="ops-bar__seg ops-bar__seg--[123]', html)), 3)


class MoneyCardStylesTests(SimpleTestCase):
    """CSS：容器查詢（不是視窗寬度）、色帶顏色、帳齡由淺到深、ⓘ 可聚焦、尊重減少動態。"""

    def setUp(self):
        css = (Path(settings.BASE_DIR) / "static" / "css" / "operations.css").read_text(encoding="utf-8")
        self.css = css.replace("\r\n", "\n")

    def test_container_query_and_bands(self):
        self.assertIn("container: ops-money / inline-size;", self.css)
        self.assertIn("@container ops-money (min-width: 22rem)", self.css)
        self.assertIn("--money-unsettled: var(--amber-strong);", self.css)
        self.assertIn("--money-before: var(--muted);", self.css)
        self.assertIn("--money-awaiting: var(--blue);", self.css)
        self.assertIn("border-top: 3px solid var(--money-band", self.css)

    def test_aging_light_to_dark_and_details_accessible(self):
        mixes = re.findall(r"\.ops-money \.ops-bar__seg--(\d),\n(?:\.ops-money \.ops-bar__seg\.is-late,\n)?"
                           r"\.ops-money \.ops-legend__swatch\.ops-bar__seg--\d \{ background: color-mix\(in srgb, "
                           r"var\(--ink\) (\d+)%, var\(--surface\)\); \}", self.css)
        self.assertEqual(mixes, [("1", "50"), ("2", "70"), ("3", "90")])
        self.assertIn(".ops-money__how > summary:focus-visible", self.css)
        self.assertIn("@media (prefers-reduced-motion: no-preference) {\n  .ops-money__how[open]", self.css)
