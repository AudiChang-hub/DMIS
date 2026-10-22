"""車輛庫存：表頭排序、複選下拉三態全選、已選摘要不堆在欄位底下（使用者 2026-10-22 投影片 T-66）。"""
import re
from datetime import date
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from sales.models import Store, VehicleColor, VehicleInventory, VehicleModel

CSS = Path("static/css/app.css").read_text(encoding="utf-8")
SCRIPT = Path("static/js/searchable-select.js").read_text(encoding="utf-8")


class InventorySortHeaderTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="sorter", password="test-pass-123")
        store = Store.objects.create(name="總店", code="HQ")
        self.vehicles = {}
        for brand, name, received in (("Alpha", "A 車", date(2026, 3, 1)), ("Beta", "B 車", date(2026, 1, 1)), ("Gamma", "C 車", date(2026, 2, 1))):
            model = VehicleModel.objects.create(brand=brand, name=name, energy_type=VehicleModel.EnergyType.GAS)
            color = VehicleColor.objects.create(vehicle_model=model, name="白")
            self.vehicles[brand] = VehicleInventory.objects.create(
                vehicle_model=model, color=color, engine_number=f"ENG-{brand}",
                ownership_store=store, location_store=store, received_on=received,
            )
        self.client.force_login(self.user)

    def brands(self, response):
        return [vehicle.vehicle_model.brand for vehicle in response.context["vehicles"]]

    def test_sort_dropdown_removed_and_sort_kept_as_hidden_field(self):
        response = self.client.get(reverse("inventory_list"), {"sort": "brand"})

        self.assertNotContains(response, 'id="inventory-sort"')
        self.assertNotContains(response, "進車日期：新到舊")
        self.assertContains(response, '<input type="hidden" name="sort" value="brand">', html=True)

    def test_default_sort_is_received_newest_first_and_marked_on_header(self):
        response = self.client.get(reverse("inventory_list"))

        self.assertEqual(self.brands(response), ["Alpha", "Gamma", "Beta"])
        html = response.content.decode()
        received = re.search(r'<th scope="col" aria-sort="descending"><a class="inventory-sort-link is-active" href="([^"]+)"[^>]*>進車日期', html)
        self.assertIsNotNone(received)
        self.assertIn("sort=received_asc", received.group(1))
        self.assertEqual(html.count('aria-sort="descending"'), 1)

    def test_clicking_active_text_column_reverses_and_keeps_filters(self):
        response = self.client.get(reverse("inventory_list"), {"sort": "brand", "brand": ["Alpha", "Gamma"], "q": "ENG"})

        self.assertEqual(self.brands(response), ["Alpha", "Gamma"])
        header = response.context["sort_headers"]["brand"]
        self.assertEqual(header["direction"], "ascending")
        self.assertIn("sort=brand_desc", header["url"])
        self.assertIn("brand=Alpha", header["url"])
        self.assertIn("brand=Gamma", header["url"])
        self.assertIn("q=ENG", header["url"])

        reversed_response = self.client.get(reverse("inventory_list"), {"sort": "brand_desc", "brand": ["Alpha", "Gamma"]})
        self.assertEqual(self.brands(reversed_response), ["Gamma", "Alpha"])
        header = reversed_response.context["sort_headers"]["brand"]
        self.assertEqual(header["direction"], "descending")
        self.assertIn("sort=brand", header["url"])
        self.assertNotIn("brand_desc", header["url"])

    def test_page_number_is_dropped_from_header_links(self):
        response = self.client.get(reverse("inventory_list"), {"page": "2", "sort": "model"})

        self.assertNotIn("page=", response.context["sort_headers"]["model"]["url"])

    def test_old_sort_keys_still_work(self):
        expected = {
            "received_asc": ["Beta", "Gamma", "Alpha"],
            "received_desc": ["Alpha", "Gamma", "Beta"],
            "model": ["Alpha", "Beta", "Gamma"],
            "identifier": ["Alpha", "Beta", "Gamma"],
            "not-a-key": ["Alpha", "Gamma", "Beta"],
        }
        for sort, brands in expected.items():
            with self.subTest(sort=sort):
                response = self.client.get(reverse("inventory_list"), {"sort": sort})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(self.brands(response), brands)
        for sort in ("priority", "status", "location", "color", "brand"):
            with self.subTest(sort=sort):
                self.assertEqual(self.client.get(reverse("inventory_list"), {"sort": sort}).status_code, 200)

    def test_priority_header_is_single_direction(self):
        response = self.client.get(reverse("inventory_list"), {"sort": "priority"})

        header = response.context["sort_headers"]["priority"]
        self.assertEqual(header["direction"], "descending")
        self.assertIn("sort=received_desc", header["url"])

    def test_model_and_color_share_one_header_cell(self):
        response = self.client.get(reverse("inventory_list"), {"sort": "color_desc"})

        html = response.content.decode()
        self.assertRegex(html, r'<th scope="col" aria-sort="descending"><span class="inventory-sort-pair"><a class="inventory-sort-link" href="[^"]*sort=model"')
        self.assertIn("sort=color", response.context["sort_headers"]["color"]["url"])

    def test_sold_scope_has_no_location_header_link(self):
        response = self.client.get(reverse("inventory_list"), {"scope": "sold"})

        html = response.content.decode()
        self.assertIn('<th scope="col">去向</th>', html)
        self.assertNotIn("sort=location", html)
        self.assertNotIn("sort=priority", html)

    def test_mobile_sort_bar_lists_the_same_links(self):
        response = self.client.get(reverse("inventory_list"))

        bar = re.search(r'<nav class="inventory-sort-bar" aria-label="排序方式">(.*?)</nav>', response.content.decode(), re.S)
        self.assertIsNotNone(bar)
        self.assertEqual(bar.group(1).count('<a class="inventory-sort-link'), 8)

    def test_multi_select_filters_have_no_all_option(self):
        response = self.client.get(reverse("inventory_list"))

        html = response.content.decode()
        for label in ("全部品牌", "全部機種", "全部車色", "全部位置"):
            self.assertNotIn(label, html)
        for tag in re.findall(r"<select[^>]*multiple[^>]*>", html):
            self.assertNotIn("data-searchable-include-empty", tag)
            self.assertNotIn("data-searchable-empty-placeholder", tag)


class SearchableMultiSelectScriptTests(SimpleTestCase):
    def test_select_matches_is_tri_state_checkbox(self):
        self.assertIn('selectMatches.setAttribute("role", "checkbox")', SCRIPT)
        self.assertIn('allChecked ? "true" : (checkedCount ? "mixed" : "false")', SCRIPT)
        self.assertIn("option.selected = !allChecked;", SCRIPT)
        self.assertIn('clear.textContent = "清除此欄"', SCRIPT)
        self.assertIn('.searchable-select__bulk-toggle[aria-checked="mixed"]::before', CSS)

    def test_selected_items_summarised_in_box_not_chips(self):
        self.assertNotIn("searchable-select__chip", SCRIPT)
        self.assertNotIn(".searchable-select__chip", CSS)
        self.assertIn('input.placeholder = labels.length ? labels.join("、") : basePlaceholder;', SCRIPT)
        self.assertIn("if (isMultiple && label) label.append(count);", SCRIPT)
        self.assertIn(".searchable-select.has-selection .searchable-select__input::placeholder", CSS)

    def test_inventory_filter_layout_and_sort_styles(self):
        self.assertIn("grid-template-columns: minmax(200px, 1.3fr) repeat(auto-fit, minmax(164px, 1fr));", CSS)
        self.assertIn(".inventory-filters.inventory-filters--stock { grid-template-columns: minmax(0, 1fr) auto;", CSS)
        self.assertNotIn("inventory-filter--sort", CSS)
        self.assertIn(".inventory-sort-bar { display: none; }", CSS)
        self.assertIn(".inventory-table--stock :is(th, td) { padding-inline: var(--space-3); }", CSS)
        self.assertNotIn("\x00", CSS)
