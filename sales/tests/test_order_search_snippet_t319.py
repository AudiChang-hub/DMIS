"""T-319：全部訂單搜尋的「符合欄位」提示只列短摘要。

問題：用客戶名字搜尋，姓名底下把車主姓名、舊車主姓名、好幾條處理紀錄（含電子簽署的
IP、裝置字串、內容指紋、檔案 SHA-256）整段倒出來，單一列撐到一個螢幕高。
修正後：該列已顯示的欄位不再另列；其他欄位最多 2 項、只顯示符合處前後一小段、只有關鍵字標色；
系統稽核資料不出現在結果列。搜尋範圍與結果筆數不變。

本檔資料全部是虛構的：姓名、公司是示範用名稱，IP 用文件專用網段 2001:db8::/32，雜湊是重複字樣。
"""
import re

from django.urls import reverse
from django.test import TestCase

from sales.models import OrderEvent, SalesOrder
from sales.services import order_search
from sales.services.order_search import order_match_terms, rebuild_order_search_index
from sales.tests import test_order_flow  # 只借 setUp／make_order，不把整個 OrderFlowTests 載入本模組重跑

NAME = "歐陽示範"
COMPANY = "示範國際有限公司"
IP = "2001:db8:85a3:8d3:1319:8a2e:370:7348"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/156.0.0.0 Safari/537.36"
FINGERPRINT = "feedface" * 8
OTHER_FINGERPRINT = "cafebabe" * 8
SHA = "deadbeef" * 8
UPLOAD = f"已上傳其他附件：代交車_{NAME}_示範車 125 (TEST125)_示範黃 (Y00)_2026-01-02_03-04-05_0001.xlsx"


class OrderSearchSnippetTests(TestCase):
    setUp = test_order_flow.OrderFlowTests.setUp
    make_order = test_order_flow.OrderFlowTests.make_order

    def make_signed_order(self):
        order = self.make_order()
        order.owner_name = NAME
        order.old_owner_name = NAME
        order.save(update_fields=["owner_name", "old_owner_name", "updated_at"])
        OrderEvent.objects.create(order=order, event_type="delivered",
                                  description=f"完成交付：客人來店取車／{COMPANY}／收車人 {NAME}", actor_name="admin")
        OrderEvent.objects.create(order=order, event_type="attachment", description=UPLOAD, actor_name="admin")
        for label, fingerprint in (("個人資料使用同意書", FINGERPRINT), ("車輛訂購單", OTHER_FINGERPRINT)):
            OrderEvent.objects.create(
                order=order, event_type="privacy_consent_esigned",
                description=(f"客戶於店內行動裝置電子簽署{label}。簽署人：{NAME}；經手：admin；IP：{IP}；裝置：{UA}；"
                             f"內容指紋：{fingerprint}；檔案 SHA-256：{SHA}"),
                actor_name="admin",
            )
        rebuild_order_search_index(order.pk)
        return SalesOrder.objects.get(pk=order.pk)

    def search(self, query):
        self.client.force_login(self.user)
        response = self.client.get(reverse("order_list"), {"q": query})
        self.assertEqual(response.status_code, 200)
        return response

    def row_html(self, response):
        html = response.content.decode()
        table = html.split("<tbody", 1)[1].split("</tbody>", 1)[0]
        cards = html.split('class="order-list order-sort-cards"', 1)[1]
        return table, cards

    def test_name_search_lists_short_snippets_without_audit_data(self):
        order = self.make_signed_order()
        response = self.search(NAME)
        self.assertEqual([row.pk for row in response.context["orders"]], [order.pk])
        row = response.context["orders"][0]
        labels = [match["label"] for match in row.search_matches]
        # 該列已顯示姓名：車主姓名、與車主同名的舊車主姓名都不再另列。
        self.assertNotIn("車主姓名／公司名稱", labels)
        self.assertNotIn("舊車主姓名", labels)
        # 最多 2 項，同一欄位（處理紀錄內容）只列一次。
        self.assertLessEqual(len(row.search_matches), 2)
        self.assertEqual(len(labels), len(set(labels)))
        table, cards = self.row_html(response)
        for html in (table, cards):
            for secret in (IP, "Mozilla/5.0", FINGERPRINT, OTHER_FINGERPRINT, SHA, "SHA-256", "內容指紋", "IP："):
                self.assertNotIn(secret, html)
            # 長字串只顯示符合處前後一小段。
            self.assertNotIn(UPLOAD, html)
            self.assertNotIn("車主姓名／公司名稱：", html)
        for match in row.search_matches:
            self.assertEqual(match["hit"], NAME)
            self.assertLessEqual(len(match["before"] + match["hit"] + match["after"]), 40)
        # 只有關鍵字標色；前後文在 <mark> 外面。
        for html in (table, cards):
            marks = re.findall(r"<mark>(.*?)</mark>", html)
            self.assertTrue(marks)
            self.assertEqual(set(marks), {NAME})
        self.assertIn("…", table)

    def test_snippet_marks_only_keyword_with_ellipsis_both_sides(self):
        order = self.make_order()
        OrderEvent.objects.create(order=order, event_type="manual_note", actor_name="admin",
                                  description="甲" * 40 + "冷氣保固延長" + "乙" * 40)
        rebuild_order_search_index(order.pk)
        response = self.search("冷氣保固")
        row = response.context["orders"][0]
        self.assertEqual(len(row.search_matches), 1)
        match = row.search_matches[0]
        self.assertEqual(match["label"], "處理紀錄內容")
        self.assertEqual(match["hit"], "冷氣保固")
        self.assertTrue(match["before"].startswith("…"))
        self.assertTrue(match["after"].endswith("…"))
        self.assertLessEqual(len(match["before"]) + len(match["after"]), 30)
        # 畫面上：前文、<mark>關鍵字</mark>、後文依序相連，只有關鍵字在 <mark> 裡。
        before, after = "…" + "甲" * 8, "延長" + "乙" * 10 + "…"
        table, cards = self.row_html(response)
        self.assertIn(f"<span>處理紀錄內容：{before}<mark>冷氣保固</mark>{after}</span>", table)
        self.assertIn(
            f'<span class="search-match"><b>處理紀錄內容</b><span class="search-match__text">{before}<mark>冷氣保固</mark>{after}</span></span>',
            cards,
        )
        for html in (table, cards):
            self.assertEqual(re.findall(r"<mark>(.*?)</mark>", html), ["冷氣保固"])

    def test_normalised_match_highlights_original_text(self):
        order = self.make_order()
        matches = [{"label": "備註", "value": "客戶指定編號 ABC-1234 請先聯絡"}]
        shown, more = order_search.condense_order_matches(order, matches, order_match_terms("abc 1234"))
        self.assertEqual(more, 0)
        self.assertEqual(shown[0]["hit"], "ABC-1234")
        self.assertEqual(shown[0]["before"] + shown[0]["hit"] + shown[0]["after"], "客戶指定編號 ABC-1234 請先聯絡")

    def test_extra_matching_fields_are_counted_not_listed(self):
        order = self.make_order()
        matches = [{"label": f"欄位{index}", "value": f"含關鍵字KW{index}"} for index in range(5)]
        shown, more = order_search.condense_order_matches(order, matches, order_match_terms("KW"))
        self.assertEqual([item["label"] for item in shown], ["欄位0", "欄位1"])
        self.assertEqual(more, 3)

    def test_fields_already_on_the_row_are_not_listed_but_note_is(self):
        """車型、引擎號碼、車身號碼在列上已完整顯示，不另列也不算進「另 N 個」；備註在列上是截短的，照樣列摘要。"""
        order = self.make_order()
        matches = [
            {"label": "車型", "value": "KW 125"},
            {"label": "引擎號碼", "value": "KW-ENGINE-0001"},
            {"label": "車身號碼", "value": "KWFRAME0000000001"},
            {"label": "車色", "value": "KW 白"},
            {"label": "備註", "value": "客人指定 KW 排氣管，交車前先確認到貨"},
        ]
        shown, more = order_search.condense_order_matches(order, matches, order_match_terms("KW"))
        self.assertEqual([item["label"] for item in shown], ["備註"])
        self.assertEqual(more, 0)
        self.assertEqual(shown[0]["hit"], "KW")

    def test_note_match_is_listed_on_the_page(self):
        order = self.make_order()
        order.note = "週末才能交車，" + "請先電話聯絡" * 4 + "並確認冷氣保固條款"
        order.save(update_fields=["note", "updated_at"])
        rebuild_order_search_index(order.pk)
        response = self.search("冷氣保固")
        self.assertEqual([match["label"] for match in response.context["orders"][0].search_matches], ["備註"])
        table, cards = self.row_html(response)
        for html in (table, cards):
            self.assertEqual(re.findall(r"<mark>(.*?)</mark>", html), ["冷氣保固"])

    def test_audit_only_match_still_finds_order_without_hint(self):
        """搜尋範圍不變：只在稽核資料符合（IP、指紋）照樣找得到這張單，只是不列提示。"""
        order = self.make_signed_order()
        other = self.make_order()
        rebuild_order_search_index(other.pk)
        for query in (IP, FINGERPRINT[:16], "Chrome/156"):
            with self.subTest(query=query):
                response = self.search(query)
                self.assertEqual([row.pk for row in response.context["orders"]], [order.pk])
                self.assertEqual(response.context["page_obj"].paginator.count, 1)
                self.assertEqual(response.context["orders"][0].search_matches, [])
                table, cards = self.row_html(response)
                self.assertNotIn(query, table)
                self.assertNotIn(query, cards)

    def test_result_set_unchanged_for_event_and_field_queries(self):
        order = self.make_signed_order()
        other = self.make_order()
        rebuild_order_search_index(other.pk)
        for query, expected in ((NAME, [order.pk]), ("示範國際", [order.pk]), ("示範黃", [order.pk]),
                                ("0912345678", sorted([order.pk, other.pk]))):
            with self.subTest(query=query):
                found = sorted(row.pk for row in self.search(query).context["orders"])
                self.assertEqual(found, sorted(expected))
