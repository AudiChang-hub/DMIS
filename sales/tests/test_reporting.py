import copy
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import Client, TestCase
from django.urls import reverse

from sales.models import ReportDefinition, ReportRevision, SalesOrder, SalesSource, VehicleColor, VehicleModel
from sales.reporting.engine import calculate, card_result, drill_query, formula_tree, validate_config
from sales.reporting.views import initial_config


class ReportingTests(TestCase):
    def test_dmis_commission_uses_saved_amount_and_missing_is_not_zero(self):
        from sales.models import OrderOperationsProfile
        card = {**self.config["cards"][0], "metric": "dealer_commission", "dimension": "recipient"}
        orders = list(SalesOrder.objects.order_by("pk"))
        # 正常建單會自動建立 operations；刻意移除測試資料以模擬歷史缺漏。
        OrderOperationsProfile.objects.filter(order=orders[2]).delete()
        for order, amount in zip(orders[:2], [Decimal("1250"), Decimal("2750")]):
            OrderOperationsProfile.objects.update_or_create(order=order, defaults={
                "dealer_commission_expense": amount, "dealer_commission_base": 99999,
                "manual_financial_fields": ["dealer_commission_expense"],
            })
        result = card_result(self.config, card, {})
        self.assertEqual(result["total"], "待補收支資料")
        self.assertEqual(result["raw_total"], None)
        self.assertIn("1 張訂單缺少", result["financial_note"])
        by_key = {row["key"]: row for row in result["rows"]}
        self.assertEqual(by_key[str(self.a.pk)]["value"], "4000")
        self.assertEqual(by_key[str(self.b.pk)]["display"], "待補收支資料")
        self.assertFalse(OrderOperationsProfile.objects.filter(order=orders[2]).exists())
        OrderOperationsProfile.objects.create(order=orders[2], dealer_commission_expense=0)
        result = card_result(self.config, card, {})
        self.assertEqual(result["total"], "4,000")
        self.assertEqual(sum(Decimal(row["value"]) for row in result["rows"]), Decimal("4000"))
        self.assertEqual(result["count"], 3)
        self.assertEqual(card_result(self.config, card, {"source_type": ["store"]})["total"], "0")

    def test_commission_detail_export_and_formula_boundaries(self):
        from sales.models import OrderOperationsProfile
        OrderOperationsProfile.objects.filter(order=SalesOrder.objects.first()).delete()
        self.login()
        config = copy.deepcopy(self.config)
        config["cards"][0]["metric"] = "dealer_commission"
        self.report.published = config
        self.report.save()
        self.assertEqual(validate_config(config), config)
        response = self.client.get(reverse("report_detail", args=[self.report.pk, 0]), {"inline": "1"})
        self.assertContains(response, "DMIS 車行傭金支出")
        self.assertContains(response, "待補收支資料")
        exported = self.client.get(reverse("report_export", args=[self.report.pk, 0]))
        self.assertContains(exported, "不代表已付款")
        self.assertContains(exported, "待補收支資料")
        with self.assertRaises(ValidationError):
            formula_tree("dealer_commission + 500")
        config["cards"][0]["chart"] = "donut"
        with self.assertRaises(ValidationError):
            validate_config(config)

    @classmethod
    def setUpTestData(cls):
        users = get_user_model()
        cls.admin = users.objects.create_superuser("admin", "admin@example.invalid", "Test-Only-123")
        cls.user = users.objects.create_user("report-reader", password="Test-Only-123")
        cls.other_admin = users.objects.create_superuser("other-admin", "other@example.invalid", "Test-Only-123")
        cls.a = SalesSource.objects.create(name="甲車行", source_type="dealer")
        cls.b = SalesSource.objects.create(name="乙車行", source_type="dealer")
        cls.model = VehicleModel.objects.create(brand="SUZUKI", name="報表測試車", energy_type="gas")
        cls.color = VehicleColor.objects.create(vehicle_model=cls.model, name="白")
        for price, source, recipient in [(10000, cls.a, None), (20000, cls.b, cls.a), (30000, cls.b, None)]:
            SalesOrder.objects.create(source_type="dealer", source=source, commission_recipient=recipient,
                order_date=date(2026, 8, 15), registration_date=date(2026, 9, 1),
                owner_type="company", owner_name="不可洩漏的車主", owner_id_number="83739807",
                owner_phone="0912345678", owner_address="測試地址", vehicle_model=cls.model, color=cls.color,
                vehicle_price=price, actual_balance=price, calculated_balance=price, payment_type="cash", status="completed")
        cls.config = initial_config()
        cls.config["audience"] = "team"
        cls.report = ReportDefinition.objects.create(draft=cls.config, published=cls.config, version=1)

    def login(self, user=None):
        self.client.force_login(user or self.admin)

    def test_multiselect_intersection_keeps_repeated_query_in_detail_and_export(self):
        self.login()
        order = SalesOrder.objects.first()
        order.registration_date = date(2026, 8, 31)
        order.save(update_fields=["registration_date"])
        params = {"months": ["2026-08", "2026-09"], "source": [str(self.a.pk), str(self.b.pk)], "brand": ["SUZUKI"], "energy": ["gas"]}
        response = self.client.get(reverse("report_display", args=[self.report.pk]), params)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["results"][0]["count"], 3)
        self.assertIn("months=2026-08&months=2026-09", response.context["query"])
        self.assertIn(f"source={self.a.pk}&source={self.b.pk}", response.context["query"])
        detail = self.client.get(reverse("report_detail", args=[self.report.pk, 0]), params)
        self.assertEqual(detail.context["page_obj"].paginator.count, 3)
        self.assertIn("months=2026-08&months=2026-09", detail.context["back_query"])
        exported = self.client.get(reverse("report_export", args=[self.report.pk, 0]), params)
        self.assertContains(exported, "months=2026-08&months=2026-09")
        response = self.client.get(reverse("report_display", args=[self.report.pk]), {**params, "months": ["2026-09"]})
        self.assertEqual(response.context["results"][0]["count"], 2)
        response = self.client.get(reverse("report_display", args=[self.report.pk]), {**params, "source_type": ["store"]})
        self.assertEqual(response.context["results"][0]["count"], 0)

    def test_invalid_multiselect_rejected_and_empty_legacy_filter_compatible(self):
        self.login()
        route = reverse("report_display", args=[self.report.pk])
        response = self.client.get(route, {"months": ["not-a-month"]})
        self.assertFalse(response.context["filter_form"].is_valid())
        self.assertEqual(response.context["results"], [])
        response = self.client.get(route, {"brand": "", "energy": ""})
        self.assertEqual(response.context["results"][0]["count"], 3)
        response = self.client.get(reverse("report_export", args=[self.report.pk, 0]), {"source": ["9999999999999999999999"]})
        self.assertEqual(response.status_code, 400)

    def test_months_do_not_include_gap_and_preserve_order_date_basis(self):
        config = copy.deepcopy(self.config)
        self.assertEqual(card_result(config, config["cards"][0], {"months": ["2026-08", "2026-10"]})["count"], 0)
        config["date_basis"] = "order_date"
        self.assertEqual(card_result(config, config["cards"][0], {"months": ["2026-08"]})["count"], 3)
        self.assertEqual(card_result(config, config["cards"][0], {"months": ["9999-12"]})["count"], 0)

    def test_inline_detail_shares_permission_and_stale_revision_protection(self):
        self.login()
        url = reverse("report_detail", args=[self.report.pk, 0])
        response = self.client.get(url, {"inline": "1", "group": "v:SUZUKI"})
        self.assertContains(response, "data-detail-content")
        self.assertNotContains(response, "<html")
        self.assertEqual(response.context["page_obj"].paginator.count, 3)
        self.assertEqual(self.client.get(url, {"inline": "1", "revision": "obsolete"}).status_code, 409)
        self.report.published = {**self.config, "audience": "admin"}
        self.report.save()
        self.login(self.user)
        self.assertEqual(self.client.get(url, {"inline": "1"}).status_code, 404)

    def test_navigation_order_and_private_titles_do_not_leak(self):
        public = copy.deepcopy(self.config)
        public.update(title="較前的銷售頁", navigation_group="sales", page_order=1)
        earlier = ReportDefinition.objects.create(draft=public, published=public)
        private = {**public, "title": "不可外洩私人頁", "audience": "admin"}
        ReportDefinition.objects.create(draft=private, published=private)
        self.login(self.user)
        response = self.client.get(reverse("report_display", args=[self.report.pk]))
        self.assertContains(response, "較前的銷售頁")
        self.assertNotContains(response, "不可外洩私人頁")
        self.assertEqual(response.context["navigation"][0]["pages"][0].pk, earlier.pk)
        self.login()
        payload = self.data()
        payload.update(navigation_group="analysis", page_order="12")
        self.assertEqual(self.client.post(reverse("report_edit", args=[self.report.pk]), payload).status_code, 302)
        self.report.refresh_from_db()
        self.assertEqual(self.report.draft["navigation_group"], "analysis")
        self.assertEqual(self.report.draft["page_order"], 12)

    def test_donut_uses_complete_total_not_truncated_total(self):
        config = copy.deepcopy(self.config)
        card = config["cards"][0]
        card.update(chart="donut", dimension="source", limit=1)
        result = card_result(config, card, {})
        self.assertEqual(result["count"], 3)
        self.assertEqual(result["rows"][0]["count"], 2)
        self.assertAlmostEqual(result["rows"][0]["percentage"], 200 / 3)
        self.assertTrue(result["truncated"])
        card["metric"] = "average_price"
        with self.assertRaises(ValidationError):
            validate_config(config)
        card["metric"] = "sale_total"
        SalesOrder.objects.filter(pk=SalesOrder.objects.first().pk).update(vehicle_price=-1)
        with self.assertRaises(ValidationError):
            card_result(config, card, {})

    def data(self, config=None, action="save", version=1):
        config = copy.deepcopy(config or self.config)
        payload = {key: config[key] for key in ("title", "description", "date_basis", "audience")}
        payload.update(version=version, action=action, **{"cards-TOTAL_FORMS": str(len(config["cards"])), "cards-INITIAL_FORMS": "0", "cards-MIN_NUM_FORMS": "1", "cards-MAX_NUM_FORMS": "8"})
        for index, card in enumerate(config["cards"]):
            payload.update({f"cards-{index}-{key}": value for key, value in card.items()})
            payload[f"cards-{index}-ORDER"] = str(index + 1)
        return payload

    def test_only_exact_admin_can_manage_even_other_superuser(self):
        for user in (self.user, self.other_admin):
            self.login(user)
            for route, args in (("report_manage", []), ("report_create", []), ("report_edit", [self.report.pk])):
                self.assertEqual(self.client.get(reverse(route, args=args)).status_code, 403)
            self.assertEqual(self.client.post(reverse("report_edit", args=[self.report.pk]), self.data()).status_code, 403)
            self.assertEqual(self.client.post(reverse("report_lifecycle", args=[self.report.pk]), {"action": "unpublish", "version": 1}).status_code, 403)
        self.login()
        self.assertEqual(self.client.get(reverse("report_manage")).status_code, 200)
        self.assertContains(self.client.get(reverse("report_edit", args=[self.report.pk])), "發布報表")

    def test_anonymous_redirect_and_csrf_enforced(self):
        self.assertEqual(self.client.get(reverse("report_center")).status_code, 302)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)
        self.assertEqual(client.post(reverse("report_edit", args=[self.report.pk]), self.data()).status_code, 403)

    def test_draft_save_does_not_leak_to_published(self):
        self.login()
        config = copy.deepcopy(self.config)
        config["title"] = "尚未發布的機密草稿"
        response = self.client.post(reverse("report_edit", args=[self.report.pk]), self.data(config))
        self.assertEqual(response.status_code, 302)
        self.report.refresh_from_db()
        self.assertEqual(self.report.version, 2)
        self.assertEqual(self.report.published["title"], self.config["title"])
        self.login(self.user)
        self.assertNotContains(self.client.get(reverse("report_center")), config["title"])
        self.assertNotContains(self.client.get(reverse("report_display", args=[self.report.pk])), config["title"])

    def test_publish_saves_and_version_conflict_preserves_data(self):
        self.login()
        config = copy.deepcopy(self.config)
        config["title"] = "新版"
        self.assertEqual(self.client.post(reverse("report_edit", args=[self.report.pk]), self.data(config, "publish")).status_code, 302)
        self.report.refresh_from_db()
        self.assertEqual(self.report.published["title"], "新版")
        self.assertEqual(self.report.revisions.get().action, "publish")
        response = self.client.post(reverse("report_edit", args=[self.report.pk]), self.data(action="save"))
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "另一個分頁更新", status_code=400)
        self.report.refresh_from_db()
        self.assertEqual(self.report.draft["title"], "新版")

    def test_preview_does_not_save_and_sources_are_unchanged(self):
        before = list(SalesOrder.objects.order_by("pk").values())
        self.login()
        response = self.client.post(reverse("report_edit", args=[self.report.pk]), self.data(action="preview"))
        self.assertContains(response, "預覽結果")
        self.report.refresh_from_db()
        self.assertEqual(self.report.version, 1)
        self.assertEqual(list(SalesOrder.objects.order_by("pk").values()), before)

    def test_admin_audience_and_unpublish_block_all_endpoints(self):
        config = copy.deepcopy(self.config)
        config["audience"] = "admin"
        self.report.published = config
        self.report.save()
        for user in (self.user, self.other_admin):
            self.login(user)
            for route, args in (("report_display", [self.report.pk]), ("report_detail", [self.report.pk, 0]), ("report_export", [self.report.pk, 0])):
                self.assertEqual(self.client.get(reverse(route, args=args)).status_code, 404)
        self.login()
        self.assertEqual(self.client.post(reverse("report_lifecycle", args=[self.report.pk]), {"action": "unpublish", "version": 1}).status_code, 302)
        self.assertEqual(self.client.get(reverse("report_display", args=[self.report.pk])).status_code, 404)

    def test_restore_only_draft_and_duplicate_is_private_unpublished(self):
        self.login()
        ReportRevision.objects.create(report=self.report, version=1, action="save", config=self.config, actor=self.admin)
        endpoint = reverse("report_lifecycle", args=[self.report.pk])
        self.assertEqual(self.client.post(endpoint, {"action": "restore", "version": 1, "revision": 1}).status_code, 302)
        self.assertEqual(self.client.post(endpoint, {"action": "duplicate", "version": 2}).status_code, 302)
        duplicate = ReportDefinition.objects.exclude(pk=self.report.pk).get()
        self.assertIsNone(duplicate.published)
        self.assertEqual(duplicate.draft["audience"], "admin")

    def test_aggregate_matches_drill_and_recipient_is_distinct_from_source(self):
        card = {**self.config["cards"][0], "dimension": "recipient", "metric": "sale_total"}
        result = card_result(self.config, card, {})
        self.assertEqual(result["total"], "60,000")
        self.assertEqual(result["count"], 3)
        row = next(row for row in result["rows"] if row["key"] == str(self.a.pk))
        self.assertEqual(row["count"], 2)
        self.assertEqual(Decimal(row["value"]), Decimal(30000))
        self.assertEqual(drill_query(self.config, card, {}, str(self.a.pk)).count(), 2)
        card["dimension"] = "source"
        self.assertEqual(drill_query(self.config, card, {}, str(self.a.pk)).count(), 1)

    def test_date_basis_filters_and_invalid_input(self):
        card = self.config["cards"][0]
        self.assertEqual(card_result(self.config, card, {"end": date(2026, 8, 31)})["count"], 0)
        config = {**self.config, "date_basis": "order_date"}
        self.assertEqual(card_result(config, card, {"end": date(2026, 8, 31)})["count"], 3)
        self.assertEqual(card_result(config, card, {"brand": "不存在"})["count"], 0)
        self.login(self.user)
        self.assertContains(self.client.get(reverse("report_display", args=[self.report.pk]), {"start": "2026-10-01", "end": "2026-09-01"}), "開始日期不可晚於")
        self.assertEqual(self.client.get(reverse("report_export", args=[self.report.pk, 0]), {"start": "invalid"}).status_code, 400)
        self.assertEqual(self.client.get(reverse("report_detail", args=[self.report.pk, 9])).status_code, 404)

    def test_unsafe_formulas_rejected_and_zero_not_hidden(self):
        for expression in ("__import__('os')", "count.__class__", "[count]", "2**100000", "count // 2", "True", "1e999", "owner_phone", "abs(count)"):
            with self.subTest(expression=expression), self.assertRaises(ValidationError):
                formula_tree(expression)
        self.assertEqual(calculate("sale_total / count", {"sale_total": 60000, "count": 3}), Decimal(20000))
        self.assertIsNone(calculate("count / 0", {"count": 3}))
        self.assertEqual(calculate("count * 0.1", {"count": 3}), Decimal("0.3"))

    def test_config_rejects_arbitrary_lookup_and_huge_formset(self):
        config = copy.deepcopy(self.config)
        config["cards"][0]["dimension"] = "owner_id_number"
        with self.assertRaises(ValidationError):
            validate_config(config)
        self.login()
        data = self.data()
        data["cards-TOTAL_FORMS"] = "10000"
        self.assertContains(self.client.post(reverse("report_edit", args=[self.report.pk]), data), "8")
        self.report.refresh_from_db()
        self.assertEqual(self.report.version, 1)

    def test_export_matches_filters_and_detail_has_no_personal_fields(self):
        self.login(self.user)
        response = self.client.get(reverse("report_export", args=[self.report.pk, 0]), {"brand": "SUZUKI"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("SUZUKI,3,3", response.content.decode("utf-8-sig"))
        detail = self.client.get(reverse("report_detail", args=[self.report.pk, 0]))
        self.assertContains(detail, "來源訂單")
        self.assertNotContains(detail, "不可洩漏的車主")
        self.assertNotContains(detail, "83739807")
        self.assertNotContains(detail, "0912345678")

    def test_export_prevents_formula_injection(self):
        self.model.brand = "=HYPERLINK(123)"
        self.model.save(update_fields=["brand"])
        self.login(self.user)
        response = self.client.get(reverse("report_export", args=[self.report.pk, 0]))
        self.assertIn("'=HYPERLINK(123)", response.content.decode("utf-8-sig"))

    def test_top_n_explicitly_warns_and_total_is_not_top_n_total(self):
        card = {**self.config["cards"][0], "dimension": "source", "limit": 1}
        result = card_result(self.config, card, {})
        self.assertTrue(result["truncated"])
        self.assertEqual(result["count"], 3)
        self.assertEqual(result["rows"][0]["count"], 2)

    def test_cancelled_and_unregistered_exclusion(self):
        orders = list(SalesOrder.objects.all())
        SalesOrder.objects.filter(pk=orders[0].pk).update(status="cancelled")
        SalesOrder.objects.filter(pk=orders[1].pk).update(registration_date=None)
        self.assertEqual(card_result(self.config, self.config["cards"][0], {})["count"], 1)

    def test_navigation_separates_reader_and_editor(self):
        self.login(self.user)
        response = self.client.get(reverse("report_center"))
        self.assertContains(response, "報表中心")
        self.assertNotContains(response, reverse("report_manage"))
        self.login()
        self.assertContains(self.client.get(reverse("report_center")), reverse("report_manage"))

    def test_preview_keeps_reordered_form_indices(self):
        self.login()
        payload = self.data(action="preview")
        payload["cards-0-ORDER"] = 2
        payload["cards-1-ORDER"] = 1
        response = self.client.post(reverse("report_edit", args=[self.report.pk]), payload)
        self.assertEqual([form.prefix for form in response.context["rendered_cards"]], ["cards-1", "cards-0"])

    def test_old_report_links_cannot_silently_use_new_design(self):
        from sales.reporting.views import publication_key
        token = publication_key(self.report)
        config = copy.deepcopy(self.config)
        config["cards"][0]["dimension"] = "source"
        self.report.published = config
        self.report.save()
        self.login(self.user)
        for route in ("report_detail", "report_export"):
            self.assertContains(self.client.get(reverse(route, args=[self.report.pk, 0]), {"revision": token}), "報表設計已更新", status_code=409)

    def test_invalid_lifecycle_and_overflow_group_are_not_server_errors(self):
        self.login()
        self.assertEqual(self.client.post(reverse("report_lifecycle", args=[self.report.pk]), {"action": "restore", "version": 1, "revision": "not-number"}).status_code, 400)
        card = {**self.config["cards"][0], "dimension": "source"}
        with self.assertRaises(ValidationError):
            drill_query(self.config, card, {}, "9" * 100)

    def test_reserved_text_is_a_literal_group_not_all_orders(self):
        self.model.brand = "__all__"
        self.model.save(update_fields=["brand"])
        result = card_result(self.config, self.config["cards"][0], {})
        self.assertEqual(result["rows"][0]["key"], "v:__all__")
        self.assertEqual(drill_query(self.config, self.config["cards"][0], {}, "v:__all__").count(), 3)

    def test_seed_is_private_and_idempotent(self):
        from django.core.management import call_command
        from io import StringIO
        ReportDefinition.objects.all().delete()
        output = StringIO()
        call_command("seed_report_templates", stdout=output)
        call_command("seed_report_templates", stdout=output)
        report = ReportDefinition.objects.get()
        self.assertEqual(report.published["audience"], "admin")
        self.assertEqual(report.revisions.count(), 1)
