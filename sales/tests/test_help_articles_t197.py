"""T-197 新版使用說明：文章資料格式、說明頁、權限過濾與合成資料的安全檢查。"""
import json

from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command
from django.test import SimpleTestCase, TestCase, tag
from django.urls import reverse

from sales.access.models import ScreenAccessGrant, UserAccessState
from sales.help import ARTICLES, BY_ROUTE, GROUPS, START_HERE, TIPS, plain
from sales.help.schema import MAX_STEPS, MIN_STEPS, validate
from sales.templatetags.help_tags import help_markup


class HelpArticleDataTests(SimpleTestCase):
    def test_articles_follow_the_format_and_every_screenshot_exists(self):
        self.assertEqual(validate(ARTICLES, GROUPS, START_HERE, TIPS), [])

    def test_every_article_has_an_example_and_short_steps(self):
        for article in ARTICLES:
            with self.subTest(article=article.slug):
                self.assertTrue(article.example.story)
                self.assertTrue(MIN_STEPS <= len(article.steps) <= MAX_STEPS)
                self.assertTrue(all(step.text for step in article.steps))

    def test_start_here_walks_one_order_from_creation_to_close(self):
        self.assertEqual([stop.article for stop in START_HERE],
                         ["create-order", "allocate", "registration", "delivery", "form-print", "close"])

    def test_create_order_example_matches_numbers_the_system_shows(self):
        article = next(item for item in ARTICLES if item.slug == "create-order")
        results = dict(article.example.results)
        self.assertIn("分期外應收 4,400", results)
        self.assertIn("交車時尾款 1,400", results)
        # 2.13.3 起分期單牌險費留空＝不向客人收，說明不能再叫人填 0
        self.assertNotIn("牌險費填 0", " ".join(step.text for step in article.steps))

    def test_demo_orders_give_the_report_example_its_numbers(self):
        from collections import Counter
        from sales.management.commands.seed_help_demo import ORDERS
        period = [row for row in ORDERS if 9 <= row[0] <= 11]
        self.assertEqual(len(ORDERS), 30)
        self.assertEqual(len(period), 23)
        self.assertEqual(Counter(row[3] for row in period),
                         {"store": 11, "platform": 5, "示範車行丙": 4, "示範車行甲": 2, "示範車行乙": 1})
        self.assertTrue(all(row[2] == 0 for row in period if row[3] == "示範車行丙"))  # 範例寫「4 張 SUI 125」

    def test_known_stale_phrases_do_not_come_back(self):
        text = " ".join(plain(" ".join([a.when, a.done, *[s.text for s in a.steps], *[f.answer for f in a.faqs], *a.rules]))
                        for a in ARTICLES)
        for phrase in ("密碼解鎖", "右邊的列印清單", "按儲存修改", "依六個步驟", "浮水印證件"):
            self.assertNotIn(phrase, text)

    def test_routes_point_to_exactly_one_article(self):
        self.assertEqual(BY_ROUTE["form_print"], "form-print")
        self.assertEqual(BY_ROUTE["order_start"], "create-order")

    def test_markup_escapes_everything_except_ui_labels_and_bold(self):
        rendered = help_markup("按 [[確認]] 後**存好**<script>alert(1)</script>")
        self.assertIn('<span class="help-ui">確認</span>', rendered)
        self.assertIn("<b>存好</b>", rendered)
        self.assertNotIn("<script>", rendered)
        self.assertEqual(plain("按 [[確認]] **好**"), "按 「確認」 好")


class HelpPageTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("admin", password="help-test-pass")

    def test_help_pages_require_login(self):
        for url in (reverse("user_guide"), reverse("help_start"), reverse("help_article", args=["create-order"])):
            with self.subTest(url=url):
                self.assertRedirects(self.client.get(url), f"{reverse('login')}?next={url}")

    def test_home_lists_groups_start_here_search_and_tips(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("user_guide"))
        self.assertContains(response, "你要完成什麼事？")
        self.assertContains(response, reverse("help_start"))
        self.assertContains(response, "data-help-search")
        self.assertContains(response, "你可能不知道")
        index = json.loads(response.content.decode().split('id="help-index" type="application/json">', 1)[1].split("</script>", 1)[0])
        self.assertEqual({item["slug"] for item in index}, {article.slug for article in ARTICLES})

    def test_article_shows_example_steps_figures_and_next_stop(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("help_article", args=["create-order"]))
        self.assertContains(response, "這篇的範例")
        self.assertContains(response, "分期外應收 4,400")
        self.assertContains(response, "/static/help/screens/create-order/01-catalog.jpg")
        self.assertContains(response, '<span class="help-ui">選這台接單</span>', html=False)
        self.assertContains(response, "從這裡開始 第 1 站")
        self.assertContains(response, reverse("help_article", args=["allocate"]))

    def test_start_here_lists_six_stops_with_links(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("help_start"))
        self.assertContains(response, "跟著王小明，走完一張單")
        self.assertContains(response, "去這個畫面 →", count=6)
        for stop in START_HERE:
            self.assertContains(response, reverse("help_article", args=[stop.article]))

    def test_unknown_or_forbidden_articles_are_not_found(self):
        user = get_user_model().objects.create_user("help-limited", password="help-test-pass")
        UserAccessState.objects.update_or_create(user=user, defaults={"configured": True})
        ScreenAccessGrant.objects.create(user=user, screen_key="order_intake", view=True, operate=True)
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse("help_article", args=["no-such-article"])).status_code, 404)
        self.assertEqual(self.client.get(reverse("help_article", args=["report-ranking"])).status_code, 404)
        self.assertEqual(self.client.get(reverse("help_article", args=["create-order"])).status_code, 200)
        home = self.client.get(reverse("user_guide"))
        self.assertNotContains(home, "報表中心：查一段期間的車行排行")


class HelpSwitchTests(TestCase):
    """/help/ 是新版：舊連結轉址；姓名選單與手機「更多」的「使用說明」一律開說明首頁（T-206）；舊版 /help/legacy/ 轉到新版。"""

    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("admin", password="help-test-pass")
        self.client.force_login(self.admin)

    def test_old_topic_links_go_to_the_rewritten_article(self):
        self.assertRedirects(self.client.get(reverse("user_guide"), {"topic": "ocr"}),
                             reverse("help_article", args=["id-photo"]))
        self.assertRedirects(self.client.get(reverse("user_guide"), {"topic": "create-order-current"}),
                             reverse("help_article", args=["create-order"]))
        self.assertRedirects(self.client.get(reverse("user_guide"), {"topic": "inventory"}),
                             reverse("help_article", args=["inventory"]))
        self.assertRedirects(self.client.get(reverse("user_guide"), {"topic": "no-such-topic"}), reverse("user_guide"))

    def test_menu_help_link_always_opens_the_help_home(self):
        """T-206：使用者「每次點進去都不一樣，很怪」——不管在哪個畫面，選單的「使用說明」都到 /help/。"""
        home = reverse("user_guide")
        for route in ("dashboard", "order_list", "operations_report", "inventory_list", "form_print", "data_maintenance"):
            with self.subTest(route=route):
                page = self.client.get(reverse(route))
                self.assertEqual(page.context["context_help_url"], home)
                body = page.content.decode()
                self.assertRegex(body, r'class="account-menu__item" href="/help/"')
                self.assertRegex(body, r'<a href="/help/" target="_blank" rel="noopener"><span aria-hidden="true">\?</span><strong>使用說明</strong>')
        # 頁首「這頁做什麼」提示（T-201）照舊連到那一頁的文章
        self.assertContains(self.client.get(reverse("form_print")), reverse("help_article", args=["form-print"]))

    def test_help_home_looks_the_same_wherever_you_came_from(self):
        """說明首頁不再依來源頁多出「你剛才在…」的區塊，每次長一樣。"""
        plain = self.client.get(reverse("user_guide")).content.decode()
        for source in ("form_print", "order_list", "inventory_list"):
            with self.subTest(source=source):
                page = self.client.get(reverse("user_guide"), {"from": source})
                self.assertNotContains(page, "你剛才在")
                self.assertNotContains(page, "help-context")
        self.assertNotIn("你剛才在", plain)

    def test_legacy_guide_url_redirects_to_the_new_guide(self):
        self.assertRedirects(self.client.get(reverse("user_guide_legacy")), reverse("user_guide"))
        self.assertRedirects(self.client.get(reverse("user_guide_legacy"), {"topic": "account-management"}),
                             reverse("help_article", args=["accounts"]))
        self.assertNotContains(self.client.get(reverse("user_guide")), reverse("user_guide_legacy"))

    def test_every_old_topic_has_an_article(self):
        """舊版的 59 個主題都對到新文章，舊版才能移除。"""
        from sales.help import BY_LEGACY_TOPIC
        old_topics = {
            "account-management", "allocation", "announcement-admin", "announcement-inline", "announcements", "cancel-refund",
            "catalog-accounts", "catalog-manage", "command-center-update", "create-order", "custom-discount", "customer-documents",
            "dashboard", "dealer-sales-programs", "dealer-volume-bonus", "delivery", "first-setup", "gift-accessories",
            "gift-distribution", "glossary", "home-favorites", "import-data", "inventory", "master-data", "mobile-shortcuts",
            "multi-payment", "news", "ocr", "official-catalog", "operations", "order-attachments", "order-deletion",
            "order-pricing", "order-recycle-bin", "order-sorting", "order-work", "order-workspace", "order-workspace-finance",
            "personal", "price-list-distribution", "print-company", "print-company-admin", "print-templates", "profit-access",
            "quick-start", "reconciliation", "reconciliation-entry", "registration", "reports", "sales-sources", "search-orders",
            "security", "single-order-access", "site-copy", "subsidy", "system-integrity", "troubleshooting", "vehicle-colors",
            "vehicle-model-tools",
        }
        self.assertEqual(len(old_topics), 59)
        self.assertEqual(sorted(old_topics - set(BY_LEGACY_TOPIC)), [])

    def test_articles_are_grouped_by_frequency_without_roles(self):
        home = self.client.get(reverse("user_guide"))
        for title in ("每天會用", "偶爾用"):
            self.assertContains(home, title)
        self.assertNotContains(home, "只看我的工作")


class SeedHelpDemoGuardTests(TestCase):
    def test_refuses_the_project_database_and_unconfirmed_runs(self):
        with self.assertRaises(CommandError):
            call_command("seed_help_demo", admin_password="x")


@tag("docs")
class UserManualSyncTests(SimpleTestCase):
    """USER_MANUAL.md 由文章資料產生（T-197 第二批）；改了 articles 卻沒重新產生時要擋下。"""

    def test_manual_matches_the_articles(self):
        from sales.help.manual import manual_text, render_manual
        self.assertEqual(manual_text(), render_manual(),
                         "docs/USER_MANUAL.md 與 sales/help/articles.py 不同步，請執行 python manage.py build_user_manual")

    def test_manual_lists_every_article_with_its_screenshots(self):
        from sales.help.articles import ARTICLES
        from sales.help.manual import render_manual
        from sales.help.schema import article_figures
        manual = render_manual()
        for article in ARTICLES:
            with self.subTest(article=article.slug):
                self.assertIn(f". {article.title}\n", manual)
                for figure in article_figures(article):
                    self.assertIn(f"../static/help/screens/{figure.src}", manual)
        self.assertNotIn("[[", manual)

