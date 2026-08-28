from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from sales.models import SalesSource
from sales.services.taiwan_address import infer_taiwan_region


class TaiwanAddressRegionTests(TestCase):
    def test_infers_city_and_district_and_normalizes_taiwan_alias(self):
        self.assertEqual(
            infer_taiwan_region("台北市內湖區康寧路三段"),
            ("臺北市", "內湖區"),
        )
        self.assertEqual(
            infer_taiwan_region("新北市汐止區康寧街470號"),
            ("新北市", "汐止區"),
        )

    def test_dealer_address_populates_structured_region(self):
        source = SalesSource.objects.create(
            name="地區回填車行",
            source_type=SalesSource.SourceType.DEALER,
            address="基隆市七堵區明德一路1號",
        )

        self.assertEqual(source.city, "基隆市")
        self.assertEqual(source.district, "七堵區")

    def test_rejects_district_that_does_not_belong_to_city(self):
        source = SalesSource(
            name="錯誤地區車行",
            source_type=SalesSource.SourceType.DEALER,
            city="新北市",
            district="內湖區",
        )

        with self.assertRaises(ValidationError):
            source.full_clean()


class SalesSourceRegionListTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="region-list-user",
            password="pass12345",
        )
        self.client.force_login(self.user)
        self.keelung = SalesSource.objects.create(
            name="基隆分區車行",
            source_type=SalesSource.SourceType.DEALER,
            address="基隆市安樂區基金一路100號",
        )
        self.new_taipei = SalesSource.objects.create(
            name="汐止分區車行",
            source_type=SalesSource.SourceType.DEALER,
            address="新北市汐止區大同路二段100號",
        )
        self.taipei = SalesSource.objects.create(
            name="內湖分區車行",
            source_type=SalesSource.SourceType.DEALER,
            address="臺北市內湖區民權東路六段100號",
        )
        self.unassigned = SalesSource.objects.create(
            name="地區待補車行",
            source_type=SalesSource.SourceType.DEALER,
            address="地址待確認",
        )

    def test_list_groups_dealers_by_city_and_district(self):
        response = self.client.get(reverse("sales_source_list"))

        self.assertEqual(response.status_code, 200)
        groups = {group["value"]: group for group in response.context["region_groups"]}
        self.assertEqual(groups["基隆市"]["count"], 1)
        self.assertEqual(groups["新北市"]["district_groups"][0]["label"], "汐止區")
        self.assertEqual(groups["__unassigned__"]["label"], "地區待補")
        self.assertContains(response, "基隆市")
        self.assertContains(response, "安樂區")

    def test_city_filter_only_returns_selected_city(self):
        response = self.client.get(
            reverse("sales_source_list"),
            {"city": "新北市"},
        )

        self.assertContains(response, self.new_taipei.name)
        self.assertNotContains(response, self.keelung.name)
        self.assertNotContains(response, self.taipei.name)

    def test_district_filter_only_returns_selected_district(self):
        second_new_taipei = SalesSource.objects.create(
            name="板橋分區車行",
            source_type=SalesSource.SourceType.DEALER,
            address="新北市板橋區文化路一段100號",
        )

        response = self.client.get(
            reverse("sales_source_list"),
            {"city": "新北市", "district": "汐止區"},
        )

        self.assertContains(response, self.new_taipei.name)
        self.assertNotContains(response, second_new_taipei.name)

    def test_keyword_search_matches_structured_region(self):
        response = self.client.get(reverse("sales_source_list"), {"q": "汐止區"})

        self.assertContains(response, self.new_taipei.name)
        self.assertNotContains(response, self.keelung.name)
