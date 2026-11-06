"""打開畫面（GET）不寫入資料庫（使用者 2026-11-06 T-114 方案 B）。

守門：以 admin GET 每一條路由，期間不得出現 INSERT／UPDATE／DELETE（session 除外）。明列的例外只有兩種
「首次固定」型寫入：列印／簽署第一次固定訂購單公司資料、價格表分發補建該月名單。新增的 GET 寫入會在這裡失敗。
"""
import re
from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import URLPattern, URLResolver, get_resolver, reverse

from sales.models import OrderChange, OrderOperationsProfile, PaymentRecord, SalesOrder, Store, VehicleInventory
from sales.tests import test_payout_reconciliation_t96 as t96
from sales.tests.test_finance_ledger import FinanceLedgerTestBase

WRITE = re.compile(r'^\s*(?:INSERT INTO|UPDATE|DELETE FROM)\s+"?(\w+)"?', re.I)
ALLOWED = {
    # 第一次列印或簽署時固定當下的公司資料（BUSINESS_RULES：之後不隨公司資料變動）。
    "contract_print": {"sales_salesorder"},
    "privacy_consent_print": {"sales_salesorder"},
    "order_documents_print": {"sales_salesorder"},
    "order_sign": {"sales_salesorder"},
    # 打開還沒有名單的月份時補建一次（月底排程通常已先建好）。
    "price_list_distribution": {"sales_pricelistdistributionmonth", "sales_pricelistdistributionitem"},
}
SKIPPED_PREFIXES = ("admin/", "static/", "media/")


def _routes(patterns, prefix=""):
    for item in patterns:
        if isinstance(item, URLResolver):
            yield from _routes(item.url_patterns, prefix + str(item.pattern))
        elif isinstance(item, URLPattern):
            yield prefix + str(item.pattern), item.name


def _written_tables(queries):
    tables = set()
    for query in queries:
        match = WRITE.match(query["sql"])
        if match and match.group(1) != "django_session":
            tables.add(match.group(1))
    return tables


class GetRequestsReadOnlyTests(FinanceLedgerTestBase):
    platform_order = t96.PayoutReconciliationTests.platform_order
    installment_order = t96.PayoutReconciliationTests.installment_order

    def setUp(self):
        self.client.force_login(self.admin)
        store = Store.objects.create(name="本店", code="HQ")
        for n in range(3):
            VehicleInventory.objects.create(vehicle_model=self.model, color=self.color, engine_number=f"RO-{n}",
                                            ownership_store=store, location_store=store)
        self.cash = self.make_order(source_type="store", source=self.staff, deposit_amount=Decimal("2000"),
                                    cash_receivable_v2=True)
        self.cancelled = self.make_order(source_type="store", source=self.staff, deposit_amount=Decimal("2000"),
                                         cash_receivable_v2=True)
        self.cancelled.request_cancellation("測試人員", "")
        self.missing_balance = self.make_order(source_type="store", source=self.staff)
        PaymentRecord.objects.filter(order=self.missing_balance, system_key="balance").delete()
        self.orders = [self.cash, self.installment_order(), self.platform_order(), self.cancelled, self.missing_balance]

    def get(self, path):
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(path)
        return response, _written_tables(ctx.captured_queries)

    def test_every_get_route_is_read_only_except_first_time_snapshots(self):
        violations = []
        for route, name in _routes(get_resolver().url_patterns):
            if route.startswith(SKIPPED_PREFIXES) or re.search(r"<(uuid|str|path|slug)", route):
                continue
            params = re.findall(r"<int:(\w+)>", route)
            if not params:
                paths = ["/" + route]
            elif route.startswith("orders/<int:pk>") and params == ["pk"]:
                paths = ["/" + route.replace("<int:pk>", str(order.pk)) for order in self.orders]
            else:
                paths = []
                for n in (1, 2, 3):
                    path = "/" + route
                    for param in params:
                        path = path.replace(f"<int:{param}>", str(n))
                    paths.append(path)
            for path in paths:
                _response, tables = self.get(path)
                extra = tables - ALLOWED.get(name, set())
                if extra:
                    violations.append(f"{name} {path}: {sorted(extra)}")
        self.assertEqual(violations, [], "GET 不得寫入資料庫（例外須明列於 ALLOWED）")

    def test_order_pages_do_not_recompute_on_open(self):
        # 31D05F 的情況：已取消的單旗標過期，打開訂單頁與收支頁都不能改它。
        OrderOperationsProfile.objects.filter(order=self.cancelled).update(payment_confirmed=False)
        for order in (self.cancelled, self.missing_balance):
            for url in (reverse("order_detail", args=[order.pk]), reverse("order_operations", args=[order.pk])):
                response, tables = self.get(url)
                self.assertIn(response.status_code, (200, 302))
                self.assertEqual(tables, set(), url)
        self.assertFalse(OrderOperationsProfile.objects.get(order=self.cancelled).payment_confirmed)
        self.assertFalse(PaymentRecord.objects.filter(order=self.missing_balance, system_key="balance").exists())

    def test_resync_command_lists_then_applies_with_audit(self):
        OrderOperationsProfile.objects.filter(order=self.cancelled).update(payment_confirmed=False)
        out = StringIO()
        call_command("resync_order_operations", stdout=out)
        text = out.getvalue()
        self.assertIn("有落差：2 張", text)
        self.assertIn(self.cancelled.number, text)
        self.assertIn("收支：payment_confirmed：False → True", text)
        self.assertIn(self.missing_balance.number, text)
        self.assertIn("新增收款列：尾款（balance）", text)
        self.assertIn("dry-run：未寫入", text)
        self.assertFalse(OrderOperationsProfile.objects.get(order=self.cancelled).payment_confirmed)

        call_command("resync_order_operations", "--apply", "--order", self.cancelled.number, stdout=StringIO())
        self.assertTrue(OrderOperationsProfile.objects.get(order=self.cancelled).payment_confirmed)
        change = OrderChange.objects.get(order=self.cancelled, reason__startswith="重新同步訂單收支")
        self.assertEqual(change.changes["收支：payment_confirmed"], {"before": "False", "after": "True"})
        self.assertFalse(PaymentRecord.objects.filter(order=self.missing_balance, system_key="balance").exists(),
                         "--order 只處理指定的單")
        out = StringIO()
        call_command("resync_order_operations", "--order", self.cancelled.number, stdout=out)
        self.assertIn("有落差：0 張", out.getvalue())
