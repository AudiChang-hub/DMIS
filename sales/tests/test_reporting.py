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
    def test_sales_overview_layout_is_explicit_validated_and_preserved(self):
        from sales.reporting.forms import FilterForm
        config = {**self.config, "reader_layout": "sales_overview"}
        validate_config(config)
        with self.assertRaises(ValidationError):
            validate_config({**config, "reader_layout": "arbitrary"})
        form = FilterForm(reader_layout="sales_overview")
        self.assertEqual([field.name for field in form.common_fields()], ["legacy_source", "months"])
        self.assertIn("start", [field.name for field in form.advanced_fields()])
        self.login()
        payload = self.data(config, action="publish")
        payload["reader_layout"] = "sales_overview"
        response = self.client.post(reverse("report_edit", args=[self.report.pk]), payload)
        self.assertEqual(response.status_code, 302)
        self.report.refresh_from_db()
        self.assertEqual(self.report.published["reader_layout"], "sales_overview")
        response = self.client.get(reverse("report_display", args=[self.report.pk]))
        self.assertContains(response, 'report-sales-overview')
        self.assertContains(response, 'data-report-selection-hint')
        self.assertNotContains(response, 'data-report-multiple')
        self.assertEqual(response.context["filter_form"].COMMON_FIELDS, ("legacy_source", "months"))
        self.assertEqual(FilterForm().COMMON_FIELDS, ("start", "end", "months", "source"))
        self.report.published = self.config
        self.report.save(update_fields=["published"])
        self.assertContains(self.client.get(reverse("report_display", args=[self.report.pk])), 'data-report-multiple')

    def test_center_opens_ordered_report_and_remembers_authorized_page(self):
        self.login()
        config = {**self.config, "title": "總車輛銷售｜原報表核對版", "navigation_group": "sales", "page_order": 1}
        first = ReportDefinition.objects.create(draft=config, published=config, version=1)
        response = self.client.get(reverse("report_center"))
        self.assertEqual(response.context["report"].pk, first.pk)
        self.assertContains(response, '<h1>總車輛銷售</h1>', html=True)
        self.assertContains(response, 'aria-current="page"')
        self.assertNotContains(response, "report-cover")
        self.client.get(reverse("report_display", args=[self.report.pk]))
        self.assertEqual(self.client.get(reverse("report_center")).context["report"].pk, self.report.pk)
        self.report.published = None
        self.report.save()
        self.assertEqual(self.client.get(reverse("report_center")).context["report"].pk, first.pk)

    def test_center_does_not_reuse_another_accounts_or_revoked_page(self):
        self.login(self.user)
        config = {**self.config, "audience": "admin", "title": "不能洩漏的私人報表"}
        private = ReportDefinition.objects.create(draft=config, published=config, version=1)
        session = self.client.session
        session["report_reader_page"] = {"user": str(self.user.pk), "report": private.pk}
        session.save()
        response = self.client.get(reverse("report_center"))
        self.assertNotContains(response, config["title"])
        self.assertNotEqual(response.context["report"].pk, private.pk)
        session = self.client.session
        session["report_reader_page"] = {"user": str(self.admin.pk), "report": private.pk}
        session.save()
        self.assertNotContains(self.client.get(reverse("report_center")), config["title"])
        ReportDefinition.objects.update(published=None)
        self.assertContains(self.client.get(reverse("report_center")), "目前沒有可查看的報表")
        self.assertNotIn("report_reader_page", self.client.session)

    def test_population_page_is_not_exposed_by_navigation_with_malformed_team_audience(self):
        config = {**self.config, "records_mode": "population", "audience": "team", "title": "私人群組"}
        ReportDefinition.objects.create(draft=config, published=config, version=1)
        self.login(self.user)
        self.assertNotContains(self.client.get(reverse("report_center")), "私人群組")

    def test_canvas_preview_is_readonly_and_layout_is_published_and_restorable(self):
        self.login()
        config = copy.deepcopy(self.config)
        config["cards"][0].update(width=12, height=640)
        url = reverse("report_edit", args=[self.report.pk])
        previous = ReportRevision.objects.count()
        response = self.client.post(url, self.data(config, action="canvas"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("report-chart--wide", response.json()["cards"][0])
        self.assertEqual(ReportRevision.objects.count(), previous)
        self.report.refresh_from_db()
        self.assertEqual(self.report.version, 1)
        self.assertEqual(self.client.post(url, self.data(config, action="publish")).status_code, 302)
        self.report.refresh_from_db()
        self.assertEqual(self.report.published["cards"][0]["width"], 12)
        self.assertEqual(self.report.published["cards"][0]["height"], 640)
        response = self.client.get(reverse("report_display", args=[self.report.pk]))
        self.assertContains(response, 'style="min-height:640px"')
        self.assertNotContains(response, 'height:640px;overflow:auto')
        saved_version = self.report.version
        altered = copy.deepcopy(config)
        altered["cards"][0].update(width=6, height=360)
        self.client.post(url, self.data(altered, action="save", version=saved_version))
        restored = self.client.post(reverse("report_lifecycle", args=[self.report.pk]), {"action": "restore", "version": saved_version + 1, "revision": saved_version})
        self.assertEqual(restored.status_code, 302)
        self.report.refresh_from_db()
        self.assertEqual(self.report.draft["cards"][0]["height"], 640)
        self.assertEqual(self.report.published["cards"][0]["height"], 640)
        for user in (self.user, self.other_admin):
            self.login(user)
            self.assertEqual(self.client.post(url, self.data(config, action="canvas")).status_code, 403)

    def test_canvas_rejects_invalid_layout_and_preserves_legacy_config(self):
        validate_config(self.config)
        for key, value in (("width", 7), ("width", True), ("height", 319), ("height", 1201), ("height", "520;display:none")):
            config = copy.deepcopy(self.config)
            config["cards"][0][key] = value
            with self.assertRaises(ValidationError):
                validate_config(config)
        self.login()
        payload = self.data(action="canvas")
        payload["cards-0-height"] = "1201"
        response = self.client.post(reverse("report_edit", args=[self.report.pk]), payload)
        self.assertEqual(response.status_code, 400)
        self.assertIn("errors", response.json())

    def test_population_groups_keep_identity_distinct_and_mask_every_output(self):
        from sales.reporting.records import record_context
        config = {**self.config, "audience": "admin", "include_records": True,
                  "records_mode": "population", "records_page_size": 100}
        orders = list(SalesOrder.objects.order_by("pk"))
        SalesOrder.objects.update(owner_type="local", owner_name="=測試車主", owner_id_number="A123456789")
        SalesOrder.objects.filter(pk=orders[-1].pk).update(owner_id_number="A198765489")
        before = list(SalesOrder.objects.order_by("pk").values())
        context = record_context(validate_config(config), {})
        self.assertEqual(context["records_page"].paginator.count, 2)
        self.assertEqual([row["cells"][-1]["value"] for row in context["records_rows"]], [2, 1])
        self.assertEqual({row["cells"][3]["value"] for row in context["records_rows"]}, {"A＊＊＊＊＊＊89"})
        self.assertNotIn("A123456789", repr(context["records_rows"]))
        self.assertNotIn("A198765489", repr(context["records_page"].object_list))
        self.assertEqual(record_context(config, {"source": [str(self.a.pk)]})["records_rows"][0]["cells"][-1]["value"], 1)
        self.report.published = config
        self.report.save()
        self.login()
        for route in ("report_display", "report_records_export"):
            response = self.client.get(reverse(route, args=[self.report.pk]))
            self.assertContains(response, "A＊＊＊＊＊＊89")
            self.assertNotContains(response, "A123456789")
            self.assertNotContains(response, "A198765489")
        exported = self.client.get(reverse("report_records_export", args=[self.report.pk])).content.decode("utf-8-sig")
        self.assertIn("'=測試車主", exported)
        for user in (self.user, self.other_admin):
            self.login(user)
            for route in ("report_display", "report_records_export"):
                self.assertEqual(self.client.get(reverse(route, args=[self.report.pk])).status_code, 404)
        self.assertEqual(before, list(SalesOrder.objects.order_by("pk").values()))
        with self.assertRaises(ValidationError):
            validate_config({**config, "audience": "team"})

    def test_population_pagination_is_full_not_top_two_hundred(self):
        from sales.reporting.records import record_context
        seed = SalesOrder.objects.first()
        copies = []
        for index in range(201):
            order = copy.copy(seed)
            order.pk = None
            order.number = f"POP-TEST-{index:04}"
            order.owner_name = f"合成車主-{index:04}"
            copies.append(order)
        SalesOrder.objects.bulk_create(copies)
        config = {**self.config, "audience": "admin", "include_records": True,
                  "records_mode": "population", "records_page_size": 100}
        pages = [record_context(config, {}, page)["records_page"] for page in (1, 2, 3)]
        self.assertEqual(pages[0].paginator.count, 202)
        self.assertEqual([len(page.object_list) for page in pages], [100, 100, 2])
        self.assertEqual(sum(row["cells"][-1]["value"] for page in pages for row in page.object_list), 204)
        self.assertEqual(record_context(config, {}, "invalid")["records_page"].number, 1)
        self.assertEqual(record_context(config, {}, 999)["records_page"].number, 3)

    def test_standalone_draft_preview_is_admin_only_readonly_and_filters_draft(self):
        config = {**self.config, "title": "未發布草稿標題", "fixed_filters": {"source": [str(self.a.pk)]},
                  "include_records": True, "records_columns": ["sex"]}
        report = ReportDefinition.objects.create(draft=config, version=1)
        url = reverse("report_draft_preview", args=[report.pk])
        before = ReportRevision.objects.count()
        self.login()
        response = self.client.get(url)
        self.assertContains(response, "未發布草稿標題")
        self.assertEqual(response.context["results"][0]["count"], 1)
        self.assertContains(response, "公司或其他")
        self.assertContains(response, f'href="{url}">清除我的篩選')
        self.assertNotContains(response, "匯出全部符合明細 CSV")
        self.assertEqual(self.client.get(url, {"source": [str(self.b.pk)]}).context["results"][0]["count"], 0)
        report.refresh_from_db()
        self.assertEqual(report.version, 1)
        self.assertFalse(report.published)
        self.assertEqual(ReportRevision.objects.count(), before)
        for user in (self.user, self.other_admin):
            self.login(user)
            self.assertEqual(self.client.get(url).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 302)

    def test_all_thirteen_selected_source_drafts_validate_and_do_not_publish(self):
        from django.core.management import call_command
        from io import StringIO
        from sales.reporting.source_templates import SOURCE_TEMPLATES
        self.assertEqual(len(SOURCE_TEMPLATES), 13)
        orders = list(SalesOrder.objects.order_by("pk").values())
        self.login()
        for key, factory in SOURCE_TEMPLATES.items():
            with self.subTest(page=key):
                config = validate_config(factory())
                self.assertEqual(config["audience"], "admin")
                for card in config["cards"]:
                    card_result(config, card, {})
                call_command("create_source_report_draft", page=key, stdout=StringIO())
                report = ReportDefinition.objects.get(draft__title=config["title"])
                self.assertFalse(report.published)
                preview = self.client.get(reverse("report_draft_preview", args=[report.pk]))
                self.assertEqual(preview.status_code, 200)
                self.assertFalse(preview.context["error"])
                call_command("create_source_report_draft", page=key, stdout=StringIO())
                self.assertEqual(ReportDefinition.objects.filter(draft__title=config["title"]).count(), 1)
        self.assertEqual(orders, list(SalesOrder.objects.order_by("pk").values()))

    def test_age_scope_keeps_unknowns_and_excludes_only_known_under_twenty(self):
        from sales.reporting.engine import base_query
        from django.utils import timezone
        orders = list(SalesOrder.objects.order_by("pk"))
        for order, birthday in zip(orders, (None, date(timezone.localdate().year - 19, 1, 1), date(timezone.localdate().year - 20, 1, 1))):
            SalesOrder.objects.filter(pk=order.pk).update(owner_type="local", owner_birth_date=birthday, owner_id_number="A123456789")
        config = {**self.config, "fixed_filters": {"age_scope": ["adult_or_unknown"]}}
        self.assertEqual(set(base_query(config, {}).values_list("pk", flat=True)), {orders[0].pk, orders[2].pk})
        SalesOrder.objects.filter(pk=orders[1].pk).update(owner_birth_date=date(timezone.localdate().year + 1, 1, 1))
        self.assertEqual(base_query(config, {}).count(), 3)

    def test_bonus_record_and_summary_use_same_saved_allocations(self):
        from sales.models import DealerVolumeBonusRule, DealerVolumeBonusSettlement, DealerVolumeBonusAllocation, OrderOperationsProfile
        from sales.reporting.records import record_context
        order = SalesOrder.objects.order_by("pk").first()
        OrderOperationsProfile.objects.get_or_create(order=order)
        rule = DealerVolumeBonusRule.objects.create(dealer=self.a, brand="SUZUKI", starts_on=date(2026, 9, 1), ends_on=date(2026, 9, 30))
        settlement = DealerVolumeBonusSettlement.objects.create(rule=rule, dealer=self.a, expected_amount=123, actual_amount=123, qualified_quantity=1)
        DealerVolumeBonusAllocation.objects.create(settlement=settlement, order=order, amount=123)
        config = {**self.config, "include_records": True, "records_columns": ["dealer_bonus", "sex"]}
        row = next(row for row in record_context(config, {})["records_rows"] if row["pk"] == order.pk)
        self.assertEqual(Decimal(row["cells"][0]["value"]), Decimal("123"))
        self.assertEqual(row["cells"][1]["value"], "公司或其他")

    def test_model_text_scopes_are_literal_intersections_and_editable(self):
        from sales.reporting.engine import base_query
        from sales.reporting.forms import ScopeForm
        VehicleModel.objects.filter(pk=self.model.pk).update(model_number="EV076SZV")
        self.assertEqual(base_query({**self.config, "fixed_filters": {"model_prefix": ["EV076"]}}, {}).count(), 3)
        self.assertEqual(base_query({**self.config, "fixed_filters": {"model_prefix": ["EV076"], "model_exclude": ["EV076SZV"]}}, {}).count(), 0)
        for pattern in ("EV.*", "ev076", "EV076$"):
            self.assertEqual(base_query({**self.config, "fixed_filters": {"model_contains": [pattern]}}, {}).count(), 0)
        config = {**self.config, "fixed_filters": {"model_prefix": ["EV"]}}
        self.assertEqual(base_query(config, {}, {"fixed_filters": {"model_exact": ["OTHER"]}}).count(), 0)
        form = ScopeForm({"fixed_model_prefix": "EV076\nEV070\nEV076", "fixed_model_exclude": "EV076SZV"})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.scope_data(), {"model_prefix": ["EV076", "EV070"], "model_exclude": ["EV076SZV"]})
        initial = ScopeForm(initial={"fixed_filters": form.scope_data()})
        self.assertEqual(initial["fixed_model_prefix"].value(), "EV076\nEV070")
        self.assertEqual(initial.scope_count(), 3)
        self.assertFalse(ScopeForm({"fixed_model_prefix": "x" * 101}).is_valid())

    def test_model_analysis_templates_preserve_different_source_filters_and_unknown_sex(self):
        from sales.reporting.source_templates import model_analysis
        sex, color = model_analysis("sex"), model_analysis("color")
        for config in (sex, color):
            validate_config(config)
            self.assertEqual(len(config["cards"]), 4)
            self.assertEqual(config["audience"], "admin")
        self.assertEqual(sex["cards"][0]["fixed_filters"], {"model_contains": ["EV060L"]})
        self.assertEqual(color["cards"][0]["fixed_filters"], {"model_contains": ["EV060"]})
        VehicleModel.objects.filter(pk=self.model.pk).update(model_number="EV060L")
        result = card_result(sex, sex["cards"][0], {})
        self.assertEqual(result["count"], 3)
        self.assertEqual(result["rows"][0]["label"], "公司或其他")
        self.assertEqual(drill_query(sex, sex["cards"][0], {}, result["rows"][0]["key"]).count(), 3)

    def test_demographics_keep_unknowns_and_legacy_comparison_without_mutation(self):
        from sales.reporting.engine import dimension_query
        from django.utils import timezone
        order = SalesOrder.objects.order_by("pk").first()
        samples = [
            ("local", "A123456789", None, "生日未填", "男性", "60歲以上", "男性"),
            ("company", "12345678", None, "公司或其他", "公司或其他", "60歲以上", "女性"),
            ("local", "12345678", None, "公司或其他", "公司或其他", "60歲以上", "女性"),
            ("local", "X1", None, "生日未填", "公司或其他", "60歲以上", "男性"),
            ("foreign", "A923456789", date(timezone.localdate().year - 25, 1, 1), "20-29歲", "女性", "20-29歲", "女性"),
            ("foreign", "A823456789", None, "生日未填", "男性", "60歲以上", "男性"),
            ("local", "", None, "生日未填", "公司或其他", "60歲以上", "未填寫或格式錯誤"),
        ]
        for owner_type, identity, birthday, *expected in samples:
            with self.subTest(owner_type=owner_type, expected=expected):
                SalesOrder.objects.filter(pk=order.pk).update(
                    owner_type=owner_type, owner_id_number=identity, owner_birth_date=birthday)
                before = SalesOrder.objects.filter(pk=order.pk).values().get()
                for dimension, label in zip(("age_group", "sex", "legacy_age_group", "legacy_sex"), expected):
                    query = dimension_query(SalesOrder.objects.filter(pk=order.pk), dimension, "registration_date")
                    self.assertEqual(query.values_list("report_key", flat=True).get(), label)
                self.assertEqual(before, SalesOrder.objects.filter(pk=order.pk).values().get())

    def test_demographic_charts_keep_missing_birthdays_and_support_drill(self):
        card = {**self.config["cards"][0], "dimension": "age_group"}
        config = {**self.config, "cards": [card]}
        validate_config(config)
        SalesOrder.objects.update(owner_birth_date=None, owner_type="local", owner_id_number="A123456789")
        result = card_result(config, card, {})
        self.assertEqual(result["count"], 3)
        self.assertEqual(len(result["rows"]), 1)
        self.assertEqual(result["rows"][0]["label"], "生日未填")
        self.assertEqual(drill_query(config, card, {}, result["rows"][0]["key"]).count(), 3)

    def test_reader_filter_groups_preserve_selected_advanced_conditions(self):
        from sales.reporting.forms import FilterForm
        from django.http import QueryDict
        form = FilterForm(QueryDict("brand=SUZUKI&energy=gas&sort_0=key_desc"))
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual([field.name for field in form.common_fields()], ["start", "end", "months", "source"])
        self.assertEqual(form.advanced_count(), 2)
        self.assertNotIn("sort_0", [field.name for field in form.advanced_fields()])
        self.login(self.user)
        response = self.client.get(reverse("report_display", args=[self.report.pk]), {"brand": "SUZUKI", "energy": "gas"})
        self.assertContains(response, 'class="report-advanced-filter" open')
        self.assertContains(response, "已使用 2 項")
        self.assertEqual(response.context["results"][0]["count"], 3)
        self.assertContains(self.client.get(reverse("report_display", args=[self.report.pk])), "進階篩選")

    def test_count_detail_keeps_saved_recipient_plate_and_finance_fields(self):
        from sales.reporting.records import record_context
        config = {**self.config, "include_records": True,
                  "records_columns": ["commission_recipient", "legacy_dealer", "plate_number", "dealer_commission"]}
        validate_config(config)
        order = SalesOrder.objects.order_by("pk")[1]
        SalesOrder.objects.filter(pk=order.pk).update(final_plate_number="QA-1234")
        rows = record_context(config, {})["records_rows"]
        row = next(row for row in rows if row["pk"] == order.pk)
        cells = {cell["key"]: cell["value"] for cell in row["cells"]}
        self.assertEqual(cells["commission_recipient"], "甲車行")
        self.assertEqual(cells["legacy_dealer"], "乙車行")
        self.assertEqual(cells["plate_number"], "QA-1234")
        self.assertEqual(Decimal(cells["dealer_commission"]), 0)

    def test_summary_table_groups_two_dimensions_and_exports_all_metrics(self):
        import json
        from sales.reporting.views import publication_key
        card = {**self.config["cards"][0], "chart": "table", "dimension": "month", "series": "recipient",
                "additional_metrics": ["sale_total", "dealer_commission"]}
        config = {**self.config, "cards": [card]}
        validate_config(config)
        result = card_result(config, card, {})
        self.assertEqual(result["count"], 3)
        self.assertEqual(len(result["rows"]), 2)
        first = next(row for row in result["rows"] if row["count"] == 2)
        self.assertEqual(first["dimension_cells"], ["2026/09", "甲車行"])
        self.assertEqual(first["metric_cells"][1]["value"], "30000")
        self.assertEqual(drill_query(config, card, {}, first["key"]).count(), 2)
        focus = json.dumps([{"card": 0, "group": first["key"], "grain": ""}])
        self.assertEqual(card_result(config, card, {"focus": focus})["count"], 2)
        self.report.published = config
        self.report.save()
        self.login(self.user)
        params = {"focus": focus, "revision": publication_key(self.report)}
        self.assertContains(self.client.get(reverse("report_display", args=[self.report.pk]), params), "多欄彙總與來源明細")
        exported = self.client.get(reverse("report_export", args=[self.report.pk, 0]), params)
        self.assertContains(exported, "月份,台數與傭金歸屬車行,訂單台數,訂單車價合計,DMIS 車行傭金支出")
        self.assertContains(exported, "2026/09,甲車行,2,30000")

    def test_saved_bonus_summary_does_not_multiply_order_values_or_recalculate_manual_total(self):
        from sales.models import DealerVolumeBonusRule, DealerVolumeBonusSettlement, DealerVolumeBonusAllocation, OrderOperationsProfile
        order = SalesOrder.objects.order_by("pk").first()
        for amount in (100, 200):
            rule = DealerVolumeBonusRule.objects.create(dealer=self.a, brand="SUZUKI",
                starts_on=date(2026, 9, 1), ends_on=date(2026, 9, 30))
            settlement = DealerVolumeBonusSettlement.objects.create(rule=rule, dealer=self.a,
                expected_amount=amount, actual_amount=amount, qualified_quantity=1)
            DealerVolumeBonusAllocation.objects.create(order=order, settlement=settlement, amount=amount)
        OrderOperationsProfile.objects.filter(order=order).update(dealer_commission_expense=765,
            dealer_commission_base=99999, manual_financial_fields=["dealer_commission_expense"])
        card = {**self.config["cards"][0], "chart": "table", "dimension": "month", "series": "recipient",
                "metric": "dealer_bonus", "additional_metrics": ["count", "sale_total", "dealer_commission"]}
        result = card_result(self.config, card, {})
        self.assertEqual(Decimal(result["raw_total"]), 300)
        self.assertEqual(result["count"], 3)
        self.assertEqual([Decimal(cell["value"]) for cell in result["table_total_cells"]], [300, 3, 60000, 765])
        self.assertIn("兩欄不可再相加", result["financial_note"])
        self.assertEqual(OrderOperationsProfile.objects.get(order=order).dealer_commission_expense, 765)
        self.assertEqual(DealerVolumeBonusAllocation.objects.count(), 2)

    def test_summary_table_missing_finance_does_not_hide_counts_or_invent_zero(self):
        from sales.models import OrderOperationsProfile
        OrderOperationsProfile.objects.filter(order=SalesOrder.objects.first()).delete()
        card = {**self.config["cards"][0], "chart": "table", "additional_metrics": ["dealer_bonus", "dealer_commission"]}
        result = card_result(self.config, card, {})
        self.assertEqual(result["total"], "3")
        self.assertEqual([cell["display"] for cell in result["table_total_cells"]], ["3", "待補收支資料", "待補收支資料"])

    def test_summary_table_rejects_ambiguous_or_unbounded_configuration(self):
        card = {**self.config["cards"][0], "chart": "table"}
        invalid = [{"additional_metrics": ["count"]}, {"additional_metrics": ["sale_total"] * 5},
                   {"additional_metrics": ["formula"]}, {"additional_metrics": ["owner_phone"]},
                   {"additional_metrics": "sale_total"}, {"additional_metrics": [["count"]]},
                   {"series": "brand"}, {"series": "month", "metric": "formula", "formula": "count"},
                   {"chart": "bar", "metric": "dealer_bonus"}]
        for values in invalid:
            with self.subTest(values=values), self.assertRaises(ValidationError):
                validate_config({**self.config, "cards": [{**card, **values}]})

    def test_reader_controls_change_only_selected_chart_and_preserve_export_drill(self):
        from sales.reporting.views import publication_key
        card = {**self.config["cards"][0], "dimension": "month"}
        self.report.published = {**self.config, "cards": [card, {**card, "title": "第二圖"}]}
        self.report.save()
        self.login(self.user)
        params = {"grain_0": "year", "grain_1": "day", "sort_0": "key_desc", "brand": ["SUZUKI"],
                  "revision": publication_key(self.report)}
        response = self.client.get(reverse("report_display", args=[self.report.pk]), params)
        self.assertEqual(response.context["results"][0]["rows"][0]["label"], "2026")
        self.assertEqual(response.context["results"][1]["rows"][0]["label"], "2026/09/01")
        self.assertEqual(response.context["results"][0]["card"]["sort"], "key_desc")
        hidden = response.context["results"][0]["controls_hidden"]
        self.assertIn({"name": "grain_1", "value": "day"}, hidden)
        self.assertIn({"name": "brand", "value": "SUZUKI"}, hidden)
        self.assertNotIn({"name": "grain_0", "value": "year"}, hidden)
        self.assertContains(self.client.get(reverse("report_export", args=[self.report.pk, 0]), params), "2026,3,3")
        detail = self.client.get(reverse("report_detail", args=[self.report.pk, 0]), {**params, "group": "2026-01-01"})
        self.assertEqual(detail.context["page_obj"].paginator.count, 3)
        self.report.refresh_from_db()
        self.assertEqual(self.report.published["cards"][0]["dimension"], "month")
        invalid = self.client.get(reverse("report_export", args=[self.report.pk, 0]), {"sort_0": "owner_phone"})
        self.assertEqual(invalid.status_code, 400)

    def test_rebuild_progress_is_only_available_to_exact_admin(self):
        self.login()
        self.assertContains(self.client.get(reverse("report_manage")), "原 Google 報表重建核對紀錄")
        for user in (self.user, self.other_admin):
            self.login(user)
            self.assertEqual(self.client.get(reverse("report_manage")).status_code, 403)
            self.assertNotContains(self.client.get(reverse("report_center")), "原 Google 報表重建核對紀錄")

    def test_cross_filter_intersects_cards_records_and_exports(self):
        import json
        from sales.reporting.records import record_context
        from sales.reporting.views import publication_key
        config = {**self.config, "include_records": True, "records_columns": ["number"], "cards": [
            {**self.config["cards"][0], "dimension": "source"},
            {**self.config["cards"][0], "dimension": "recipient"}]}
        filters = {"focus": json.dumps([{"card": 0, "group": str(self.b.pk), "grain": ""},
                                        {"card": 1, "group": str(self.a.pk), "grain": ""}])}
        for card in config["cards"]:
            self.assertEqual(card_result(config, card, filters)["count"], 1)
            self.assertEqual(drill_query(config, card, filters, "__all__").count(), 1)
        self.assertEqual(record_context(config, filters)["records_page"].paginator.count, 1)
        self.report.published = config
        self.report.save()
        self.login(self.user)
        params = {**filters, "revision": publication_key(self.report)}
        response = self.client.get(reverse("report_display", args=[self.report.pk]), params)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["focus_items"]), 2)
        self.assertEqual(response.context["records_page"].paginator.count, 1)
        self.assertContains(self.client.get(reverse("report_records_export", args=[self.report.pk]), params), "訂單編號")
        config["cards"][0]["fixed_filters"] = {"source": [str(self.a.pk)]}
        self.assertEqual(card_result(config, config["cards"][1], filters)["count"], 0)

    def test_cross_filter_freezes_selected_date_grain(self):
        import json
        card = {**self.config["cards"][0], "dimension": "month"}
        config = {**self.config, "cards": [card]}
        filters = {"grain": "day", "focus": json.dumps([{"card": 0, "group": "2026-01-01", "grain": "year"}])}
        result = card_result(config, card, filters)
        self.assertEqual(result["count"], 3)
        self.assertEqual(result["rows"][0]["label"], "2026/09/01")

    def test_cross_filter_multiselect_union_and_candidate_preservation(self):
        import json
        from sales.reporting.views import results
        from sales.reporting.records import record_context
        card = {**self.config["cards"][0], "dimension": "source"}
        config = {**self.config, "cards": [card, {**card, "dimension": "recipient"}], "include_records": True, "records_columns": ["number"]}
        one = {"card": 0, "group": str(self.b.pk), "grain": ""}
        both = {**one, "group": [str(self.a.pk), str(self.b.pk)]}
        filters = {"focus": json.dumps([both])}
        self.assertEqual(card_result(config, card, filters)["count"], 3)
        filters = {"focus": json.dumps([both, {"card": 1, "group": str(self.a.pk), "grain": ""}])}
        self.assertEqual(card_result(config, card, filters)["count"], 2)
        self.assertEqual(record_context(config, filters)["records_page"].paginator.count, 2)
        filters = {"focus": json.dumps([one])}
        candidates = results(config, filters, retain_candidates=True)
        self.assertEqual(candidates[0]["count"], 3)
        self.assertTrue(candidates[0]["retained_candidates"])
        self.assertEqual(candidates[1]["count"], 2)
        self.assertFalse(candidates[1]["retained_candidates"])
        config["fixed_filters"] = {"source": [str(self.a.pk)]}
        self.assertEqual(card_result(config, card, {"focus": json.dumps([both])})["count"], 1)

    def test_cross_filter_multiselect_is_bounded_and_typed(self):
        import json
        from sales.reporting.cross_filter import selections
        for groups in ([], ["a"] * 2, list(map(str, range(21))), [None], [["a"]], ["__all__"], ["o:test"]):
            with self.subTest(groups=groups), self.assertRaises(ValidationError):
                selections(json.dumps([{"card": 0, "group": groups, "grain": ""}]))

    def test_cross_filter_rejects_unbounded_or_ambiguous_selection(self):
        import json
        from sales.reporting.cross_filter import selections
        valid = {"card": 0, "group": "v:SUZUKI", "grain": ""}
        for value in ([valid] * 9, [valid, valid], [{**valid, "card": True}], [{**valid, "lookup": "owner_phone"}],
                      [{**valid, "group": "o:2026-09-01"}], [{**valid, "group": "__all__"}], [{**valid, "grain": "bad"}]):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                selections(json.dumps(value))
        with self.assertRaises(ValidationError):
            card_result(self.config, self.config["cards"][0], {"focus": json.dumps([{**valid, "card": 7}])})

    def test_cross_filter_requires_current_publication_all_endpoints(self):
        import json
        self.login(self.user)
        params = {"focus": json.dumps([{"card": 0, "group": "v:SUZUKI", "grain": ""}])}
        self.report.published = {**self.config, "include_records": True}
        self.report.save()
        for revision in (None, "old"):
            if revision:
                params["revision"] = revision
            for route, args in (("report_display", [self.report.pk]), ("report_records_export", [self.report.pk]),
                                ("report_detail", [self.report.pk, 0]), ("report_export", [self.report.pk, 0])):
                with self.subTest(route=route, revision=revision):
                    self.assertEqual(self.client.get(reverse(route, args=args), params).status_code, 409)

    def test_source_draft_command_is_private_idempotent_and_preserves_edits(self):
        from django.core.management import call_command
        from io import StringIO
        before = list(SalesOrder.objects.order_by("pk").values())
        call_command("create_source_report_draft", stdout=StringIO())
        report = ReportDefinition.objects.exclude(pk=self.report.pk).get()
        self.assertIsNone(report.published)
        self.assertEqual(report.draft["audience"], "admin")
        self.assertEqual(len(report.draft["cards"]), 4)
        report.draft["description"] = "管理者保留的修改"
        report.save()
        call_command("create_source_report_draft", stdout=StringIO())
        report.refresh_from_db()
        self.assertEqual(report.draft["description"], "管理者保留的修改")
        self.assertEqual(report.revisions.count(), 1)
        self.assertEqual(ReportDefinition.objects.count(), 2)
        self.assertEqual(list(SalesOrder.objects.order_by("pk").values()), before)
        self.login(self.user)
        self.assertEqual(self.client.get(reverse("report_display", args=[report.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("report_edit", args=[report.pk])).status_code, 403)

    def test_source_draft_requires_exact_active_admin(self):
        from django.core.management import call_command
        from django.core.management.base import CommandError
        self.admin.is_active = False
        self.admin.save()
        with self.assertRaises(CommandError):
            call_command("create_source_report_draft")
        self.assertEqual(ReportDefinition.objects.count(), 1)

    def test_electric_source_draft_has_independent_fixed_scope_and_preserves_both_pages(self):
        from django.core.management import call_command
        from io import StringIO
        before = list(SalesOrder.objects.order_by("pk").values())
        call_command("create_source_report_draft", stdout=StringIO())
        call_command("create_source_report_draft", page="electric", stdout=StringIO())
        report = ReportDefinition.objects.get(draft__title="電動車銷售統計｜原報表核對版")
        self.assertIsNone(report.published)
        self.assertEqual(report.draft["audience"], "admin")
        self.assertEqual(report.draft["fixed_filters"]["legacy_energy"], ["電車"])
        self.assertEqual(len(report.draft["cards"]), 3)
        self.assertEqual(report.draft["cards"][1]["series"], "legacy_model")
        self.assertIn("legacy_premium", report.draft["records_columns"])
        for card in report.draft["cards"]:
            self.assertEqual(card_result(report.draft, card, {"legacy_energy": ["油車"]})["count"], 0)
        report.draft["description"] = "保留第二頁調整"
        report.save()
        call_command("create_source_report_draft", page="electric", stdout=StringIO())
        report.refresh_from_db()
        self.assertEqual(report.draft["description"], "保留第二頁調整")
        self.assertEqual(report.revisions.count(), 1)
        self.assertEqual(ReportDefinition.objects.count(), 3)
        self.assertEqual(list(SalesOrder.objects.order_by("pk").values()), before)
        self.login(self.user)
        self.assertEqual(self.client.get(reverse("report_display", args=[report.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("report_edit", args=[report.pk])).status_code, 403)

    def test_gasoline_source_drafts_preserve_scope_and_do_not_change_orders(self):
        from django.core.management import call_command
        from io import StringIO
        from sales.reporting.source_templates import electric_vehicle_sales, gasoline_vehicle_sales, gasoline_platform_sales
        from sales.reporting.records import record_context
        before = list(SalesOrder.objects.order_by("pk").values())
        for page, factory, cards in (("gasoline", gasoline_vehicle_sales, 3), ("gasoline-platform", gasoline_platform_sales, 1)):
            with self.subTest(page=page):
                config = validate_config(factory())
                self.assertEqual(len(config["cards"]), cards)
                self.assertEqual(config["fixed_filters"]["legacy_energy"], ["油車"])
                for card in config["cards"]:
                    result = card_result(config, card, {})
                    self.assertEqual(result["count"], record_context(config, {})["records_page"].paginator.count)
                    self.assertEqual(card_result(config, card, {"legacy_energy": ["電車"]})["count"], 0)
                    for row in result["rows"]:
                        self.assertEqual(drill_query(config, card, {}, row["key"]).count(), row["count"])
                call_command("create_source_report_draft", page=page, stdout=StringIO())
                report = ReportDefinition.objects.get(draft__title=config["title"])
                self.assertIsNone(report.published)
                self.assertEqual(report.draft["audience"], "admin")
                report.draft["description"] = "保留管理者修改"
                report.save()
                call_command("create_source_report_draft", page=page, stdout=StringIO())
                report.refresh_from_db()
                self.assertEqual(report.draft["description"], "保留管理者修改")
                self.login(self.user)
                self.assertEqual(self.client.get(reverse("report_edit", args=[report.pk])).status_code, 403)
                self.assertEqual(self.client.get(reverse("report_display", args=[report.pk])).status_code, 404)
        self.assertEqual(gasoline_vehicle_sales()["cards"][1]["series_limit"], 10)
        self.assertEqual(electric_vehicle_sales()["cards"][1]["series_limit"], 20)
        self.assertEqual(list(SalesOrder.objects.order_by("pk").values()), before)

    def test_gasoline_platform_drills_use_both_fixed_filters(self):
        from sales.reporting.source_templates import gasoline_platform_sales
        self.model.model_number = "UC125DA"
        self.model.save(update_fields=["model_number"])
        SalesSource.objects.filter(pk=self.a.pk).update(name="PC")
        SalesSource.objects.filter(pk=self.b.pk).update(name="一般車行")
        config = validate_config(gasoline_platform_sales())
        card = config["cards"][0]
        result = card_result(config, card, {})
        expected = SalesOrder.objects.filter(source=self.a).count()
        self.assertGreater(expected, 0)
        self.assertEqual(result["count"], expected)
        for row in result["rows"]:
            for segment in row["segments"]:
                self.assertEqual(drill_query(config, card, {}, segment["key"]).count(), segment["count"])
        self.assertEqual(card_result(config, card, {"legacy_source": ["車行"]})["count"], 0)

    def test_records_export_escapes_formulas_and_limits_size(self):
        from unittest.mock import patch
        self.report.published = {**self.config, "include_records": True, "records_columns": ["owner_name"]}
        self.report.save()
        SalesOrder.objects.update(owner_name="=HYPERLINK(123)")
        self.login(self.user)
        endpoint = reverse("report_records_export", args=[self.report.pk])
        response = self.client.get(endpoint)
        self.assertEqual(response.status_code, 200)
        self.assertIn("'=HYPERLINK(123)", response.content.decode("utf-8-sig"))
        with patch("sales.reporting.views.record_queryset") as query:
            query.return_value.count.return_value = 5001
            self.assertEqual(self.client.get(endpoint).status_code, 400)
            query.return_value.iterator.assert_not_called()

    def test_records_invalid_page_is_safe_and_queries_are_bounded(self):
        from sales.reporting.records import record_context
        with self.assertNumQueries(3):
            context = record_context(self.config, {}, "not-a-page")
        self.assertEqual(context["records_page"].number, 1)
        self.assertEqual(len(context["records_rows"]), 3)
        self.assertEqual(record_context(self.config, {}, 99999)["records_page"].number, 1)

    def test_series_name_sort_and_colors_agree_between_stacks_and_pies(self):
        SalesSource.objects.filter(pk=self.a.pk).update(name="文傑")
        stack = {**self.config["cards"][0], "chart": "stacked", "dimension": "month", "series": "legacy_sales_source", "series_sort": "key_desc"}
        result = card_result(self.config, stack, {})
        labels = [item["label"] for item in result["series_legend"]]
        self.assertEqual(labels, sorted(labels, reverse=True))
        self.assertEqual([item["label"] for item in result["rows"][0]["segments"]], labels)
        pie = {**self.config["cards"][0], "chart": "donut", "dimension": "legacy_sales_source"}
        pie_colors = {row["label"]: row["color"] for row in card_result(self.config, pie, {})["rows"]}
        self.assertEqual({item["label"]: item["color"] for item in result["series_legend"]}, pie_colors)

    def test_original_source_filter_intersects_fixed_scope_and_records(self):
        from sales.reporting.records import record_context
        SalesSource.objects.filter(pk=self.a.pk).update(name="文傑")
        config = {**self.config, "fixed_filters": {"legacy_source": ["店內員工"]}}
        self.assertEqual(validate_config(config), config)
        self.assertEqual(card_result(config, config["cards"][0], {})["count"], 1)
        self.assertEqual(record_context(config, {})["records_page"].paginator.count, 1)
        self.assertEqual(card_result(config, config["cards"][0], {"legacy_source": ["車行"]})["count"], 0)
        self.assertEqual(record_context(config, {"legacy_source": ["車行"]})["records_page"].paginator.count, 0)
        with self.assertRaises(ValidationError):
            validate_config({**config, "fixed_filters": {"legacy_source": ["bogus"]}})

    def test_records_only_publish_export_whitelist_and_scope(self):
        import csv
        from io import StringIO
        self.login()
        config = {**copy.deepcopy(self.config), "include_records": True, "records_columns": ["number", "source", "total_received"],
                  "records_page_size": 10, "cards": []}
        payload = self.data(config=config, action="publish")
        payload.update(include_records="on", records_columns=config["records_columns"], records_page_size=10,
                       fixed_source=[str(self.a.pk)])
        self.assertEqual(self.client.post(reverse("report_edit", args=[self.report.pk]), payload).status_code, 302)
        response = self.client.get(reverse("report_display", args=[self.report.pk]))
        self.assertEqual(response.context["records_page"].paginator.count, 1)
        self.assertContains(response, "來源訂單明細")
        self.assertNotContains(response, "不可洩漏的車主")
        self.assertNotContains(response, "0912345678")
        exported = self.client.get(reverse("report_records_export", args=[self.report.pk]))
        rows = list(csv.reader(StringIO(exported.content.decode("utf-8-sig"))))
        self.assertEqual(rows[3], ["訂單編號", "目前銷售通路", "DMIS 已確認實收"])
        self.assertEqual(len(rows[4:]), 1)
        self.assertNotContains(exported, "83739807")
        narrowed = self.client.get(reverse("report_display", args=[self.report.pk]), {"source": [str(self.b.pk)]})
        self.assertEqual(narrowed.context["records_page"].paginator.count, 0)
        self.assertContains(narrowed, "目前範圍沒有符合的訂單")

    def test_records_configuration_rejects_private_fields_and_empty_design(self):
        for columns in (["owner_id_number"], ["owner_phone"], ["legacy_snapshot__raw_financials"], ["number", "number"], []):
            with self.subTest(columns=columns), self.assertRaises(ValidationError):
                validate_config({**self.config, "include_records": True, "records_columns": columns})
        for size in (True, 0, 500):
            with self.subTest(size=size), self.assertRaises(ValidationError):
                validate_config({**self.config, "records_page_size": size})
        with self.assertRaises(ValidationError):
            validate_config({**self.config, "cards": []})

    def test_records_checkbox_save_preserves_existing_column_order(self):
        from sales.reporting.forms import ReportForm
        initial = {**self.config, "records_columns": ["legacy_premium", "number", "legacy_gift_card"]}
        form = ReportForm(initial=initial)
        form.cleaned_data = {"records_columns": ["number", "color", "legacy_gift_card", "legacy_premium"]}
        self.assertEqual(form.clean_records_columns(), ["legacy_premium", "number", "legacy_gift_card", "color"])
        form.cleaned_data = {"records_columns": ["number"]}
        self.assertEqual(form.clean_records_columns(), ["number"])

    def test_source_dealer_normalization_merges_only_report_groups_and_drills_exactly(self):
        before = list(SalesOrder.objects.order_by("pk").values())
        SalesSource.objects.filter(pk=self.a.pk).update(name=" p c \t")
        SalesSource.objects.filter(pk=self.b.pk).update(name="PC")
        card = {**self.config["cards"][0], "dimension": "legacy_dealer"}
        result = card_result(self.config, card, {})
        self.assertEqual([(r["label"], r["count"]) for r in result["rows"]], [("PC", 3)])
        self.assertEqual(drill_query(self.config, card, {}, "v:PC").count(), 3)
        SalesSource.objects.filter(pk=self.a.pk).update(name="P\u3000C")
        result = card_result(self.config, card, {})
        self.assertEqual({r["label"] for r in result["rows"]}, {"P\u3000C", "PC"})
        SalesSource.objects.filter(pk=self.a.pk).update(name="   ")
        self.assertEqual(drill_query(self.config, card, {}, "v:馭盛").count(), 1)
        self.assertEqual(list(SalesOrder.objects.order_by("pk").values()), before)

    def test_platform_candidate_intersects_source_and_energy_and_keeps_dealer_labels(self):
        from sales.reporting.source_templates import electric_platform_sales
        from sales.reporting.records import record_context
        config = validate_config(electric_platform_sales())
        self.model.model_number = "EV060L"
        self.model.save(update_fields=["model_number"])
        SalesSource.objects.filter(pk=self.a.pk).update(name="PC")
        SalesSource.objects.filter(pk=self.b.pk).update(name="momo")
        result = card_result(config, config["cards"][0], {})
        self.assertEqual(result["count"], 3)
        self.assertEqual({s["label"] for r in result["rows"] for s in r["segments"]}, {"PC", "MOMO"})
        rows = record_context(config, {})["records_rows"]
        self.assertEqual({r["cells"][1]["value"] for r in rows}, {"PC", "MOMO"})
        self.assertEqual(card_result(config, config["cards"][0], {"legacy_source": ["車行"]})["count"], 0)
        self.assertEqual(card_result(config, config["cards"][0], {"legacy_energy": ["油車"]})["count"], 0)

    def test_records_financial_values_use_confirmed_receipts_and_missing_is_not_zero(self):
        from sales.models import PaymentRecord, OrderOperationsProfile
        from sales.reporting.records import record_context
        order = SalesOrder.objects.first()
        PaymentRecord.objects.create(order=order, item_name="測試已確認", expected_amount=100, received_amount=100, confirmed=True)
        PaymentRecord.objects.create(order=order, item_name="測試未確認", expected_amount=900, received_amount=900, confirmed=False)
        config = {**self.config, "include_records": True, "records_columns": ["number", "total_received", "historical_received_price"]}
        context = record_context(config, {})
        row = next(row for row in context["records_rows"] if row["pk"] == order.pk)
        self.assertEqual(row["cells"][1]["value"], "100")
        self.assertEqual(row["cells"][2]["value"], "非歷史匯入")
        OrderOperationsProfile.objects.filter(order=order).delete()
        row = next(row for row in record_context(config, {})["records_rows"] if row["pk"] == order.pk)
        self.assertEqual(row["cells"][1]["value"], "待補收支資料")

    def test_records_private_export_and_old_pagination_are_blocked(self):
        from sales.reporting.views import publication_key
        config = {**self.config, "audience": "admin", "include_records": True, "records_columns": ["number"]}
        self.report.published = config
        self.report.save()
        revision = publication_key(self.report)
        self.login(self.user)
        self.assertEqual(self.client.get(reverse("report_records_export", args=[self.report.pk])).status_code, 404)
        self.login()
        self.report.published = {**config, "title": "新版"}
        self.report.save()
        for url in (reverse("report_display", args=[self.report.pk]), reverse("report_records_export", args=[self.report.pk])):
            self.assertEqual(self.client.get(url, {"records_page": 2, "revision": revision}).status_code, 409)

    def test_source_sales_classification_preserves_five_categories_and_regex_plus(self):
        card = {**self.config["cards"][0], "dimension": "legacy_sales_source"}
        for name, label in (("中古車", "馭盛"), ("假展場", "馭盛"), ("Yahoo", "網路平台"),
                            ("文傑", "店內員工"), ("峻生", "店內員工"), ("展場", "展場"),
                            ("Yahoo+假展場", "車行"), ("Yahoo假展場", "網路平台"),
                            ("Yahoo假展場\n", "車行"), ("其他", "車行")):
            with self.subTest(name=name):
                SalesSource.objects.filter(pk=self.a.pk).update(name=name)
                result = card_result(self.config, card, {"source": [str(self.a.pk)]})
                self.assertEqual([(row["label"], row["count"]) for row in result["rows"]], [(label, 1)])
                self.assertEqual(drill_query(self.config, card, {"source": [str(self.a.pk)]}, result["rows"][0]["key"]).count(), 1)

    def test_stacked_other_series_preserves_total_nulls_and_scoped_drill(self):
        card = {**self.config["cards"][0], "chart": "stacked", "dimension": "month", "series": "source",
                "series_limit": 1, "series_other": True}
        SalesOrder.objects.filter(source=self.a).update(source=None)
        result = card_result(self.config, card, {})
        self.assertTrue(result["series_truncated"])
        segments = result["rows"][0]["segments"]
        self.assertEqual(sum(segment["count"] for segment in segments), 3)
        other = next(segment for segment in segments if segment["key"].startswith("o:"))
        self.assertEqual(other["count"], 1)
        self.assertEqual(drill_query(self.config, card, {}, other["key"]).count(), 1)
        self.assertTrue(drill_query(self.config, card, {}, other["key"]).first().source_id is None)
        without_other = {**card, "series_other": False}
        truncated = card_result(self.config, without_other, {})
        self.assertEqual(truncated["rows"][0]["count"], 3)
        self.assertEqual(sum(segment["count"] for segment in truncated["rows"][0]["segments"]), 2)
        with self.assertRaises(ValidationError):
            drill_query(self.config, without_other, {}, other["key"])

    def test_stacked_series_bounds_validation(self):
        for key, value in (("series_limit", 0), ("series_limit", 201), ("series_limit", True), ("series_other", "true")):
            config = copy.deepcopy(self.config)
            config["cards"][0][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValidationError):
                validate_config(config)

    def test_stacked_other_csv_includes_merged_values_and_scope_note(self):
        self.login()
        config = copy.deepcopy(self.config)
        config["cards"][0].update(chart="stacked", dimension="month", series="source", series_limit=1, series_other=True)
        self.report.published = config
        self.report.save()
        response = self.client.get(reverse("report_export", args=[self.report.pk, 0]))
        self.assertContains(response, "2026/09,乙車行,2,2")
        self.assertContains(response, "2026/09,其他系列（合併）,1,1")
        self.assertContains(response, "其餘合併為其他")

    def test_source_motor_type_uses_import_model_without_changing_master(self):
        from sales.models import LegacyImportBatch, LegacyImportRow, LegacySalesSnapshot
        batch = LegacyImportBatch.objects.create(import_type="operations", source_file="test-only.xlsx",
            original_filename="test-only.xlsx", file_sha256="a" * 64, file_size=0, uploaded_by="tester")
        row = LegacyImportRow.objects.create(batch=batch, sheet_name="銷售", source_row=1,
            fingerprint="b" * 64, action="create", mapped_data={"model_number": "M02"})
        order = SalesOrder.objects.first()
        original_number = order.vehicle_model.model_number
        LegacySalesSnapshot.objects.create(order=order, import_row=row)
        from sales.reporting.records import record_cells
        row.raw_data = {"收款價": None, "公司禮卷、匯款": "禮券 2000 元", "平台贈品": "機油", "其他": " 安全帽 ", "公司贈品": "不能混用的欄位"}
        row.save(update_fields=["raw_data"])
        order.refresh_from_db()
        fields = ["historical_received_price", "legacy_gift_card", "legacy_platform_gift", "legacy_premium"]
        self.assertEqual([cell["value"] for cell in record_cells(order, fields)],
                         ["原始未填寫", "禮券 2000 元", "機油", "安全帽"])
        row.raw_data["收款價"] = 0
        row.save(update_fields=["raw_data"])
        order.refresh_from_db()
        self.assertEqual(Decimal(record_cells(order, ["historical_received_price"])[0]["value"]), Decimal("0"))
        card = {**self.config["cards"][0], "dimension": "legacy_motor_type"}
        result = card_result(self.config, card, {})
        self.assertEqual(next(r for r in result["rows"] if r["label"] == "微型電車")["count"], 1)
        self.assertEqual(list(drill_query(self.config, card, {}, "v:微型電車").values_list("pk", flat=True)), [order.pk])
        self.assertIn("不影響", result["compatibility_note"])
        model_card = {**card, "dimension": "legacy_model"}
        model_result = card_result(self.config, model_card, {})
        self.assertEqual(next(r for r in model_result["rows"] if r["label"] == "M02")["count"], 1)
        self.assertEqual(list(drill_query(self.config, model_card, {}, "v:M02").values_list("pk", flat=True)), [order.pk])
        stacked_model = {**card, "chart": "stacked", "dimension": "day", "series": "legacy_model"}
        stacked_result = card_result(self.config, stacked_model, {})
        segment = next(s for r in stacked_result["rows"] for s in r["segments"] if s["label"] == "M02")
        self.assertEqual(drill_query(self.config, stacked_model, {}, segment["key"]).count(), 1)
        from sales.reporting.records import record_context
        records_config = {**self.config, "records_columns": ["legacy_sales_source", "legacy_energy", "energy"]}
        record = next(r for r in record_context(records_config, {})["records_rows"] if r["pk"] == order.pk)
        self.assertEqual([c["value"] for c in record["cells"]], ["車行", "電車", "油車"])
        energy_card = {**card, "dimension": "legacy_energy"}
        for model_number, expected in (("EV060L", "電車"), ("EV_any", "電車"), ("ev060l", "油車"),
                                       ("GOGORO Pulse", "電車"), ("Pulse", "電車"), ("Pulse Ultra", "油車"),
                                       ("M02", "電車"), ("M02\n", "油車"), ("JDL-B1", "油車")):
            with self.subTest(source_energy_model=model_number):
                row.mapped_data = {"model_number": model_number}
                row.save(update_fields=["mapped_data"])
                matching = drill_query(self.config, energy_card, {}, "v:" + expected)
                self.assertTrue(matching.filter(pk=order.pk).exists())
                scoped_energy = {**self.config, "fixed_filters": {"legacy_energy": [expected]}}
                self.assertEqual(card_result(scoped_energy, energy_card, {})["count"], matching.count())
        order.vehicle_model.refresh_from_db()
        self.assertEqual(order.vehicle_model.model_number, original_number)
        present_config = {**self.config, "fixed_filters": {"model_presence": ["present"]}}
        missing_config = {**self.config, "fixed_filters": {"model_presence": ["missing"]}}
        for mapped, expected in (({}, 2), ({"model_number": None}, 2), ({"model_number": ""}, 3),
                                 ({"model_number": "null"}, 3), ({"model_number": "M02"}, 3)):
            with self.subTest(mapped=mapped):
                row.mapped_data = mapped
                row.save(update_fields=["mapped_data"])
                self.assertEqual(card_result(present_config, card, {})["count"], expected)
                self.assertEqual(card_result(missing_config, card, {})["count"], 3 - expected)
        source_card = {**card, "dimension": "legacy_sales_source"}
        for raw_name, expected in ((None, "馭盛"), ("null", "車行"), ("Yahoo+假展場", "車行"), ("Yahoo", "網路平台")):
            row.mapped_data["dealer_name_raw"] = raw_name
            row.save(update_fields=["mapped_data"])
            result = card_result(self.config, source_card, {})
            group = next(item for item in result["rows"] if item["label"] == expected)
            self.assertIn(order.pk, drill_query(self.config, source_card, {}, group["key"]).values_list("pk", flat=True))

    def test_source_motor_type_preserves_full_match_not_keyword_search(self):
        card = {**self.config["cards"][0], "dimension": "legacy_motor_type"}
        for model_number, label in (("EV076SZV", "白牌電車"), ("S2ABS", "白牌電車"),
                                    ("EZZY", "綠牌電車"), ("M02", "微型電車"),
                                    ("UT125XZ", "速克達"), ("DS250", "擋車"),
                                    ("UQ125DA", "其他"), ("Pulse Ultra", "其他"), ("UQ\n", "其他"), ("uq", "其他"), ("", "其他")):
            with self.subTest(model_number=model_number):
                VehicleModel.objects.all().update(model_number=model_number)
                result = card_result(self.config, card, {})
                self.assertEqual([(row["label"], row["count"]) for row in result["rows"]], [(label, 3)])
                self.assertEqual(drill_query(self.config, card, {}, result["rows"][0]["key"]).count(), 3)

    def test_stacked_series_totals_and_detail_match_with_top_n(self):
        card = {**self.config["cards"][0], "chart": "stacked", "dimension": "source", "series": "energy", "limit": 1}
        result = card_result(self.config, card, {})
        self.assertTrue(result["truncated"])
        self.assertEqual(len(result["rows"]), 1)
        for row in result["rows"]:
            self.assertEqual(sum(segment["count"] for segment in row["segments"]), row["count"])
            for segment in row["segments"]:
                self.assertEqual(drill_query(self.config, card, {}, segment["key"]).count(), segment["count"])
        for key in ('c:[]', 'c:{}', 'c:["x","v:gas"]', 'c:[null,{}]'):
            with self.subTest(key=key), self.assertRaises(ValidationError):
                drill_query(self.config, card, {}, key)

    def test_calendar_grain_and_undated_are_explicit_and_read_only(self):
        config = {**self.config, "include_undated": True}
        card = {**self.config["cards"][0], "chart": "stacked", "dimension": "month", "series": "source", "sort": "key_desc"}
        SalesOrder.objects.filter(pk=SalesOrder.objects.first().pk).update(registration_date=None)
        result = card_result(config, card, {"grain": "year"})
        self.assertEqual(result["count"], 3)
        self.assertEqual(result["rows"][-1]["label"], "日期未填寫")
        self.assertEqual(result["dimension_label"], "年份")
        self.assertEqual(card["dimension"], "month")
        for row in result["rows"]:
            for segment in row["segments"]:
                self.assertEqual(drill_query(config, card, {"grain": "year"}, segment["key"]).count(), segment["count"])
        self.assertEqual(card_result(config, card, {"start": date(2026, 1, 1)})["count"], 2)
        self.assertEqual(card_result(self.config, card, {})["count"], 2)
        with self.assertRaises(ValidationError):
            card_result(config, card, {"grain": "arbitrary"})

    def test_stacked_config_rejects_non_additive_and_ambiguous_series(self):
        for metric, series in (("average_price", "source"), ("dealer_commission", "source"), ("count", "brand"), ("count", "")):
            config = copy.deepcopy(self.config)
            config["cards"][0].update(chart="stacked", metric=metric, dimension="brand", series=series)
            with self.subTest(metric=metric, series=series), self.assertRaises(ValidationError):
                validate_config(config)
        with self.assertRaises(ValidationError):
            validate_config({**self.config, "include_undated": "false"})

    def test_stacked_published_export_and_calendar_detail_share_scope(self):
        self.login()
        config = copy.deepcopy(self.config)
        config["cards"][0].update(chart="stacked", dimension="month", series="source")
        self.report.published = config
        self.report.save()
        result = card_result(config, config["cards"][0], {"grain": "year"})
        exported = self.client.get(reverse("report_export", args=[self.report.pk, 0]), {"grain": "year"})
        self.assertContains(exported, "年份,原銷售車行／通路,訂單台數")
        self.assertContains(exported, "2026,甲車行,1,1")
        self.assertContains(exported, "2026,乙車行,2,2")
        segment = result["rows"][0]["segments"][0]
        response = self.client.get(reverse("report_detail", args=[self.report.pk, 0]), {
            "grain": "year", "group": segment["key"], "inline": "1"})
        self.assertEqual(response.context["page_obj"].paginator.count, segment["count"])


    def test_fixed_scopes_intersect_and_cannot_be_overridden_by_reader(self):
        config = copy.deepcopy(self.config)
        config["fixed_filters"] = {"energy": ["gas"], "source": [str(self.a.pk), str(self.b.pk)]}
        card = config["cards"][0]
        card["fixed_filters"] = {"source": [str(self.a.pk)], "model": [str(self.model.pk)]}
        self.assertEqual(validate_config(config), config)
        self.assertEqual(card_result(config, card, {})["count"], 1)
        self.assertEqual(card_result(config, card, {"source": [str(self.b.pk)]})["count"], 0)
        self.assertEqual(card_result(config, card, {"energy": ["electric"]})["count"], 0)
        self.assertEqual(drill_query(config, card, {}, "__all__").count(), 1)
        self.assertEqual(drill_query(config, card, {"source": [str(self.b.pk)]}, "__all__").count(), 0)
        config["fixed_filters"]["model"] = ["99999999"]
        self.assertEqual(card_result(config, card, {})["count"], 0)

    def test_fixed_scopes_publish_preview_restore_and_preserve_legacy_config(self):
        from sales.reporting.forms import ReportForm, CardForm
        original = copy.deepcopy(self.config)
        ReportForm(initial=original)
        CardForm(initial=original["cards"][0])
        self.assertEqual(original, self.config)
        self.login()
        payload = self.data(action="preview")
        payload.update(fixed_energy=["gas"], **{"cards-0-fixed_source": [str(self.a.pk)]})
        response = self.client.post(reverse("report_edit", args=[self.report.pk]), payload)
        self.assertEqual(response.context["preview"][0]["count"], 1)
        self.assertEqual(response.context["preview"][1]["count"], 3)
        self.report.refresh_from_db()
        self.assertEqual(self.report.version, 1)
        payload["action"] = "publish"
        self.assertEqual(self.client.post(reverse("report_edit", args=[self.report.pk]), payload).status_code, 302)
        self.report.refresh_from_db()
        self.assertEqual(self.report.published["fixed_filters"], {"energy": ["gas"]})
        self.assertEqual(self.report.published["cards"][0]["fixed_filters"], {"source": [str(self.a.pk)]})
        response = self.client.get(reverse("report_edit", args=[self.report.pk]))
        self.assertEqual(response.context["form"]["fixed_energy"].value(), ["gas"])
        self.assertEqual(response.context["formset"][0]["fixed_source"].value(), [str(self.a.pk)])
        self.assertEqual(validate_config(self.config), self.config)

    def test_fixed_scopes_display_detail_export_consistent_and_safe(self):
        config = copy.deepcopy(self.config)
        config["fixed_filters"] = {"energy": ["gas"]}
        config["cards"][0]["fixed_filters"] = {"source": [str(self.a.pk)]}
        self.report.published = config
        self.report.save()
        self.login(self.user)
        response = self.client.get(reverse("report_display", args=[self.report.pk]), {"fixed_energy": "electric"})
        self.assertContains(response, "報表固定範圍")
        self.assertEqual(response.context["results"][0]["count"], 1)
        detail = self.client.get(reverse("report_detail", args=[self.report.pk, 0]), {"inline": "1"})
        self.assertEqual(detail.context["page_obj"].paginator.count, 1)
        self.assertContains(detail, "甲車行")
        exported = self.client.get(reverse("report_export", args=[self.report.pk, 0]))
        self.assertContains(exported, "報表固定範圍")
        self.assertContains(exported, "圖表固定範圍")
        self.assertContains(exported, "SUZUKI,1,1")
        self.assertNotContains(exported, "乙車行")

    def test_invalid_fixed_scopes_rejected_and_deleted_option_preserved(self):
        from sales.reporting.forms import ReportForm
        for invalid in (None, [], {"owner_phone": ["x"]}, {"brand": "SUZUKI"}, {"source": ["1__gte"]},
                        {"source": ["9" * 30]}, {"energy": ["bogus"]}, {"brand": ["x"] * 201}, {"model": [True]}):
            with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                validate_config({**self.config, "fixed_filters": invalid})
        form = ReportForm(initial={**self.config, "fixed_filters": {"source": ["99999999"]}})
        self.assertIn(("99999999", "已移除項目 #99999999"), form.fields["fixed_source"].choices)

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
