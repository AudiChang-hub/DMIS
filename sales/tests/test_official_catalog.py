import io
import tempfile
from unittest.mock import patch

from PIL import Image
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.test import TestCase, SimpleTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from sales.models import (
    OfficialCatalogCheck,
    OfficialCatalogModel,
    UserAccountAuditLog,
    VehicleColor,
    VehicleModel,
    VehiclePriceVersion,
)
from sales.services import official_catalog as service

# 測試網頁依官網版型自行撰寫，只保留解析會用到的結構。
SYM_LIST = """
<h3>125cc~150cc以下</h3>
<div class="product__thumb"><a class="first__img" href="https://tw.sym-global.com/jetsl125"><img data-src="/storage/jetsl/AM526.webp" alt="類別"></a>
<div class="product__content"><h4><a> JET SL </a></h4></div></div>
<div class="product__thumb"><a class="first__img" href="https://tw.sym-global.com/4mica125"><img data-src="/storage/4mica/AM855.webp" alt="類別"></a>
<div class="product__content"><h4><a> 4MICA 125 </a></h4></div></div>
<h3>電動車</h3>
<div class="product__thumb"><a class="first__img" href="https://tw.sym-global.com/e-woo"><img data-src="/storage/ewoo/G326.webp" alt="類別"></a>
<div class="product__content"><h4><a> E-Woo </a></h4></div></div>
<a href="https://tw.sym-global.com/about">關於</a>
"""

SYM_TWO_VARIANTS = """
<div class="butline"><a class="stay">ABS</a><a>標準</a></div>
<div class="colorposition" id="colorposition"><div class="colorarea">
<div class="colorchose stay"><ul><li><div class="pic"><img src='/s/wp.webp' alt="x"></div><div class="text"> 珍珠白-白/銀 AM855 </div></li>
<li><div class="pic"><img src='/s/gb.webp' alt="x"></div><div class="text"> 消光灰-灰(消光)/黑 AM856 </div></li></ul></div>
<div class="colorchose "><ul><li><div class="pic"><img src='/s/bp.webp' alt="x"></div><div class="text"> 天空藍-藍/白 AM850 </div></li></ul></div>
</div></div>
<div class="motobike"><div class="motoslide">
<div class="picgroup stay"><div class="x"><img src="/s/125/AM855.webp" alt="2026 4MICA"><div class="angle360"></div></div><div class="x"><img src="/s/125/AM856.webp" alt="2026 4MICA"></div></div>
<div class="picgroup"><div class="x"><img src="/s/125/AM850.webp" alt="2026 4MICA"></div></div>
</div><div class="colorposition" id="mobile_colorposition"><div class="text"> 不應重複讀取 AM999 </div></div></div>
<div class="typeabscba"><div>2026 4MICA 125 ABS</div><div>2026 4MICA 125 標準</div></div><div id="changtp-next"></div>
<div class="formtable"><div class="onef"><div class="row"><div><div><span>排氣量</span> 124.6 CC </div></div><div><div><span>最大馬力</span> 7.1KW/7000rpm(9.6ps) </div></div></div></div>
<div class="onef"><div class="row"><div><div><span>排氣量</span> 124.6 CC </div></div></div></div></div>
<footer></footer>
"""

SUZUKI_LIST = """
<li><div><figure><img src="images/product/sui_125/b61_angle_01.jpg"></figure>
<h5 style="padding-bottom:10px;">SUI 125</h5><a href="product/sui_125/intro.html" class="btn">了解</a></div></li>
<!-- <li><div><figure><img src="images/product/address-110/a.jpg"></figure>
<h5>Address 110</h5><a href="product/address-110/intro.html">了解</a></div></li> -->
<li><div><figure><img src="images/product/gsx-8r/ysf_angle_01.jpg"></figure>
<h5 style="padding-bottom:10px;">GSX-8R<br/></h5> <a href="product/gsx-8r/intro.html" target="_self">了解</a></div></li>
<li><div><figure><img src="images/ready.jpg"></figure><h5>eReady</h5><a href="https://www.eready.com.tw/">了解</a></div></li>
"""

SUZUKI_MODEL = """
<img src="../../images/product/sui_125/kv_sui-125.jpg" class="block">
<div id="color"><div class="color-slide"><div class="cycle-slideshow" data-x="1">
<img src="../../images/product/sui_125/b61_angle_04.jpg" alt="蘇打藍 (B61)" >
<!-- 2026-09-14 下架 <img src="../../images/product/sui_125/q08_angle_04.jpg" alt="泰奶紅 (Q08)" > -->
<img src="../../images/product/sui_125/w17_angle_04.jpg" alt="白 (W17) 26年式" >
</div></div>
<div class="color-pager"><img src="../../images/product/sui_125/color_b61.jpg"></div>
<p><strong class="price">NT.163,000元</strong> (不含牌險)</p>
</div>
<div id="spec"><table>
<tr><td colspan="2">排氣量</td><td>124 C.C.</td></tr>
<tr><td colspan="2">最大馬力</td><td>8.8PS / 7000 rpm</td></tr>
<tr><td rowspan="2">輪胎尺寸</td><td>(F)</td><td>100/90-10</td></tr>
<tr><td>(R)</td><td>100/90-10</td></tr>
</table></div>
<footer></footer>
"""


def png_file():
    data = io.BytesIO()
    Image.new("RGB", (8, 8), "white").save(data, "PNG")
    return ContentFile(data.getvalue(), name="official.png")


class OfficialCatalogParserTests(SimpleTestCase):
    def test_sym_list_keeps_product_cards_and_category(self):
        entries = service.parse_sym_list(SYM_LIST, "https://tw.sym-global.com/product")
        self.assertEqual([entry["slug"] for entry in entries], ["jetsl125", "4mica125", "e-woo"])
        self.assertEqual(entries[2]["category"], "電動車")
        self.assertEqual(entries[0]["image_url"], "https://tw.sym-global.com/storage/jetsl/AM526.webp")

    def test_sym_model_splits_variants_and_pairs_colors_with_images(self):
        listing = {"slug": "4mica125", "url": "https://tw.sym-global.com/4mica125", "name": "4MICA 125", "category": "125cc"}
        abs_entry, standard = service.parse_sym_model(SYM_TWO_VARIANTS, listing)
        self.assertEqual((abs_entry["source_key"], abs_entry["name"], abs_entry["year_hint"]), ("4mica125#1", "2026 4MICA 125 ABS", 2026))
        self.assertEqual([(c["stem"], c["code"]) for c in abs_entry["colors"]], [("珍珠白", "AM855"), ("消光灰", "AM856")])
        self.assertEqual(abs_entry["colors"][1]["image_url"], "https://tw.sym-global.com/s/125/AM856.webp")
        self.assertEqual((abs_entry["displacement_cc"], abs_entry["power"]), ("124.6", "7.1KW/7000rpm(9.6ps)"))
        self.assertEqual([c["code"] for c in standard["colors"]], ["AM850"])
        self.assertEqual(standard["variant"], "標準")

    def test_sym_model_rejects_color_image_count_mismatch(self):
        listing = {"slug": "x", "url": "https://tw.sym-global.com/x", "name": "X"}
        broken = SYM_TWO_VARIANTS.replace('<div class="x"><img src="/s/125/AM856.webp" alt="2026 4MICA"></div>', "")
        with self.assertRaises(service.OfficialCatalogError):
            service.parse_sym_model(broken, listing)

    def test_suzuki_list_skips_commented_and_external_cards(self):
        entries = service.parse_suzuki_list(SUZUKI_LIST, "https://www.suzukimotor.com.tw/products.html")
        self.assertEqual([(e["slug"], e["name"]) for e in entries], [("sui_125", "SUI 125"), ("gsx-8r", "GSX-8R")])
        self.assertEqual(entries[0]["url"], "https://www.suzukimotor.com.tw/product/sui_125/style_price.html")

    def test_suzuki_model_skips_commented_colors_and_reads_price(self):
        listing = {"slug": "sui_125", "url": "https://www.suzukimotor.com.tw/product/sui_125/style_price.html", "name": "SUI 125"}
        (entry,) = service.parse_suzuki_model(SUZUKI_MODEL, listing)
        self.assertEqual([(c["stem"], c["code"]) for c in entry["colors"]], [("蘇打藍", "B61"), ("白", "W17")])
        self.assertEqual(entry["colors"][0]["image_url"], "https://www.suzukimotor.com.tw/images/product/sui_125/b61_angle_04.jpg")
        self.assertEqual((entry["price"], entry["price_note"], entry["year_hint"]), (163000, "不含牌險", 2026))
        self.assertEqual(entry["displacement_cc"], "124")
        self.assertNotIn("(R)", entry["specs"])

    def test_suzuki_commented_price_is_not_read(self):
        listing = {"slug": "sui_125", "url": "https://www.suzukimotor.com.tw/product/sui_125/style_price.html", "name": "SUI 125"}
        hidden = SUZUKI_MODEL.replace('<p><strong class="price">NT.163,000元</strong> (不含牌險)</p>', "<!-- <p>NT.163,000元</p> -->")
        self.assertIsNone(service.parse_suzuki_model(hidden, listing)[0]["price"])

    def test_color_matching_requires_unique_pairs(self):
        class Color:
            def __init__(self, pk, name):
                self.pk, self.name = pk, name
        official = [
            {"name": "珍珠白-白/銀 AM855", "code": "AM855", "stem": "珍珠白", "image_url": "a"},
            {"name": "白 (QU2)", "code": "QU2", "stem": "白", "image_url": "b"},
            {"name": "白（彩繪版）", "code": "", "stem": "白", "image_url": "c"},
        ]
        matches = service.match_colors(official, [Color(1, "珍珠白"), Color(2, "白"), Color(3, "黑 AM855")])
        self.assertEqual(matches, {})  # 珍珠白與「黑 AM855」搶同一官網色、「白」對到兩色，皆不猜
        matches = service.match_colors(official, [Color(1, "珍珠白"), Color(4, "白 QU2")])
        self.assertEqual({pk: color["image_url"] for pk, color in matches.items()}, {1: "a", 4: "b"})

    def test_suggestion_skips_same_name_with_other_displacement(self):
        class Model:
            def __init__(self, pk, name, cc, year=2026):
                self.pk, self.name, self.displacement_cc, self.model_year = pk, name, cc, year
        entry = {"name": "2026- 全新 JET SL+ TCS版", "displacement_cc": "158.0"}
        self.assertEqual(service.suggest_vehicle_models(entry, [Model(1, "JET SL", 125)]), [])
        entry = {"name": "2026-全新JET SL", "displacement_cc": "124.6"}
        self.assertEqual([m.pk for m in service.suggest_vehicle_models(entry, [Model(1, "JET SL", 125), Model(2, "JET SL", 125, 2027)])], [2, 1])

    def test_fetch_rejects_other_hosts_without_network(self):
        with self.assertRaises(service.OfficialCatalogError):
            service.fetch_image("https://evil.example.com/a.jpg", service.SOURCES["sym"]["hosts"])
        with self.assertRaises(service.OfficialCatalogError):
            service.fetch_page("http://tw.sym-global.com/product", service.SOURCES["sym"]["hosts"])


class OfficialCatalogCheckJobTests(TestCase):
    def pages(self, pages):
        def fake(url, hosts):
            value = pages[url]
            if isinstance(value, Exception):
                raise value
            return value
        return patch.object(service, "fetch_page", side_effect=fake)

    def run_check(self, brand, pages):
        check = OfficialCatalogCheck.objects.create(brand=brand)
        with self.pages(pages), patch.object(service, "REQUEST_DELAY", 0):
            service.run_official_catalog_check(check.pk)
        check.refresh_from_db()
        return check

    def test_check_records_entries_errors_and_missing(self):
        old = OfficialCatalogModel.objects.create(brand="sym", source_key="retired", source_url="https://tw.sym-global.com/retired",
                                                  name="舊車", data={}, content_hash="x")
        failed_before = OfficialCatalogModel.objects.create(brand="sym", source_key="e-woo", source_url="https://tw.sym-global.com/e-woo",
                                                            name="E-Woo", data={}, content_hash="y")
        check = self.run_check("sym", {
            "https://tw.sym-global.com/product": SYM_LIST,
            "https://tw.sym-global.com/jetsl125": SYM_TWO_VARIANTS,
            "https://tw.sym-global.com/4mica125": SYM_TWO_VARIANTS,
            "https://tw.sym-global.com/e-woo": service.OfficialCatalogError("官網回應 500。"),
        })
        self.assertEqual((check.status, check.pages_total, check.pages_done, check.entries_found, check.error_count), ("succeeded", 3, 3, 4, 1))
        self.assertIn("E-Woo：官網回應 500。", check.errors)
        self.assertTrue(OfficialCatalogModel.objects.filter(source_key="4mica125#2").exists())
        old.refresh_from_db(), failed_before.refresh_from_db()
        self.assertTrue(old.missing)
        self.assertFalse(failed_before.missing)  # 讀取失敗的頁面不判定下架

    def test_list_failure_writes_nothing(self):
        check = self.run_check("suzuki", {"https://www.suzukimotor.com.tw/products.html": "<html>改版</html>"})
        self.assertEqual(check.status, "failed")
        self.assertFalse(OfficialCatalogModel.objects.exists())

    def test_rerun_detects_changes_against_acknowledged_content(self):
        pages = {"https://www.suzukimotor.com.tw/products.html": SUZUKI_LIST,
                 "https://www.suzukimotor.com.tw/product/sui_125/style_price.html": SUZUKI_MODEL,
                 "https://www.suzukimotor.com.tw/product/gsx-8r/style_price.html": SUZUKI_MODEL.replace("sui_125", "gsx-8r")}
        self.run_check("suzuki", pages)
        link = OfficialCatalogModel.objects.get(source_key="sui_125")
        link.vehicle_model = VehicleModel.objects.create(brand="SUZUKI", name="SUI 125", energy_type="gas", displacement_cc=124)
        link.acknowledged_data, link.acknowledged_hash = link.data, link.content_hash
        link.save()
        self.run_check("suzuki", pages)
        link.refresh_from_db()
        self.assertFalse(link.has_changes)
        pages["https://www.suzukimotor.com.tw/product/sui_125/style_price.html"] = SUZUKI_MODEL.replace("163,000", "165,000")
        self.run_check("suzuki", pages)
        link.refresh_from_db()
        self.assertTrue(link.has_changes)
        self.assertIn("建議售價：163000 → 165000", service.describe_changes(link.acknowledged_data, link.data))


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class OfficialCatalogViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.root = get_user_model().objects.create_superuser("admin", password="Official-catalog-test-51!")
        cls.staff = get_user_model().objects.create_user("clerk", password="Official-catalog-test-52!")
        cls.model = VehicleModel.objects.create(brand="SUZUKI", name="SUI 125", model_number="UQ125", model_year=2026,
                                                energy_type="gas", displacement_cc=124)
        cls.blue = VehicleColor.objects.create(vehicle_model=cls.model, name="蘇打藍")
        cls.white = VehicleColor.objects.create(vehicle_model=cls.model, name="白")
        cls.other_brand = VehicleModel.objects.create(brand="SYM", name="SUI 125", energy_type="gas", displacement_cc=125)
        listing = {"slug": "sui_125", "url": "https://www.suzukimotor.com.tw/product/sui_125/style_price.html", "name": "SUI 125"}
        (entry,) = service.parse_suzuki_model(SUZUKI_MODEL, listing)
        cls.link = OfficialCatalogModel.objects.create(brand="suzuki", source_key="sui_125", source_url=listing["url"], name="SUI 125",
                                                       data=entry, content_hash=service.content_hash(entry))
        VehiclePriceVersion.objects.create(vehicle_model=cls.model, suggested_price=160000, effective_from=timezone.localdate())

    def setUp(self):
        self.client.force_login(self.root)
        self.url = reverse("official_catalog")

    def test_only_root_can_open_or_post(self):
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.client.post(reverse("official_catalog_link", args=[self.link.pk]), {"vehicle_model": self.model.pk}).status_code, 403)

    def test_pending_suggests_same_brand_model(self):
        response = self.client.get(self.url, {"brand": "suzuki"})
        self.assertEqual(response.status_code, 200)
        (row,) = response.context["rows"]
        self.assertEqual(row["suggested"], self.model.pk)
        self.assertNotIn(self.other_brand, response.context["candidates"])

    def test_link_rejects_other_brand_and_duplicate(self):
        post = reverse("official_catalog_link", args=[self.link.pk])
        self.client.post(post, {"vehicle_model": self.other_brand.pk})
        self.link.refresh_from_db()
        self.assertIsNone(self.link.vehicle_model)
        self.client.post(post, {"vehicle_model": self.model.pk})
        self.link.refresh_from_db()
        self.assertEqual((self.link.vehicle_model, self.link.acknowledged_hash), (self.model, self.link.content_hash))
        second = OfficialCatalogModel.objects.create(brand="suzuki", source_key="dup", source_url=self.link.source_url,
                                                     name="重複", data={}, content_hash="z")
        response = self.client.post(reverse("official_catalog_link", args=[second.pk]), {"vehicle_model": self.model.pk}, follow=True)
        self.assertContains(response, "已對應其他官網車型")

    def test_fill_images_only_blank_colors_without_touching_master_data(self):
        self.link.vehicle_model = self.model
        self.link.save()
        self.white.catalog_image.save("keep.png", png_file())
        before = VehicleModel.objects.filter(pk=self.model.pk).values().get()
        response = self.client.get(self.url, {"brand": "suzuki", "tab": "images"})
        (row,) = response.context["rows"]
        self.assertEqual([color.pk for color, _ in row["fillable"]], [self.blue.pk])
        with patch.object(service, "fetch_image", side_effect=lambda url, hosts: png_file()) as fetch:
            self.client.post(reverse("official_catalog_fill_images", args=[self.link.pk]),
                             {"color": [self.blue.pk, self.white.pk], "tab": "images"})
        fetch.assert_called_once_with("https://www.suzukimotor.com.tw/images/product/sui_125/b61_angle_04.jpg",
                                      service.SOURCES["suzuki"]["hosts"])
        self.blue.refresh_from_db(), self.white.refresh_from_db()
        self.assertTrue(self.blue.catalog_image.name)
        self.assertIn("keep", self.white.catalog_image.name)
        after = VehicleModel.objects.filter(pk=self.model.pk).values().get()
        self.assertEqual({k: v for k, v in before.items() if k != "updated_at"}, {k: v for k, v in after.items() if k != "updated_at"})
        self.assertEqual(VehiclePriceVersion.objects.filter(vehicle_model=self.model).count(), 1)
        self.assertTrue(UserAccountAuditLog.objects.filter(description__contains="從原廠官網補上車色圖片").exists())

    def test_linked_row_shows_price_difference(self):
        self.link.vehicle_model = self.model
        self.link.save()
        response = self.client.get(self.url, {"brand": "suzuki", "tab": "linked"})
        self.assertTrue(response.context["rows"][0]["price"]["differs"])
        self.assertContains(response, "價格不同")

    def test_acknowledge_requires_current_hash(self):
        OfficialCatalogModel.objects.filter(pk=self.link.pk).update(vehicle_model=self.model, acknowledged_hash="old")
        post = reverse("official_catalog_acknowledge", args=[self.link.pk])
        self.client.post(post, {"content_hash": "stale"})
        self.link.refresh_from_db()
        self.assertTrue(self.link.has_changes)
        self.client.post(post, {"content_hash": self.link.content_hash})
        self.link.refresh_from_db()
        self.assertFalse(self.link.has_changes)

    def test_ignore_and_restore(self):
        post = reverse("official_catalog_ignore", args=[self.link.pk])
        self.client.post(post)
        self.assertEqual(self.client.get(self.url, {"brand": "suzuki", "tab": "ignored"}).context["rows"][0]["link"], self.link)
        self.client.post(post, {"action": "restore"})
        self.assertEqual(len(self.client.get(self.url, {"brand": "suzuki"}).context["rows"]), 1)

    def test_start_check_enqueues_once(self):
        with patch("sales.official_catalog_views.django_rq.get_queue") as get_queue:
            self.client.post(reverse("official_catalog_check_start"), {"brand": "sym"})
            self.client.post(reverse("official_catalog_check_start"), {"brand": "sym"})
        self.assertEqual(get_queue.return_value.enqueue.call_count, 1)
        self.assertEqual(OfficialCatalogCheck.objects.filter(brand="sym").count(), 1)

    def test_start_check_marks_failed_when_queue_unavailable(self):
        with patch("sales.official_catalog_views.django_rq.get_queue", side_effect=RuntimeError):
            response = self.client.post(reverse("official_catalog_check_start"), {"brand": "suzuki"}, follow=True)
        self.assertEqual(OfficialCatalogCheck.objects.get(brand="suzuki").status, "failed")
        self.assertContains(response, "上次檢查失敗")


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class OfficialCatalogCreateModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.root = get_user_model().objects.create_superuser("admin", password="Official-create-test-61!")
        cls.old = VehicleModel.objects.create(brand="SUZUKI", name="SUI 125", model_number="UQ125", model_year=2025,
                                              model_code=VehicleModel.ModelType.FRONT_DISC_REAR_DRUM,
                                              energy_type="gas", displacement_cc=124)
        VehicleColor.objects.create(vehicle_model=cls.old, name="蘇打藍")
        listing = {"slug": "sui_125", "url": "https://www.suzukimotor.com.tw/product/sui_125/style_price.html", "name": "SUI 125"}
        (entry,) = service.parse_suzuki_model(SUZUKI_MODEL, listing)
        cls.entry = entry

    def setUp(self):
        self.client.force_login(self.root)
        self.link = OfficialCatalogModel.objects.create(brand="suzuki", source_key="sui_125", source_url=self.entry["source_url"],
                                                        name="SUI 125", data=self.entry, content_hash=service.content_hash(self.entry))

    def payload(self, **overrides):
        data = {
            "brand": "SUZUKI", "energy_type": "gas", "name": "SUI 125", "model_number": "UQ125B", "model_year": "2026",
            "model_code": VehicleModel.ModelType.FRONT_DISC_REAR_DRUM, "displacement_cc": "124", "active": "on",
            "colors-TOTAL_FORMS": "2", "colors-INITIAL_FORMS": "0", "colors-MIN_NUM_FORMS": "0", "colors-MAX_NUM_FORMS": "1000",
            "colors-0-name": "蘇打藍", "colors-0-active": "on", "colors-1-name": "白", "colors-1-active": "on",
            "official": str(self.link.pk),
        }
        data.update(overrides)
        return data

    def test_prefill_from_official_entry(self):
        response = self.client.get(reverse("vehicle_model_create"), {"official": self.link.pk})
        form, colors = response.context["form"], response.context["color_formset"]
        self.assertEqual((form.initial["name"], form.initial["model_year"], form.initial["displacement_cc"], form.initial["active"]),
                         ("SUI 125", 2026, 124, False))
        self.assertEqual([f.initial.get("name") for f in colors.forms], ["蘇打藍", "白"])
        self.assertContains(response, "從官網建立車型")

    def test_new_model_is_inactive_and_linked(self):
        response = self.client.post(reverse("vehicle_model_create"), self.payload())
        created = VehicleModel.objects.get(model_number="UQ125B")
        self.assertRedirects(response, f"{reverse('official_catalog')}?brand=suzuki&tab=images", fetch_redirect_response=False)
        self.assertFalse(created.active)
        self.link.refresh_from_db()
        self.assertEqual((self.link.vehicle_model, self.link.acknowledged_hash), (created, self.link.content_hash))
        self.assertTrue(UserAccountAuditLog.objects.filter(description__contains="從原廠官網建立車型").exists())

    def test_new_year_keeps_old_year_and_moves_link(self):
        self.link.vehicle_model = self.old
        self.link.save()
        page = self.client.get(reverse("vehicle_model_create"), {"official": self.link.pk, "base": self.old.pk})
        self.assertEqual(page.context["form"].initial["existing_family"], self.old.family_id)
        before = VehicleModel.objects.filter(pk=self.old.pk).values().get()
        self.client.post(reverse("vehicle_model_create"), self.payload(
            existing_family=str(self.old.family_id), base=str(self.old.pk)))
        created = VehicleModel.objects.get(model_year=2026)
        self.assertEqual((created.family_id, created.active), (self.old.family_id, False))
        self.link.refresh_from_db()
        self.assertEqual(self.link.vehicle_model, created)
        self.assertEqual(VehicleModel.objects.filter(pk=self.old.pk).values().get(), before)
        self.assertEqual(list(self.old.colors.values_list("name", flat=True)), ["蘇打藍"])

    def test_stale_or_unauthorized_official_is_not_used(self):
        self.link.vehicle_model = self.old
        self.link.save()
        response = self.client.post(reverse("vehicle_model_create"), self.payload())
        self.assertRedirects(response, reverse("official_catalog"), fetch_redirect_response=False)
        self.assertFalse(VehicleModel.objects.filter(model_number="UQ125B").exists())
        staff = get_user_model().objects.create_user("clerk", password="Official-create-test-62!", is_staff=True)
        self.client.force_login(staff)
        response = self.client.get(reverse("vehicle_model_create"), {"official": self.link.pk})
        if response.status_code == 200:
            self.assertIsNone(response.context["official"])
