"""T-347：原廠代墊／代轉的「原廠」改成品牌下拉。

- 訂單頁新增表單、活動設定頁的「原廠」都只能從品牌清單選，來源和車型主檔的品牌下拉同一份（sales.forms._brand_choices）。
- 訂單頁預設帶入訂單車型的品牌；車型品牌不在清單裡也列出來，選了照樣能存。
- 既有資料存的原廠名稱（不在清單裡也一樣）照常顯示，勾選、編輯存檔不報錯；不改舊資料。
- 活動依原廠＋車型自動掛單的比對結果不變。
測試資料一律明顯虛構。
"""
from datetime import date
from decimal import Decimal

from django.urls import reverse

from sales.forms import _brand_choices
from sales.models import ManufacturerAdvance, ManufacturerAdvanceCampaign, VehicleBrand, VehicleColor, VehicleModel
from sales.services import manufacturer_advance as advances
from sales.tests.test_manufacturer_advance_t334 import XHR
from sales.tests.test_manufacturer_advance_t337 import CampaignTestBase

LEGACY = "虛構舊廠牌"


class OrderFormBrandSelectTests(CampaignTestBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        VehicleBrand.objects.create(name="虛構停用品牌", active=False)
        cls.lower_model = VehicleModel.objects.create(brand="suzuki", name="虛構車型丁", energy_type="gas")
        cls.lower_color = VehicleColor.objects.create(vehicle_model=cls.lower_model, name="藍")
        cls.legacy_model = VehicleModel.objects.create(brand=LEGACY, name="虛構車型戊", energy_type="gas")
        cls.legacy_color = VehicleColor.objects.create(vehicle_model=cls.legacy_model, name="綠")

    def create(self, order, **data):
        payload = {"manufacturer": "SUZUKI", "campaign_name": "虛構活動", "recipient": "customer", "kind": "cash",
                   "amount": "500", **data}
        return self.client.post(reverse("manufacturer_advance_create", args=[order.pk]), payload, **XHR)

    def test_order_form_is_a_brand_select_with_vehicle_master_options(self):
        order = self.make_order()
        page = self.order_page(order)
        self.assertIn(f'<select id="advance-manufacturer-{order.pk}" name="manufacturer" required>', page)
        self.assertNotIn(f'list="advance-manufacturers-{order.pk}"', page)
        self.assertNotIn("虛構停用品牌", page)
        self.assertEqual(advances.manufacturer_choices(order), _brand_choices("SUZUKI")[1:])
        self.assertIn('<option value="SUZUKI" selected>', page)
        self.assertIn('<option value="SYM">', page)

    def test_default_follows_vehicle_brand_case_insensitively(self):
        order = self.make_order(vehicle_model=self.lower_model, color=self.lower_color)
        self.assertEqual(advances.default_manufacturer(order), "SUZUKI")
        self.assertIn('<option value="SUZUKI" selected>', self.order_page(order))

    def test_vehicle_brand_missing_from_list_is_still_offered_and_saves(self):
        order = self.make_order(vehicle_model=self.legacy_model, color=self.legacy_color)
        self.assertIn(f'<option value="{LEGACY}" selected>', self.order_page(order))
        response = self.create(order, manufacturer=LEGACY)
        self.assertEqual(response.status_code, 200, response.content.decode())
        self.assertEqual(ManufacturerAdvance.objects.get(order=order).manufacturer, LEGACY)

    def test_free_text_and_blank_are_rejected(self):
        order = self.make_order()
        for value in ("隨便打的原廠", LEGACY, ""):
            response = self.create(order, manufacturer=value)
            self.assertEqual(response.status_code, 400, value)
            self.assertIn("manufacturer", response.json()["errors"])
        self.assertFalse(ManufacturerAdvance.objects.exists())
        self.assertEqual(self.create(order, manufacturer="SYM").status_code, 200)

    def test_existing_item_with_unlisted_manufacturer_still_shows_and_ticks(self):
        order = self.make_order()
        item = ManufacturerAdvance.objects.create(order=order, manufacturer=LEGACY, campaign_name="虛構舊活動",
                                                  amount=Decimal("300"))
        self.assertIn(f"<span>{LEGACY}</span>", self.order_page(order))
        response = self.client.post(reverse("manufacturer_advance_toggle", args=[item.pk]), {"flag": "reimbursed", "value": "1"}, **XHR)
        self.assertEqual(response.status_code, 200, response.content.decode())
        item.refresh_from_db()
        self.assertEqual((item.manufacturer, item.reimbursed), (LEGACY, True))


class CampaignFormBrandSelectTests(CampaignTestBase):
    def test_campaign_form_uses_same_brand_list_and_rejects_free_text(self):
        page = self.client.get(reverse("manufacturer_advance_campaign_create")).content.decode()
        self.assertIn('<select name="manufacturer"', page)
        for value, _label in _brand_choices()[1:]:
            self.assertIn(f'<option value="{value}"', page)
        response = self.client.post(reverse("manufacturer_advance_campaign_create"), self.campaign_payload(manufacturer="隨便打的原廠"))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(ManufacturerAdvanceCampaign.objects.exists())

    def test_legacy_campaign_manufacturer_shows_and_saves(self):
        campaign = ManufacturerAdvanceCampaign.objects.create(name="虛構舊活動", manufacturer=LEGACY, effective_from=date(2026, 10, 1),
                                                              amount=Decimal("100"))
        page = self.client.get(reverse("manufacturer_advance_campaign_edit", args=[campaign.pk])).content.decode()
        self.assertIn(f'<option value="{LEGACY}" selected>', page)
        self.edit_campaign(campaign, name="虛構舊活動", manufacturer=LEGACY)
        self.assertEqual(campaign.manufacturer, LEGACY)


class AutoAttachMatchingUnchangedTests(CampaignTestBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.lower_model = VehicleModel.objects.create(brand="suzuki", name="虛構車型丁", energy_type="gas")
        cls.lower_color = VehicleColor.objects.create(vehicle_model=cls.lower_model, name="藍")

    def test_brand_picked_from_select_matches_by_vehicle_brand_and_models(self):
        same = self.register(self.make_order(), date(2026, 10, 5))
        lower = self.register(self.make_order(vehicle_model=self.lower_model, color=self.lower_color), date(2026, 10, 5))
        other = self.register(self.make_order(vehicle_model=self.other_model, color=self.other_color), date(2026, 10, 5))
        self.create_campaign()
        # 原廠比對不分大小寫：車型品牌寫 suzuki 的單一樣掛上；別的原廠不掛。
        self.assertEqual(len(self.auto_items(same)), 1)
        self.assertEqual(len(self.auto_items(lower)), 1)
        self.assertEqual(self.auto_items(other), [])
        # 訂單頁的預設原廠就是活動比對用的那個品牌。
        self.assertEqual(advances.default_manufacturer(lower), self.auto_items(lower)[0].manufacturer)
        # 限定車型：只掛清單裡的車型。
        sibling = self.register(self.make_order(vehicle_model=self.sibling_model, color=self.sibling_color), date(2026, 10, 6))
        self.create_campaign(name="虛構限定車型", vehicle_models=[self.model.pk])
        self.assertEqual({item.campaign_name for item in self.auto_items(same)}, {"虛構領牌加碼回饋", "虛構限定車型"})
        self.assertEqual({item.campaign_name for item in self.auto_items(sibling)}, {"虛構領牌加碼回饋"})
