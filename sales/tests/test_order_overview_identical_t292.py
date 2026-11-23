"""T-292 訂單總覽每張單完全一樣：同樣的區塊、同樣的欄、同樣的順序、區塊內同樣的欄位列與明細表。

T-289 固定了兩欄，但汰舊、車行獎勵、取消與退款三個區塊、其他費用與補助項目兩張表、
車行獎勵內的「傭金給」「活動獎勵」等列仍依資料有無才輸出（正式站兩張單因此排列不同）。
"""
import re
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from sales.models import AccessoryLine, OtherFeeLine, PaymentRecord, SalesOrder, SubsidyItem
from sales.services.dealer_commission import apply_order_dealer_commission
from sales.services.order_overview import build_order_overview
from sales.tests import test_order_lifecycle as lifecycle


class OrderOverviewIdenticalTests(TestCase):
    setUp = lifecycle.OrderLifecycleTests.setUp
    make_order = lifecycle.OrderLifecycleTests.make_order

    def cash_store_order(self):
        """現金、本店、無汰舊、無加購、無收支、無費用、無補助、未取消。"""
        order, _vehicle = self.make_order(deposit=Decimal("0"))
        order.payment_records.all().delete()
        order.accessories.all().delete()
        return SalesOrder.objects.get(pk=order.pk)

    def installment_dealer_order(self):
        """分期、車行單（有傭金）、汰舊、加購、其他費用、補助、收支、取消申請。"""
        self.model.base_dealer_commission = Decimal("1500")
        self.model.save(update_fields=["base_dealer_commission"])
        order, _vehicle = self.make_order(dealer=True)
        SalesOrder.objects.filter(pk=order.pk).update(
            payment_type=SalesOrder.PaymentType.INSTALLMENT, installment_company="示範分期", installment_periods=24,
            installment_amount=Decimal("60000"), installment_monthly=Decimal("2800"),
            is_trade_in_subsidy=True, trade_in_plate="ABC-123", note="長備註" * 40,
            cancellation_requested_at=timezone.now(), cancellation_reason="客人改買他牌",
        )
        AccessoryLine.objects.create(order=order, name="後架", quantity=1, amount=Decimal("1200"))
        OtherFeeLine.objects.create(order=order, name="代辦費", amount=Decimal("500"))
        SubsidyItem.objects.create(order=order, category=SubsidyItem.Category.OTHER, item_name="汰舊換新", expected_amount=Decimal("1000"))
        PaymentRecord.objects.create(order=order, item_name="訂金", expected_amount=Decimal("5000"), received_amount=Decimal("5000"))
        order = SalesOrder.objects.get(pk=order.pk)
        apply_order_dealer_commission(order)
        return SalesOrder.objects.get(pk=order.pk)

    @staticmethod
    def shape(overview):
        """排列骨架：區塊（跳轉順序）、各欄區塊、每區塊的欄位列位置、明細表。"""
        return {
            "sections": [section["key"] for section in overview["sections"]],
            "columns": [[section["key"] for section in column] for column in overview["columns"]],
            "rows": {section["key"]: len(section["rows"]) for section in overview["sections"]},
            "labels": {section["key"]: [row["label"] for row in section["rows"]] for section in overview["sections"]},
            "tables": [table["key"] for table in overview["tables"]],
        }

    def test_cash_and_installment_dealer_orders_have_identical_layout(self):
        cash = build_order_overview(self.cash_store_order())
        rich = build_order_overview(self.installment_dealer_order())
        self.assertEqual(self.shape(cash), self.shape(rich))
        self.assertEqual(self.shape(cash)["sections"], [
            "order", "owner", "vehicle", "registration", "dealer_reward", "price", "installment",
            "trade_in", "delivery", "cancellation", "note",
        ])
        self.assertEqual(self.shape(cash)["columns"], [
            ["order", "owner", "vehicle", "trade_in", "delivery", "cancellation", "note"],
            ["registration", "dealer_reward", "price", "installment"],
        ])
        self.assertEqual(self.shape(cash)["tables"], ["accessories", "fees", "subsidies", "payments"])

    def test_missing_scenario_blocks_show_dash_and_stay_out_of_copy_all(self):
        cash = build_order_overview(self.cash_store_order())
        for key in ("dealer_reward", "trade_in", "cancellation"):
            section = next(section for section in cash["sections"] if section["key"] == key)
            self.assertTrue(section["rows"], key)
            self.assertTrue(all(row["value"] == "—" and row["copy"] == "" for row in section["rows"]), key)
        for table in cash["tables"]:
            self.assertEqual(table["rows"], [], table["key"])
            self.assertTrue(table["empty"], table["key"])
        for title in ("車行獎勵", "汰舊", "取消與退款", "其他費用", "補助項目"):
            self.assertNotIn(f"【{title}】", cash["plain_text"])

    def test_rendered_pages_are_identical_in_blocks_columns_rows_and_jumps(self):
        self.client.force_login(self.user)

        def skeleton(order):
            page = self.client.get(reverse("order_overview", args=[order.pk]) + "?fragment=1").content.decode()
            grid = page.split('class="order-overview__grid"', 1)[1].split('class="order-overview__tables"', 1)[0]
            columns = [re.findall(r'<section class="order-overview__card" id="overview-(\w+)"', chunk)
                       for chunk in grid.split('data-overview-column="')[1:]]
            sections = re.findall(r'<section class="order-overview__card[^"]*" id="overview-(\w+)"', page)
            rows = [len(re.findall(r"<dt>", card)) for card in grid.split("<section ")[1:]]
            jumps = re.findall(r'<a href="#overview-(\w+)" data-overview-jump>', page)
            return columns, sections, rows, jumps

        cash = skeleton(self.cash_store_order())
        rich = skeleton(self.installment_dealer_order())
        self.assertEqual(cash, rich)
        _columns, sections, _rows, jumps = cash
        self.assertEqual(jumps, [key for key in jumps if key in sections])
        self.assertEqual(sorted(jumps), sorted(sections))
