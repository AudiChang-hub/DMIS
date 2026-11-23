"""T-296（使用者 2026-11-23「這裡應該是要有分期待撥款 平台待撥款 跟現金未結清，這樣才對的上10張單」）。

營運總表「錢」右側原本的「其中：撥款待入帳」只列分期、平台，張數加不回待收合計。改成待收合計依付款方式拆開：
- 四列固定：現金未結清、刷卡未結清、分期待撥款、平台待撥款（順序同卡片內），0 張寫「—」並附讀螢幕文字。
- 每張單只有一種付款方式、只落在一格，所以四列張數、金額加總＝待收合計；金額口徑不變（客人應收＋撥款）。
- 分期、平台金額拆成撥款＋客人自付；平台預估加「約」。對帳頁的撥款待入帳（連結、對不上時的差額）照留在該列下面。
"""
import re
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.urls import reverse

from sales.models import ScreenAccessGrant, UserAccessState
from sales.tests.test_money_card_layout_t293 import MoneyCardScenario
from sales.tests.test_money_card_t278 import ZERO


class OutstandingByPaymentTests(MoneyCardScenario):

    def section(self, response):
        html = response.content.decode()
        start = html.index('id="ops-recon-title"')
        return html[start:html.index("</table>", start)]

    def test_rows_add_up_to_outstanding_total(self):
        # 情境含現金（交車後未結清、未交車）、分期（撥款＋客人自付、只差撥款）、平台（撥款預估＋客人自付）。
        self.scenario()
        response, cockpit = self.cockpit()
        money = cockpit["money"]
        rows = money["by_payment"]
        self.assertEqual([row["label"] for row in rows], ["現金未結清", "刷卡未結清", "分期待撥款", "平台待撥款"])
        self.assertEqual(sum(row["count"] for row in rows), money["outstanding_count"])
        self.assertEqual(sum((row["amount"] for row in rows), ZERO), money["outstanding_amount"])
        self.assertEqual([(row["count"], row["amount"]) for row in rows],
                         [(3, Decimal("244550")), (0, ZERO), (2, Decimal("342610")), (2, Decimal("133627"))])
        for row in rows:
            self.assertEqual(row["customer"] + row["payout"], row["amount"], row["key"])
            self.assertEqual(sum(term["count"] for term in row["terms"]), row["count"], row["key"])
            self.assertEqual(sum((term["amount"] for term in row["terms"]), ZERO), row["amount"], row["key"])
        # 同一種付款方式三格的拆列相加＝這一列（每張單只算進一列）。
        for row in rows:
            cells = [cell for bucket in money["split"].values() for cell in bucket if cell["key"] == row["key"]]
            self.assertEqual(sum(cell["count"] for cell in cells), row["count"])
        installment, platform = rows[2], rows[3]
        self.assertEqual((installment["payout"], installment["customer"]), (Decimal("260460"), Decimal("82150")))
        self.assertEqual((platform["payout"], platform["customer"]), (Decimal("131277"), Decimal("2350")))
        self.assertTrue(platform["estimated"])
        self.assertFalse(installment["estimated"])

    def test_table_shows_four_rows_parts_and_reconciliation(self):
        self.scenario()
        response, _cockpit = self.cockpit()
        html = self.section(response)
        self.assertIn(">待收合計依付款方式拆開</p>", html)
        self.assertNotIn("已含在上面三格", response.content.decode())
        self.assertEqual(re.findall(r'<th scope="row">([^<]+)</th>', html),
                         ["現金未結清", "刷卡未結清", "分期待撥款", "平台待撥款"])
        self.assertRegex(html, r'<th scope="row">現金未結清</th>\s*<td><a [^>]*href="[^"]*risk=outstanding&amp;pay=cash">'
                               r'3 張</a></td>\s*<td>\$244,550</td>')
        self.assertRegex(html, r'<th scope="row">刷卡未結清</th>\s*<td><span class="ops-money__nil" aria-hidden="true">—'
                               r'</span><span class="ops-visually-hidden">0 張</span></td>\s*<td><span class="ops-money__nil" '
                               r'aria-hidden="true">—</span><span class="ops-visually-hidden">沒有金額</span></td>')
        self.assertIn('<td>$342,610<small class="ops-money__parts" data-payment-parts><span>撥款 $260,460</span>'
                      '<span>＋客人 $82,150</span></small></td>', html)
        self.assertIn('<td>約 $133,627<small class="ops-money__parts" data-payment-parts><span>撥款 約 $131,277</span>'
                      '<span>＋客人 $2,350</span></small></td>', html)
        # 對帳頁的撥款待入帳留在分期、平台列下面，連結照舊。
        self.assertRegex(html, r'對帳頁的分期撥款待入帳 <a [^>]*channel=installment">2 張</a> · \$260,460')
        self.assertRegex(html, r'對帳頁的平台撥款待入帳 <a [^>]*channel=platform">2 張</a> · 約 \$131,277')
        formula = response.content.decode()
        self.assertIn('<p class="ops-facts__formula" data-payment-terms="installment"><b>分期待撥款</b>'
                      '<span>＝未交車・尾款待收 1 張 $270,310</span><span>＋已交車待撥款 1 張 $72,300</span></p>', formula)
        self.assertIn('<span>＋交車後未結清 1 張 預估 $63,627（含撥款 預估 $61,277）</span>', formula)

    def test_viewer_without_operations_sees_counts_only(self):
        self.scenario()
        user = get_user_model().objects.create_user("t296-reconciliation", password="test-only")
        UserAccessState.objects.create(user=user, configured=True)
        for screen in ("dashboard", "reconciliation"):
            ScreenAccessGrant.objects.create(user=user, screen_key=screen, view=True)
        self.client.force_login(user)
        response = self.client.get(reverse("operations_report"))
        rows = response.context["cockpit"]["money"]["by_payment"]
        self.assertEqual([row["count"] for row in rows], [3, 0, 2, 2])
        self.assertTrue(all(row["amount"] is None for row in rows))
        html = self.section(response)
        self.assertNotIn("$", html)
        self.assertNotIn("data-payment-terms", response.content.decode())
