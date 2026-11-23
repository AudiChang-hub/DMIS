"""T-293（使用者 2026-11-23「照你的建議全部做」）：營運總表「錢」卡片只改呈現，數字一律不變。

- 數字不變：同一組資料，卡片上看得到的每個金額、張數、帳齡、撥款待入帳、車行未付，改版前後完全相同。
  這組測試在改版前的模板上先跑過（全過）才動模板；值為 0 的拆列改顯示「—」，比對時當 0。
"""
import re
from decimal import Decimal
from html.parser import HTMLParser

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


class MoneyCardNumbersUnchangedTests(MoneyCardTestBase):
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

    def test_amount_set_is_unchanged(self):
        money, _, parser = self.card()
        text = squash(" ".join(parser.text))
        self.assertEqual(sorted(set(AMOUNT.findall(text))), [
            "$0", "$131,277", "$162,400", "$164,750", "$188,160", "$2,350", "$260,460", "$270,310",
            "$422,460", "$61,277", "$70,000", "$72,300", "$720,787", "$79,850", "$82,150",
        ])
        expected = {money["unsettled_amount"], money["before_delivery_amount"], money["awaiting_payout_amount"],
                    money["outstanding_amount"], money["unsettled_payout_amount"], money["dealer_credit_total"]}
        self.assertTrue({f"${int(value):,}" for value in expected} <= set(AMOUNT.findall(text)))

    def test_three_card_counts_and_split_rows_are_unchanged(self):
        money, _, parser = self.card()
        self.assertEqual([count(value) for value in parser.cards], [3, 3, 1])
        self.assertEqual(parser.cards and [money["unsettled_count"], money["before_delivery_count"],
                                           money["awaiting_payout_count"]], [3, 3, 1])
        rows = [[(row["span"].strip(), count(row["b"]), amount(row["small"]), AMOUNT.findall(row["parts"]))
                 for row in split] for split in parser.splits]
        self.assertEqual(rows, [
            [("現金", 2, "$162,400", []), ("刷卡", 0, None, []), ("分期", 0, None, []), ("平台", 1, "$2,350", [])],
            [("現金", 1, "$82,150", []), ("刷卡", 0, None, []), ("分期", 1, "$270,310", ["$188,160", "$82,150"]),
             ("平台", 1, "$70,000", ["$70,000", "$0"])],
            [("現金", 0, None, []), ("刷卡", 0, None, []), ("分期", 1, "$72,300", []), ("平台", 0, None, [])],
        ])
        for split, bucket in zip(rows, ("unsettled", "before_delivery", "awaiting_payout")):
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
