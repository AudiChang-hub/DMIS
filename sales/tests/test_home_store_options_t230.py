"""T-230：車行選單／篩選器最上面固定一組「本店：馭盛、永湛」，和車行分開。

本店不進車行名單；選到本店只記名稱、不連車行主檔，不會產生車行傭金、獎勵、掛帳或台數獎金。
範圍只有調車簽收、報表中心篩選、禮品名單三處（使用者 2026-11-18 勾選）。
"""
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.http import QueryDict
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from sales.models import (
    GiftDistribution,
    GiftDistributionItem,
    SalesOrder,
    SalesSource,
    Store,
    VehicleColor,
    VehicleInventory,
    VehicleModel,
    VehicleTransferSignoff,
)
from sales.reporting.engine import base_query
from sales.reporting.forms import FilterForm
from sales.reporting.views import initial_config
from sales.services.home_stores import home_store_choices
from sales.tests.test_transfer_signoff import signature_data_url

HOME = ["store:yusheng", "store:yongzhan"]


class HomeStoreChoiceTests(TestCase):
    def test_choices_come_from_staff_store_and_list_yusheng_first(self):
        self.assertEqual(home_store_choices(), [("store:yusheng", "馭盛"), ("store:yongzhan", "永湛")])

    def test_searchable_select_keeps_pinned_options_on_top(self):
        script = Path("static/js/searchable-select.js").read_text(encoding="utf-8")
        self.assertIn('left.dataset.pinned === "1"', script)


class TransferHomeStoreTests(TestCase):
    def setUp(self):
        self.tempdir = TemporaryDirectory()
        self.override = override_settings(MEDIA_ROOT=self.tempdir.name)
        self.override.enable()
        store = Store.objects.create(name="總店", code="MAIN")
        self.client.force_login(get_user_model().objects.create_superuser("admin", password="Local-t230-551!"))
        self.dealer = SalesSource.objects.create(name="昌勝", source_type=SalesSource.SourceType.DEALER)
        # 正式站的永湛是本店來源（store），不是車行。
        self.yongzhan = SalesSource.objects.create(name="永湛", source_type=SalesSource.SourceType.STORE,
                                                   staff_stores=["yongzhan"])
        model = VehicleModel.objects.create(brand="SYM", name="JET SL 125", model_number="T230")
        color = VehicleColor.objects.create(vehicle_model=model, name="消光黑")
        self.cars = [VehicleInventory.objects.create(vehicle_model=model, color=color, frame_number=f"T230{n:04d}",
                                                     ownership_store=store, location_store=store) for n in range(2)]

    def tearDown(self):
        self.override.disable()
        self.tempdir.cleanup()

    def post(self, step, **extra):
        data = {"dealer": "store:yongzhan", "dealer_name": "", "note": "", "vehicles": [car.pk for car in self.cars],
                "step": step, **extra}
        return self.client.post(reverse("transfer_signoff_create"), data)

    def test_home_stores_are_pinned_on_top_and_not_in_dealer_list(self):
        response = self.client.get(reverse("transfer_signoff_create"))
        html = response.content.decode()
        self.assertIn('<option value="store:yusheng" data-pinned="1">本店：馭盛</option>', html)
        self.assertIn('<option value="store:yongzhan" data-pinned="1">本店：永湛</option>', html)
        self.assertLess(html.index("本店：馭盛"), html.index("原廠／總公司（調回）"))
        self.assertEqual(list(response.context["dealers"]), [self.dealer])
        self.assertNotIn(f'<option value="{self.yongzhan.pk}"', html)

    def test_signing_to_home_store_records_name_without_dealer(self):
        fingerprint = self.post("review").context["fingerprint"]
        response = self.post("sign", agree="1", fingerprint=fingerprint, signature=signature_data_url())
        signoff = VehicleTransferSignoff.objects.get()
        self.assertRedirects(response, reverse("transfer_signoff_detail", args=[signoff.pk]))
        self.assertIsNone(signoff.dealer)
        self.assertEqual(signoff.dealer_name, "永湛")
        for car in self.cars:
            car.refresh_from_db()
            self.assertEqual(car.status, VehicleInventory.Status.TRANSFERRED_OUT)
            self.assertIsNone(car.disposition_dealer, "本店不連車行主檔，不會被當成車行計算")
            self.assertEqual(car.disposition_dealer_name, "永湛")

    def test_typed_name_is_ignored_when_home_store_is_chosen(self):
        self.post("save", dealer="store:yusheng", dealer_name="亂填")
        self.assertEqual(VehicleTransferSignoff.objects.get().dealer_name, "馭盛")

    def test_reopening_pending_home_store_keeps_it_selected(self):
        self.post("save")
        pending = VehicleTransferSignoff.objects.get()
        response = self.client.get(reverse("transfer_signoff_create"), {"pending": pending.pk})
        self.assertContains(response, '<option value="store:yongzhan" data-pinned="1" selected>本店：永湛</option>', html=False)
        self.assertNotContains(response, 'name="dealer_name" maxlength="120" value="永湛"', html=False)


class GiftHomeStoreTests(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_superuser("admin", password="Local-t230-552!"))
        self.dealer = SalesSource.objects.create(name="昌勝", source_type=SalesSource.SourceType.DEALER)
        SalesSource.objects.create(name="永湛", source_type=SalesSource.SourceType.STORE, staff_stores=["yongzhan"])
        self.activity = GiftDistribution.objects.create(title="年節", created_by="admin")
        self.url = reverse("gift_distribution_detail", args=[self.activity.pk])

    def test_picker_lists_home_stores_first_and_dealers_without_them(self):
        response = self.client.get(self.url)
        html = response.content.decode()
        self.assertLess(html.index('value="store:yusheng"'), html.index(f'value="{self.dealer.pk}"'))
        self.assertIn("本店：永湛", html)
        self.assertEqual(list(response.context["sources"]), [self.dealer])

    def test_adding_home_stores_records_names_without_source(self):
        self.client.post(self.url, {"action": "add_sources", "sources": [*HOME, str(self.dealer.pk), "store:bogus"]})
        items = {item.recipient: item.source for item in GiftDistributionItem.objects.filter(distribution=self.activity)}
        self.assertEqual(items, {"馭盛": None, "永湛": None, "昌勝": self.dealer})


class ReportHomeStoreFilterTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.dealer = SalesSource.objects.create(name="甲車行", source_type="dealer")
        cls.platform = SalesSource.objects.create(name="小樹購員購", source_type="platform")
        cls.yongzhan = SalesSource.objects.create(name="永湛", source_type="store", staff_stores=["yongzhan"])
        cls.staff = SalesSource.objects.create(name="文傑", source_type="store", staff_stores=["yusheng"])
        model = VehicleModel.objects.create(brand="SUZUKI", name="T230 報表車", energy_type="gas")
        color = VehicleColor.objects.create(vehicle_model=model, name="白")
        rows = [("dealer", cls.dealer), ("platform", cls.platform), ("store", cls.yongzhan), ("store", cls.yongzhan),
                ("store", None), ("store", cls.staff)]
        for index, (source_type, source) in enumerate(rows):
            SalesOrder.objects.create(source_type=source_type, source=source, order_date=date(2026, 10, 1),
                registration_date=date(2026, 10, 2 + index), registration_completed_at=timezone.now(),
                owner_type="company", owner_name="合成車主", owner_id_number="83739807",
                vehicle_model=model, color=color, vehicle_price=10000, actual_balance=10000,
                calculated_balance=10000, payment_type="cash", status="completed")
        cls.config = {**initial_config(), "audience": "team", "include_records": True}

    def groups(self, form, name):
        return [(group["label"], [value for value, _ in group["choices"]]) for group in form[name].split_groups]

    def test_overview_picker_puts_home_stores_first_and_apart_from_dealers(self):
        config = {**self.config, "reader_layout": "analysis_overview"}
        form = FilterForm(config=config, reader_layout="analysis_overview")
        self.assertEqual(self.groups(form, "legacy_dealer"),
                         [("本店", ["馭盛", "永湛"]), ("車行", ["甲車行"]), ("平台", ["小樹購員購"])])

    def test_selecting_home_store_filters_its_orders(self):
        config = {**self.config, "reader_layout": "analysis_overview"}
        form = FilterForm(QueryDict("legacy_dealer=永湛"), config=config, reader_layout="analysis_overview")
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(base_query(config, form.cleaned_data).count(), 2)

    def test_standard_picker_lists_home_store_sources_first(self):
        form = FilterForm(config=self.config)
        groups = self.groups(form, "source")
        self.assertEqual(groups[:2], [("本店", [str(self.yongzhan.pk)]), ("車行", [str(self.dealer.pk)])])
        self.assertEqual(groups[2][0], "平台")
        self.assertNotIn(str(self.yongzhan.pk), groups[2][1])

    def test_selected_staff_outside_lists_goes_to_dealer_picker_not_home(self):
        form = FilterForm(QueryDict(f"source={self.staff.pk}"), config=self.config)
        groups = dict(self.groups(form, "source"))
        self.assertEqual(groups["本店"], [str(self.yongzhan.pk)])
        self.assertIn(str(self.staff.pk), groups["車行"])

    def test_dealer_only_page_has_no_home_store_picker(self):
        config = {**self.config, "reader_layout": "dealer_overview", "fixed_filters": {"legacy_source": ["車行"]}}
        form = FilterForm(config=config, reader_layout="dealer_overview")
        self.assertEqual(self.groups(form, "legacy_dealer"), [("車行", ["甲車行"])])
