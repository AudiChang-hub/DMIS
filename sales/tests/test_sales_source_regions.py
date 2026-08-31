from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from sales.forms import SalesSourceForm
from sales.models import SalesSource, SalesSourceCategory
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

    def test_form_infers_region_when_only_address_is_entered(self):
        category = SalesSourceCategory.objects.get(
            system_behavior=SalesSource.SourceType.DEALER,
        )
        form = SalesSourceForm(
            data={
                "category": category.pk,
                "name": "地址自動辨識車行",
                "address": "基隆市中正區正濱里中正路718號",
                "city": "",
                "district": "",
                "line_group_presence": "no",
                "active": "on",
            },
            source_type=SalesSource.SourceType.DEALER,
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["city"], "基隆市")
        self.assertEqual(form.cleaned_data["district"], "中正區")

    def test_district_select_only_contains_selected_city_districts(self):
        source = SalesSource(
            name="基隆區域選單車行",
            source_type=SalesSource.SourceType.DEALER,
            city="基隆市",
            district="中正區",
        )
        form = SalesSourceForm(
            instance=source,
            source_type=SalesSource.SourceType.DEALER,
        )
        choices = dict(form.fields["district"].widget.choices)

        self.assertIn("中正區", choices)
        self.assertIn("七堵區", choices)
        self.assertNotIn("汐止區", choices)

    def test_edit_page_contains_address_region_linkage(self):
        user = get_user_model().objects.create_user(
            username="region-form-user",
            password="pass12345",
        )
        category = SalesSourceCategory.objects.get(
            system_behavior=SalesSource.SourceType.DEALER,
        )
        source = SalesSource.objects.create(
            name="區域聯動車行",
            source_type=SalesSource.SourceType.DEALER,
            category=category,
            address="基隆市中正區中正路1號",
        )
        self.client.force_login(user)

        response = self.client.get(reverse("sales_source_edit", args=[source.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="source-district-options"')
        self.assertContains(response, "inferRegionFromAddress")
        self.assertContains(response, 'addressInput?.addEventListener("input"')
        self.assertContains(response, "populateDistrictOptions")
        self.assertEqual(
            response.context["source_context_kind"],
            SalesSource.SourceType.DEALER,
        )
        self.assertContains(response, 'type="hidden" name="category"')
        self.assertNotContains(response, '<label for="id_category">')
        self.assertNotContains(response, '<select name="category"')


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
        sections = {
            section["key"]: section
            for section in response.context["line_group_sections"]
        }
        groups = {
            group["value"]: group
            for group in sections["without_group"]["region_groups"]
        }
        self.assertEqual(groups["基隆市"]["count"], 1)
        self.assertEqual(groups["新北市"]["district_groups"][0]["label"], "汐止區")
        self.assertEqual(groups["__unassigned__"]["label"], "地區待補")
        self.assertContains(response, "基隆市")
        self.assertContains(response, "安樂區")
        self.assertContains(response, 'data-source-region="without_group:基隆市"')
        self.assertContains(response, "dmis:sales-source-expanded-regions:v1")
        self.assertContains(response, "sessionStorage")

    def test_list_separates_dealers_by_line_group_status(self):
        grouped = SalesSource.objects.create(
            name="已有群組車行",
            source_type=SalesSource.SourceType.DEALER,
            address="新北市板橋區文化路一段100號",
            has_line_group=True,
        )

        response = self.client.get(reverse("sales_source_list"))

        sections = {
            section["key"]: section
            for section in response.context["line_group_sections"]
        }
        self.assertEqual(sections["with_group"]["count"], 1)
        self.assertEqual(sections["without_group"]["count"], 4)
        grouped_sources = [
            source
            for region in sections["with_group"]["region_groups"]
            for district in region["district_groups"]
            for source in district["sources"]
        ]
        self.assertEqual(grouped_sources, [grouped])
        self.assertContains(response, "有 LINE 群組")
        self.assertContains(response, "無 LINE 群組")

    def test_search_keeps_both_line_group_sections_when_one_has_no_matches(self):
        SalesSource.objects.create(
            name="群組限定搜尋車行",
            source_type=SalesSource.SourceType.DEALER,
            address="新北市板橋區文化路一段100號",
            has_line_group=True,
        )

        response = self.client.get(
            reverse("sales_source_list"),
            {"q": "群組限定搜尋車行"},
        )

        sections = {
            section["key"]: section
            for section in response.context["line_group_sections"]
        }
        self.assertEqual(sections["with_group"]["count"], 1)
        self.assertEqual(sections["without_group"]["count"], 0)
        self.assertEqual(sections["without_group"]["region_groups"], [])
        self.assertTrue(response.context["has_active_filters"])
        self.assertContains(response, "0 筆符合")
        self.assertContains(response, "其他區域的結果仍顯示在同一頁")
        self.assertContains(response, "source-line-group-section__empty")

    def test_city_filter_only_returns_selected_city(self):
        response = self.client.get(
            reverse("sales_source_list"),
            {"city": "新北市"},
        )

        self.assertContains(response, self.new_taipei.name)
        self.assertNotContains(response, self.keelung.name)
        self.assertNotContains(response, self.taipei.name)

    def test_list_preloads_district_options_for_each_available_city(self):
        response = self.client.get(reverse("sales_source_list"))

        self.assertEqual(response.status_code, 200)
        district_map = response.context["district_filters_by_city"]
        self.assertEqual(
            district_map["新北市"],
            [{"value": "汐止區", "label": "汐止區", "count": 1}],
        )
        self.assertEqual(
            district_map["臺北市"],
            [{"value": "內湖區", "label": "內湖區", "count": 1}],
        )
        self.assertContains(response, 'id="source-district-options"')
        self.assertContains(response, "districtOptionsByCity")

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

    def test_list_displays_existing_dealer_note_in_its_own_column(self):
        self.new_taipei.note = "送價格表前先以 LINE 聯繫"
        self.new_taipei.save(update_fields=["note", "updated_at"])

        response = self.client.get(reverse("sales_source_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "<th>備註</th>", html=True)
        self.assertContains(response, "送價格表前先以 LINE 聯繫")
        self.assertContains(response, 'data-label="備註"')

    def test_list_defaults_to_active_sources_and_keeps_inactive_separate(self):
        inactive = SalesSource.objects.create(
            name="已停用歷史車行",
            source_type=SalesSource.SourceType.DEALER,
            address="新北市板橋區文化路一段200號",
            active=False,
        )

        response = self.client.get(reverse("sales_source_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.new_taipei.name)
        self.assertNotContains(response, inactive.name)
        self.assertEqual(response.context["selected"]["status"], "active")
        self.assertEqual(response.context["source_status_counts"]["active"], 4)
        self.assertEqual(response.context["source_status_counts"]["inactive"], 1)
        self.assertContains(response, "啟用中車行")
        self.assertContains(response, "已停用車行")

    def test_inactive_view_only_shows_inactive_sources_and_preserves_search(self):
        inactive = SalesSource.objects.create(
            name="已停用汐止車行",
            source_type=SalesSource.SourceType.DEALER,
            address="新北市汐止區新台五路一段200號",
            active=False,
        )
        SalesSource.objects.create(
            name="另一筆已停用車行",
            source_type=SalesSource.SourceType.DEALER,
            active=False,
        )

        response = self.client.get(
            reverse("sales_source_list"),
            {"status": "inactive", "q": "汐止"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, inactive.name)
        self.assertNotContains(response, self.new_taipei.name)
        self.assertNotContains(response, "另一筆已停用車行")
        self.assertContains(response, "歷史資料集中收納於此")
        self.assertContains(response, 'name="status" value="inactive"')
        self.assertIn("status=active", response.context["status_urls"]["active"])
        self.assertIn("q=%E6%B1%90%E6%AD%A2", response.context["status_urls"]["active"])

    def test_inactive_view_does_not_split_or_style_by_line_group(self):
        SalesSource.objects.create(
            name="停用但曾有群組車行",
            source_type=SalesSource.SourceType.DEALER,
            address="新北市板橋區文化路一段300號",
            has_line_group=True,
            active=False,
        )
        SalesSource.objects.create(
            name="停用且沒有群組車行",
            source_type=SalesSource.SourceType.DEALER,
            address="基隆市安樂區基金一路300號",
            has_line_group=False,
            active=False,
        )

        response = self.client.get(
            reverse("sales_source_list"),
            {"status": "inactive", "line_group": "yes"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["selected"]["line_group"], "")
        self.assertEqual(len(response.context["line_group_sections"]), 1)
        section = response.context["line_group_sections"][0]
        self.assertEqual(section["key"], "inactive")
        self.assertEqual(section["count"], 2)
        self.assertContains(response, "停用但曾有群組車行")
        self.assertContains(response, "停用且沒有群組車行")
        self.assertContains(response, "歷史資料統一收納，不再依 LINE 群組區分")
        self.assertNotContains(response, 'id="source-line-group"')
        self.assertNotContains(response, "line-group-colour-guide")
        self.assertNotContains(response, "has-line-group")

    def test_unknown_status_falls_back_to_active_sources(self):
        inactive = SalesSource.objects.create(
            name="不應出現的停用車行",
            source_type=SalesSource.SourceType.DEALER,
            active=False,
        )

        response = self.client.get(
            reverse("sales_source_list"),
            {"status": "unexpected"},
        )

        self.assertEqual(response.context["selected"]["status"], "active")
        self.assertContains(response, self.keelung.name)
        self.assertNotContains(response, inactive.name)

    def test_dealer_status_can_be_disabled_from_list(self):
        response = self.client.post(
            reverse("sales_source_set_active", args=[self.new_taipei.pk]),
            {
                "active": "0",
                "next": f"{reverse('sales_source_list')}?city=新北市",
            },
        )

        self.assertRedirects(
            response,
            f"{reverse('sales_source_list')}?city=%E6%96%B0%E5%8C%97%E5%B8%82",
            fetch_redirect_response=False,
        )
        self.new_taipei.refresh_from_db()
        self.assertFalse(self.new_taipei.active)

    def test_dealer_status_can_be_enabled_from_inactive_list(self):
        self.new_taipei.active = False
        self.new_taipei.save(update_fields=["active", "updated_at"])

        response = self.client.post(
            reverse("sales_source_set_active", args=[self.new_taipei.pk]),
            {
                "active": "1",
                "next": f"{reverse('sales_source_list')}?status=inactive",
            },
        )

        self.assertRedirects(
            response,
            f"{reverse('sales_source_list')}?status=inactive",
            fetch_redirect_response=False,
        )
        self.new_taipei.refresh_from_db()
        self.assertTrue(self.new_taipei.active)

    def test_dealer_status_ajax_updates_without_reloading_list(self):
        response = self.client.post(
            reverse("sales_source_set_active", args=[self.new_taipei.pk]),
            {
                "active": "0",
                "next": reverse("sales_source_list"),
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "ok": True,
                "active": False,
                "status_counts": {"active": 3, "inactive": 1},
                "message": f"{self.new_taipei.name} 已停用，已移至已停用車行。",
            },
        )
        self.new_taipei.refresh_from_db()
        self.assertFalse(self.new_taipei.active)

    def test_dealer_status_ajax_rejects_invalid_state(self):
        response = self.client.post(
            reverse("sales_source_set_active", args=[self.new_taipei.pk]),
            {"active": "unexpected"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            {"ok": False, "message": "無法更新車行狀態，請重新操作。"},
        )
        self.new_taipei.refresh_from_db()
        self.assertTrue(self.new_taipei.active)

    def test_dealer_status_endpoint_rejects_get_and_non_dealer(self):
        platform = SalesSource.objects.create(
            name="不可切換的平台",
            source_type=SalesSource.SourceType.PLATFORM,
        )

        get_response = self.client.get(
            reverse("sales_source_set_active", args=[self.new_taipei.pk])
        )
        platform_response = self.client.post(
            reverse("sales_source_set_active", args=[platform.pk]),
            {"active": "0"},
        )

        self.assertEqual(get_response.status_code, 405)
        self.assertEqual(platform_response.status_code, 404)

    def test_dealer_status_endpoint_rejects_external_return_url(self):
        response = self.client.post(
            reverse("sales_source_set_active", args=[self.new_taipei.pk]),
            {"active": "0", "next": "https://example.com/unsafe"},
        )

        self.assertRedirects(
            response,
            reverse("sales_source_list"),
            fetch_redirect_response=False,
        )

    def test_list_renders_accessible_status_switch(self):
        response = self.client.get(reverse("sales_source_list"))

        self.assertContains(response, 'role="switch"')
        self.assertContains(response, 'aria-checked="true"')
        self.assertContains(
            response,
            reverse("sales_source_set_active", args=[self.new_taipei.pk]),
        )
        self.assertContains(response, "點擊停用")
        self.assertContains(response, 'data-source-name="汐止分區車行"')
        self.assertContains(response, "const submitActive = async (form) =>")
        self.assertContains(response, "removeMovedSourceRow(form, payload.status_counts);")
        self.assertContains(response, 'data-source-status-count="active"')
        self.assertContains(response, 'data-source-status-count="inactive"')

    def test_dealer_list_does_not_mix_staff_or_platform_sources(self):
        staff = SalesSource.objects.create(
            name="內部行政人員",
            source_type=SalesSource.SourceType.STORE,
        )
        platform = SalesSource.objects.create(
            name="網路銷售平台",
            source_type=SalesSource.SourceType.PLATFORM,
        )

        response = self.client.get(reverse("sales_source_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.keelung.name)
        self.assertNotContains(response, staff.name)
        self.assertNotContains(response, platform.name)
        self.assertNotContains(response, "本店人員與網路平台")

    def test_staff_and_platform_have_separate_screens(self):
        staff = SalesSource.objects.create(
            name="內部行政人員",
            source_type=SalesSource.SourceType.STORE,
        )
        platform = SalesSource.objects.create(
            name="網路銷售平台",
            source_type=SalesSource.SourceType.PLATFORM,
        )

        staff_response = self.client.get(reverse("sales_source_staff_list"))
        platform_response = self.client.get(reverse("sales_source_platform_list"))

        self.assertEqual(staff_response.status_code, 200)
        self.assertContains(staff_response, staff.name)
        self.assertNotContains(staff_response, platform.name)
        self.assertNotContains(staff_response, self.keelung.name)
        self.assertEqual(platform_response.status_code, 200)
        self.assertContains(platform_response, platform.name)
        self.assertNotContains(platform_response, staff.name)
        self.assertNotContains(platform_response, self.keelung.name)

    def test_simple_source_screens_separate_inactive_records(self):
        active_staff = SalesSource.objects.create(
            name="啟用人員",
            source_type=SalesSource.SourceType.STORE,
        )
        inactive_staff = SalesSource.objects.create(
            name="停用人員",
            source_type=SalesSource.SourceType.STORE,
            active=False,
        )

        active_response = self.client.get(reverse("sales_source_staff_list"))
        inactive_response = self.client.get(
            reverse("sales_source_staff_list"), {"status": "inactive"}
        )

        self.assertContains(active_response, active_staff.name)
        self.assertNotContains(active_response, inactive_staff.name)
        self.assertContains(inactive_response, inactive_staff.name)
        self.assertNotContains(inactive_response, active_staff.name)

    def test_create_form_uses_requested_source_context_and_return_path(self):
        staff_category = SalesSourceCategory.objects.create(
            name="本店人員",
            system_behavior=SalesSource.SourceType.STORE,
        )
        dealer_category = SalesSourceCategory.objects.create(
            name="不應出現的車行分類",
            system_behavior=SalesSource.SourceType.DEALER,
        )

        response = self.client.get(
            reverse("sales_source_create"),
            {"kind": SalesSource.SourceType.STORE},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "新增本店人員")
        self.assertContains(response, reverse("sales_source_staff_list"))
        self.assertIn(staff_category, response.context["form"].fields["category"].queryset)
        self.assertNotIn(
            dealer_category,
            response.context["form"].fields["category"].queryset,
        )

    def test_edit_form_returns_to_the_matching_source_screen(self):
        platform = SalesSource.objects.create(
            name="回程測試平台",
            source_type=SalesSource.SourceType.PLATFORM,
        )

        response = self.client.get(reverse("sales_source_edit", args=[platform.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "編輯網路平台")
        self.assertContains(response, reverse("sales_source_platform_list"))
