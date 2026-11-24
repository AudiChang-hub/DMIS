"""T-230：車行選單／篩選器最上面固定一組「本店：馭盛、永湛」，和車行分開。

本店不進車行名單；選到本店只記名稱、不連車行主檔，不會產生車行傭金、獎勵、掛帳或台數獎金。
範圍只有報表中心篩選、禮品名單兩處（使用者 2026-11-18 勾選）；調車的本店選項 T-310 收回：
放到本店其他門市改用「實際位置」，車仍是庫存，不能調出（使用者 2026-11-24）。
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
from sales.services.transfer_signoff import name_suggestions

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
        self.dealer = SalesSource.objects.create(name="示範車行甲", source_type=SalesSource.SourceType.DEALER)
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

    def post(self, name):
        data = {"name": name, "note": "", "vehicles": [car.pk for car in self.cars]}
        return self.client.post(reverse("inventory_transfer_out"), data, HTTP_X_REQUESTED_WITH="XMLHttpRequest")

    def test_suggestions_have_no_home_stores_and_list_active_dealers(self):
        names = name_suggestions()
        self.assertEqual(names["dealers"], [self.dealer.name])
        self.assertNotIn("永湛", [item["name"] for item in names["used"]])
        html = self.client.get(reverse("inventory_list")).content.decode()
        self.assertNotIn("本店：馭盛", html.split('id="transfer-out-names"')[1].split("</script>")[0])
        self.assertIn("請直接改列表上的「實際位置」", html)

    def test_typing_home_store_name_is_blocked_and_cars_stay_in_stock(self):
        response = self.post("永湛")
        self.assertEqual(response.status_code, 400)
        self.assertIn("實際位置", response.json()["message"])
        self.assertFalse(VehicleTransferSignoff.objects.exists())
        for car in self.cars:
            car.refresh_from_db()
            self.assertEqual(car.status, VehicleInventory.Status.AVAILABLE)
            self.assertEqual(car.disposition_dealer_name, "")


class GiftHomeStoreTests(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_superuser("admin", password="Local-t230-552!"))
        self.dealer = SalesSource.objects.create(name="示範車行甲", source_type=SalesSource.SourceType.DEALER)
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
        self.assertEqual(items, {"馭盛": None, "永湛": None, "示範車行甲": self.dealer})


class ReportHomeStoreFilterTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.dealer = SalesSource.objects.create(name="甲車行", source_type="dealer")
        cls.platform = SalesSource.objects.create(name="示範平台甲員購", source_type="platform")
        cls.yongzhan = SalesSource.objects.create(name="永湛", source_type="store", staff_stores=["yongzhan"])
        cls.staff = SalesSource.objects.create(name="示範員工甲", source_type="store", staff_stores=["yusheng"])
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
                         [("本店", ["馭盛", "永湛"]), ("車行", ["甲車行"]), ("平台", ["示範平台甲員購"])])

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


class HomeLocationMigrationTests(TestCase):
    """T-230 B：總店改名馭盛、新增永湛；空資料庫不建立門市，可回復。"""

    def run_migration(self, direction):
        from importlib import import_module
        from django.apps import apps as django_apps
        getattr(import_module("sales.migrations.0214_t230_home_location_stores"), direction)(django_apps, None)

    def test_renames_hq_and_adds_yongzhan_then_reverts(self):
        Store.objects.create(name="總店", code="HQ")
        Store.objects.create(name="二店", code="S02")
        self.run_migration("forwards")
        self.run_migration("forwards")  # 重跑不重複建立
        self.assertEqual(sorted(Store.objects.values_list("code", "name")), [("HQ", "馭盛"), ("S02", "二店"), ("YZ", "永湛")])
        self.run_migration("backwards")
        self.assertEqual(sorted(Store.objects.values_list("code", "name")), [("HQ", "總店"), ("S02", "二店")])

    def test_empty_database_gets_no_store(self):
        self.run_migration("forwards")
        self.assertFalse(Store.objects.exists())


class InventoryHomeLocationTests(TestCase):
    """T-230 B：庫存實際位置最上面固定本店門市，選了改實際存放門市、不放車行。"""

    def setUp(self):
        self.client.force_login(get_user_model().objects.create_superuser("admin", password="Local-t230-553!"))
        self.yusheng = Store.objects.create(name="馭盛", code="HQ")
        self.yongzhan = Store.objects.create(name="永湛", code="YZ")
        Store.objects.create(name="二店", code="S02")  # 不是本店名稱，不列入
        self.dealer = SalesSource.objects.create(name="示範車行甲", source_type=SalesSource.SourceType.DEALER)
        SalesSource.objects.create(name="永湛", source_type=SalesSource.SourceType.STORE, staff_stores=["yongzhan"])
        model = VehicleModel.objects.create(brand="SYM", name="JET SL 125", model_number="T230B")
        self.color = VehicleColor.objects.create(vehicle_model=model, name="消光黑")
        self.model = model
        self.car = VehicleInventory.objects.create(vehicle_model=model, color=self.color, frame_number="T230B0001",
                                                   ownership_store=self.yusheng, location_store=self.yusheng)

    def edit(self, location):
        return self.client.post(reverse("inventory_edit", args=[self.car.pk]), {
            "vehicle_model": self.model.pk, "color": self.color.pk, "engine_number": "", "frame_number": "T230B0001",
            "acquisition_type": "company", "transfer_source_name": "", "current_dealer": location,
            "received_on": str(self.car.received_on), "condition_note": "", "condition_resolution": "",
        })

    def test_form_lists_home_stores_first_without_store_sources(self):
        html = self.client.get(reverse("inventory_edit", args=[self.car.pk])).content.decode()
        self.assertIn(f'<option value="home-{self.yusheng.pk}" selected data-pinned="1">本店：馭盛</option>', html)
        self.assertIn(f'<option value="home-{self.yongzhan.pk}" data-pinned="1">本店：永湛</option>', html)
        self.assertLess(html.index("本店：永湛"), html.index(f'<option value="{self.dealer.pk}"'))
        self.assertNotIn("本店：二店", html)
        self.assertEqual(html.count(">永湛<"), 0, "永湛來源不出現在車行選項")

    def test_moving_to_yongzhan_changes_store_not_dealer_and_logs_transfer(self):
        response = self.edit(f"home-{self.yongzhan.pk}")
        self.assertEqual(response.status_code, 302, getattr(response, "context", None) and response.context["form"].errors)
        self.car.refresh_from_db()
        self.assertIsNone(self.car.current_dealer, "本店不是車行，不會被當成車行計算")
        self.assertEqual(self.car.location_store, self.yongzhan)
        self.assertEqual(self.car.ownership_store, self.yusheng, "只改實際存放門市，不改歸屬門市")
        self.assertEqual(self.car.actual_location_label, "本店：永湛")
        history = self.car.history_entries.get()
        self.assertEqual((history.from_location_label, history.to_location_label), ("本店", "本店：永湛"))

    def test_dealer_then_back_to_main_store(self):
        self.car.location_store = self.yongzhan
        self.car.save()
        self.edit(str(self.dealer.pk))
        self.car.refresh_from_db()
        self.assertEqual((self.car.current_dealer, self.car.location_store), (self.dealer, self.yongzhan))
        self.edit(f"home-{self.yusheng.pk}")
        self.car.refresh_from_db()
        self.assertEqual((self.car.current_dealer, self.car.location_store), (None, self.yusheng))
        self.assertEqual(self.car.actual_location_label, "本店")

    def test_list_filter_has_home_store_options_and_filters_by_store(self):
        other = VehicleInventory.objects.create(vehicle_model=self.model, color=self.color, frame_number="T230B0002",
                                                ownership_store=self.yusheng, location_store=self.yongzhan)
        VehicleInventory.objects.create(vehicle_model=self.model, color=self.color, frame_number="T230B0003",
                                        ownership_store=self.yusheng, location_store=self.yusheng, current_dealer=self.dealer)
        response = self.client.get(reverse("inventory_list"))
        self.assertContains(response, f'<option value="home-{self.yusheng.pk}" data-pinned="1" >本店：馭盛（1）</option>', html=False)
        self.assertContains(response, f'<option value="home-{self.yongzhan.pk}" data-pinned="1" >本店：永湛（1）</option>', html=False)
        self.assertNotContains(response, '<option value="store"', html=False)
        filtered = self.client.get(reverse("inventory_list"), {"location": f"home-{self.yongzhan.pk}"})
        self.assertEqual([v.pk for v in filtered.context["vehicles"]], [other.pk])
        legacy = self.client.get(reverse("inventory_list"), {"location": "store"})
        self.assertEqual({v.pk for v in legacy.context["vehicles"]}, {self.car.pk, other.pk}, "舊網址 store＝全部本店")
        keyword = self.client.get(reverse("inventory_list"), {"q": "永湛"})
        self.assertEqual([v.pk for v in keyword.context["vehicles"]], [other.pk])
