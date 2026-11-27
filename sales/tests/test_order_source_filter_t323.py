"""T-323（使用者 2026-11-27）：全部訂單「車行／平台」多選篩選。

只比對訂單來源（列表「車行／平台」欄顯示的那一家），不含歸屬車行、不比對備註；
Excel 匯入單用列表顯示的來源比對；停用來源照樣列出；沒選時結果與筆數和原本一樣。
資料全是合成的虛構名稱。
"""
import re
from io import BytesIO
from urllib.parse import parse_qs, urlsplit

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from sales.models import LegacyImportBatch, LegacyImportRow, LegacySalesSnapshot, SalesOrder, SalesSource
from sales.order_exchange.columns import DEFAULT_COLUMNS
from sales.order_exchange.workbook import SHEET_TITLE
from sales.services.order_source_filter import parse_tokens, selected_labels, source_groups, summarize
from sales.tests import test_command_center


def filter_form(response):
    html = response.content.decode()
    return html.split('<form class="filter-bar order-filter-bar"', 1)[1].split("</form>", 1)[0]


class OrderSourceFilterT323Tests(TestCase):
    base_make_order = test_command_center.CommandCenterTests.make_order

    @classmethod
    def setUpTestData(cls):
        test_command_center.CommandCenterTests.setUpTestData.__func__(cls)
        kinds = SalesSource.SourceType
        cls.dealer_a = SalesSource.objects.create(name="合成甲車行", source_type=kinds.DEALER)
        cls.dealer_b = SalesSource.objects.create(name="合成乙車行", source_type=kinds.DEALER)
        cls.dealer_off = SalesSource.objects.create(name="合成停業車行", source_type=kinds.DEALER, active=False)
        cls.platform = SalesSource.objects.create(name="合成網購平台", source_type=kinds.PLATFORM)
        cls.staff = SalesSource.objects.create(name="合成店員", source_type=kinds.STORE)
        cls.house_named = SalesSource.objects.create(name="本店", source_type=kinds.STORE)

    def setUp(self):
        self.client.force_login(self.user)

    def make_order(self, source=None, **changes):
        order = self.base_make_order(timezone.localdate())
        source_type = source.source_type if source else SalesOrder.SourceType.STORE
        SalesOrder.all_objects.filter(pk=order.pk).update(source=source, source_type=source_type, **changes)
        return SalesOrder.objects.select_related("source").get(pk=order.pk)

    def listed(self, **params):
        response = self.client.get(reverse("order_list"), {"tab": "all", "per_page": 100, **params})
        self.assertEqual(response.status_code, 200)
        return {order.pk for order in response.context["orders"]}, response

    def fixture(self):
        return {
            "a": self.make_order(self.dealer_a), "b": self.make_order(self.dealer_b),
            "off": self.make_order(self.dealer_off), "platform": self.make_order(self.platform),
            "staff": self.make_order(self.staff), "house": self.make_order(None),
            "house_named": self.make_order(self.house_named),
        }

    def test_single_source_only_matches_order_source_not_commission_recipient_or_note(self):
        rows = self.fixture()
        # 歸屬車行是甲、來源是乙：不算甲的單。備註寫了甲的名字：也不算。
        credited = self.make_order(self.dealer_b, commission_recipient=self.dealer_a, note="合成甲車行介紹")
        noted = self.make_order(self.platform, note="合成甲車行")
        ids, response = self.listed(src=str(self.dealer_a.pk))
        self.assertEqual(ids, {rows["a"].pk})
        self.assertNotIn(credited.pk, ids)
        self.assertNotIn(noted.pk, ids)
        self.assertEqual(response.context["page_obj"].paginator.count, 1)
        # 每一列「車行／平台」欄都是選到的那一家。
        self.assertEqual({order.source_display for order in response.context["orders"]}, {"合成甲車行"})

    def test_multiple_sources_return_any_of_them(self):
        rows = self.fixture()
        ids, _response = self.listed(src=f"{self.dealer_a.pk},{self.platform.pk}")
        self.assertEqual(ids, {rows["a"].pk, rows["platform"].pk})

    def test_whole_groups(self):
        rows = self.fixture()
        self.assertEqual(self.listed(src="dealer")[0], {rows["a"].pk, rows["b"].pk, rows["off"].pk})
        self.assertEqual(self.listed(src="platform")[0], {rows["platform"].pk})
        self.assertEqual(self.listed(src="store")[0], {rows["staff"].pk, rows["house"].pk, rows["house_named"].pk})
        # 整組和單家可以混用。
        self.assertEqual(self.listed(src=f"platform,{self.dealer_b.pk}")[0], {rows["platform"].pk, rows["b"].pk})

    def test_house_option_matches_every_order_displayed_as_house(self):
        rows = self.fixture()
        ids, response = self.listed(src="house")
        self.assertEqual(ids, {rows["house"].pk, rows["house_named"].pk})
        self.assertEqual({order.source_display for order in response.context["orders"]}, {"馭盛"})

    def test_inactive_source_is_listed_marked_and_filterable(self):
        rows = self.fixture()
        groups, _names = source_groups()
        dealer = next(group for group in groups if group["key"] == "dealer")
        option = next(option for option in dealer["options"] if option["value"] == str(self.dealer_off.pk))
        self.assertTrue(option["inactive"])
        self.assertEqual(dealer["options"][-1], option, "停用的排在同組最後")
        self.assertEqual(self.listed(src=str(self.dealer_off.pk))[0], {rows["off"].pk})
        _ids, response = self.listed()
        self.assertContains(response, '"inactive": true')

    def test_imported_orders_match_the_displayed_source(self):
        rows = self.fixture()
        batch = LegacyImportBatch.objects.create(import_type="operations", original_filename="t323.xlsx", file_size=0)
        imported = []
        for index, source in enumerate((self.dealer_a, None)):
            order = self.make_order(source)
            row = LegacyImportRow.objects.create(batch=batch, sheet_name="銷貨", source_row=index + 1,
                                                 fingerprint=f"t323-imported-{index}")
            LegacySalesSnapshot.objects.create(order=order, import_row=row)
            # 原 Excel 車行文字和顯示不同（沒對應到來源），篩選照列表顯示的比對。
            order.operations.dealer_name = "合成甲車行" if source is None else "原始文字"
            order.operations.save(update_fields=["dealer_name"])
            imported.append(order)
        ids, response = self.listed(src=str(self.dealer_a.pk))
        self.assertEqual(ids, {rows["a"].pk, imported[0].pk})
        self.assertTrue(next(order for order in response.context["orders"] if order.pk == imported[0].pk).origin_imported)
        self.assertIn(imported[1].pk, self.listed(src="house")[0])

    def test_combines_with_search_and_other_filters(self):
        rows = self.fixture()
        from sales.services.order_search import rebuild_order_search_index
        for key in ("a", "b"):
            SalesOrder.all_objects.filter(pk=rows[key].pk).update(owner_name="合成王小明")
            rebuild_order_search_index(rows[key].pk)
        self.assertEqual(self.listed(q="合成王小明")[0], {rows["a"].pk, rows["b"].pk})
        ids, _response = self.listed(src=str(self.dealer_a.pk), q="合成王小明")
        self.assertEqual(ids, {rows["a"].pk})
        SalesOrder.all_objects.filter(pk=rows["b"].pk).update(status="cancelled")
        self.assertEqual(self.listed(src="dealer", status="cancelled")[0], {rows["b"].pk})

    def test_combines_with_transaction_type_scope(self):
        # src 和 txn（營運總表「怎麼算」連過來的交易類型範圍）一起用：兩個條件都要符合。
        rows = self.fixture()
        prize = self.make_order(self.staff, transaction_type=SalesOrder.TransactionType.PRIZE, vehicle_price=0)
        proxy = self.make_order(None, transaction_type=SalesOrder.TransactionType.PROXY_DELIVERY, vehicle_price=0)
        ids, response = self.listed(src=str(self.staff.pk), txn="prize")
        self.assertEqual(ids, {prize.pk})
        self.assertEqual(response.context["page_obj"].paginator.count, 1)
        self.assertEqual(self.listed(src=str(self.staff.pk), txn="performance")[0], {rows["staff"].pk})
        self.assertEqual(self.listed(src="store", txn="non_performance")[0], {prize.pk, proxy.pk})
        self.assertEqual(self.listed(src="house", txn="proxy_delivery")[0], {proxy.pk})
        self.assertEqual(self.listed(src="dealer", txn="non_performance")[0], set())
        self.assertEqual(self.listed(src="dealer", txn="performance")[0], {rows["a"].pk, rows["b"].pk, rows["off"].pk})

    def test_no_selection_and_invalid_values_leave_results_unchanged(self):
        self.fixture()
        response = self.client.get(reverse("order_list"))
        baseline = (response.context["page_obj"].paginator.count, [tab["count"] for tab in response.context["order_tabs"]],
                    response.context["order_tab"])
        for params in ({"src": ""}, {"src": "bogus,,-1"}, {"src": " "}):
            with self.subTest(params):
                again = self.client.get(reverse("order_list"), params)
                self.assertEqual((again.context["page_obj"].paginator.count,
                                  [tab["count"] for tab in again.context["order_tabs"]], again.context["order_tab"]), baseline)
        self.assertNotContains(response, "已套用篩選條件")

    def test_selection_lists_all_matching_orders_like_other_filters(self):
        rows = self.fixture()
        SalesOrder.all_objects.filter(pk=rows["a"].pk).update(status="completed")
        response = self.client.get(reverse("order_list"), {"src": str(self.dealer_a.pk)})
        self.assertEqual(response.context["order_tab"], "all")

    def test_summary_chip_and_clear_link(self):
        self.fixture()
        response = self.client.get(reverse("order_list"), {"src": f"{self.dealer_a.pk},{self.dealer_b.pk}"})
        self.assertContains(response, "已套用篩選條件：車行／平台「合成乙車行、合成甲車行」")
        form = filter_form(response)
        self.assertIn(f'name="src" value="{self.dealer_b.pk},{self.dealer_a.pk}"', form, "依選項順序整理")
        self.assertIn('data-filter-text="合成乙車行、合成甲車行"', form)
        clear = re.search(r'<a class="button ghost small" href="([^"]+)"[^>]*>清除車行／平台</a>', response.content.decode())
        self.assertIsNotNone(clear)
        self.assertNotIn("src=", clear.group(1).replace("&amp;", "&"))
        three = self.client.get(reverse("order_list"), {"src": f"{self.platform.pk},{self.dealer_b.pk},{self.dealer_a.pk}"})
        self.assertContains(three, "車行／平台「合成乙車行 等 3 家」")

    def test_survives_pagination_sort_page_size_and_tabs(self):
        self.fixture()
        response = self.client.get(reverse("order_list"), {"src": str(self.dealer_a.pk), "per_page": 25, "tab": "open"})
        html = response.content.decode().replace("&amp;", "&")
        for tab in response.context["order_tabs"]:
            self.assertIn(f"src={self.dealer_a.pk}", tab["url"])
        for column in response.context["sort_columns"]:
            if not column["locked"]:
                self.assertIn(f"src={self.dealer_a.pk}", column["url"])
        page_size_form = html.split('<form class="order-page-size-form"', 1)[1].split("</form>", 1)[0]
        self.assertIn(f'<input type="hidden" name="src" value="{self.dealer_a.pk}">', page_size_form)
        self.assertIn(f"src={self.dealer_a.pk}", re.search(r'href="([^"]+)" data-order-export-link', html).group(1))

    def test_pagination_links_keep_the_filter(self):
        for _ in range(30):
            self.make_order(self.dealer_a)
        self.make_order(self.dealer_b)
        response = self.client.get(reverse("order_list"), {"src": str(self.dealer_a.pk), "per_page": 25, "tab": "all"})
        self.assertEqual(response.context["page_obj"].paginator.count, 30)
        html = response.content.decode().replace("&amp;", "&")
        self.assertRegex(html, rf'href="\?[^"]*src={self.dealer_a.pk}[^"]*page=2|href="\?[^"]*page=2[^"]*src={self.dealer_a.pk}')
        second = self.client.get(reverse("order_list"), {"src": str(self.dealer_a.pk), "per_page": 25, "tab": "all", "page": 2})
        self.assertEqual(len(second.context["orders"]), 5)

    def test_existing_source_param_names_are_untouched(self):
        # 既有網址參數（例如營運總表的 risk、pay）照舊；新參數叫 src，不和既有鍵衝突。
        from sales.order_exchange.scope import SCOPE_KEYS
        from sales.services.order_filters import FILTER_KEYS, HIDDEN_FILTERS
        self.assertNotIn("src", HIDDEN_FILTERS)
        self.assertIn("src", FILTER_KEYS)
        self.assertIn("src", SCOPE_KEYS)

    def test_export_carries_the_filter(self):
        rows = self.fixture()
        page = self.client.get(reverse("order_list"), {"src": str(self.dealer_a.pk), "tab": "all"})
        link = re.search(r'href="([^"]+)" data-order-export-link', page.content.decode()).group(1).replace("&amp;", "&")
        export_page = self.client.get(link)
        self.assertEqual(export_page.status_code, 200)
        self.assertEqual(export_page.context["total"], 1)
        self.assertIn(("車行／平台", "合成甲車行"), export_page.context["scope_labels"])
        data = {key: values for key, values in parse_qs(urlsplit(link).query).items()}
        data["cols"] = list(DEFAULT_COLUMNS)
        response = self.client.post(reverse("order_export_download"), data)
        self.assertEqual(response.status_code, 200)
        sheet = load_workbook(BytesIO(response.content))[SHEET_TITLE]
        exported = [row[0] for row in sheet.iter_rows(min_row=3, values_only=True) if row[0] is not None]
        self.assertEqual(exported, [rows["a"].pk])


class OrderSourceFilterRulesT323Tests(TestCase):
    def test_parse_drops_unknown_tokens_and_duplicates(self):
        self.assertEqual(parse_tokens("12, dealer,12,house,abc,-3,１２,"), ["12", "dealer", "house"])
        self.assertEqual(parse_tokens(None), [])

    def test_summary_text(self):
        groups = [{"key": "dealer", "all": "全部車行", "options": [{"value": "1", "label": "示範車行甲"}, {"value": "2", "label": "示範車行乙"},
                                                                     {"value": "3", "label": "丙"}]}]
        self.assertEqual(summarize(selected_labels(["2", "1"], groups)), "示範車行甲、示範車行乙")
        self.assertEqual(summarize(selected_labels(["3", "2", "1"], groups)), "示範車行甲 等 3 家")
        self.assertEqual(summarize(selected_labels(["dealer", "2"], groups)), "全部車行")
        self.assertEqual(summarize(selected_labels(["99"], groups, {"99": "併入馭盛的來源"})), "併入馭盛的來源")
