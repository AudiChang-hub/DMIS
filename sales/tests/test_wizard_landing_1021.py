"""建立訂單精靈的換步停點與選車篩選（使用者 2026-10-21 投影片三 T-52／T-53）。"""
import re
from pathlib import Path

from django.test import TestCase, override_settings
from django.urls import reverse

from sales.tests import test_order_wizard as wizard_tests

SEARCHABLE = Path("static/js/searchable-select.js").read_text(encoding="utf-8")
CATALOG_JS = Path("static/js/catalog-manage.js").read_text(encoding="utf-8")


@override_settings(MEDIA_ROOT=wizard_tests.MEDIA)
class WizardLandingTests(TestCase):
    setUp = wizard_tests.OrderWizardTests.setUp
    image = wizard_tests.OrderWizardTests.image
    complete_data = wizard_tests.OrderWizardTests.complete_data
    post = wizard_tests.OrderWizardTests.post
    draft = wizard_tests.OrderWizardTests.draft
    walk_to = wizard_tests.OrderWizardTests.walk_to

    def step_page(self, step):
        draft = self.walk_to(step)
        response = self.client.get(reverse("order_create") + f"?draft={draft.pk}&step={step}")
        self.assertEqual(response.status_code, 200)
        return draft, response.content.decode()

    # T-52 根因：精靈每一步都送出整張表單、草稿整份覆寫。車色在其他步驟是隱藏欄位，
    # 少了它就被退回「車款與車價」並帶車色錯誤，畫面因而跳到車色。
    def test_step_post_without_color_bounces_back_to_vehicle_color(self):
        draft = self.walk_to("tradein")
        data = {key: value for key, value in self.complete_data().items() if key != "color"}
        data.update({"_wizard_step": "tradein", "_wizard_action": "next", "_submission_key": self.key,
                     "_draft_id": str(draft.pk), "_draft_revision": str(draft.revision)})
        response = self.client.post(reverse("order_create"), data)
        self.assertEqual(response.status_code, 200)
        page = response.content.decode()
        self.assertIn('name="_wizard_step" value="vehicle"', page)
        self.assertIn("車色", page.split("wizard-errors", 1)[1].split("</ul>", 1)[0])

    # 所以進頁核對已選車色時不可停用或清空車色（停用的欄位不會送出）；讀取失敗也保留伺服器帶好的選項。
    def test_colour_refresh_keeps_current_colour_submittable(self):
        _draft, page = self.step_page("tradein")
        loader = page.split("async function loadVehicleColors", 1)[1].split("vehicleModel.addEventListener", 1)[0]
        self.assertIn("const refreshing = Boolean(previousColor);", loader)
        guarded = loader.split("if (!refreshing) {", 1)[1].split("}", 1)[0]
        self.assertIn("color.disabled = true;", guarded)
        self.assertIn('if (error.name === "AbortError" || refreshing) return;', loader)
        self.assertIn("loadVehicleColors({preserveCurrent: true});", page)

    # 換步後停在這一步區塊頂端，瞬間定位（全站 html 是 smooth）；只有驗證失敗才定位到錯誤欄位。
    def test_next_step_lands_on_step_panel_top(self):
        _draft, page = self.step_page("owner")
        landing = page.split("const landOnStep = () => {", 1)[1].split("const settle", 1)[0]
        self.assertIn('stepPanel.getBoundingClientRect().top - headerHeight - 16', landing)
        self.assertIn('behavior: "instant"', landing)
        self.assertIn('orderForm.querySelector("[data-wizard-panel]:not([hidden])")', page)
        self.assertIn('!orderForm.querySelector(".has-error") && !document.querySelector(".wizard-errors")', page)
        self.assertIn('history.replaceState(history.state, "", pageUrl)', page)
        self.assertIn('showValidationSummary(null, {instant: true})', page)
        self.assertIn('behavior: instant ? "instant" : "smooth"', page)


class CatalogSearchableFilterTests(TestCase):
    # T-53：選車的每個篩選都能打字搜尋，可選「全部…」清除；送出的值與原本 select 相同。
    def test_every_catalog_filter_is_a_searchable_select(self):
        page = self.client.get(reverse("catalog")).content.decode()
        form = page.split("data-catalog-filters", 1)[1].split("</form>", 1)[0]
        selects = re.findall(r"<select[^>]*>", form)
        self.assertEqual([re.search(r'name="([^"]+)"', tag).group(1) for tag in selects],
                         ["brand", "model_name", "model_number", "energy"])
        for tag in selects:
            self.assertIn('data-searchable-select="1"', tag)
            self.assertIn('data-searchable-include-empty="1"', tag)
            self.assertIn("data-search-placeholder=", tag)
        for empty in ("全部品牌", "全部車型", "全部型號", "全部能源"):
            self.assertIn(f'<option value="">{empty}</option>', form)

    def test_clearing_syncs_the_search_boxes(self):
        # 按搜尋框的 × 就清除這一欄；「清除篩選」改值後要送 change，搜尋框才會顯示「全部…」。
        self.assertIn('input.addEventListener("search"', SEARCHABLE)
        self.assertIn("if (emptyOption) choose(emptyOption);", SEARCHABLE)
        self.assertIn("energy.dispatchEvent(new Event('change'));", CATALOG_JS)
