"""T-216：訂單頁「補助申請項目」狀態下拉是「未申請」時紅底（實心色），改成已申請就恢復；只影響這個下拉。"""
import re
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from sales.forms import SubsidyItemForm
from sales.models import SalesOrder, SubsidyItem, VehicleColor, VehicleModel


class SubsidyStatusSelectTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_superuser("t216-admin", password="test-only")
        model = VehicleModel.objects.create(brand="測試", name="補助機種", energy_type="gas")
        color = VehicleColor.objects.create(vehicle_model=model, name="白")
        cls.order = SalesOrder.objects.create(
            owner_name="合成車主", owner_phone="0912345678", owner_address="合成測試地址", owner_id_number="A123456789",
            vehicle_model=model, color=color, payment_type="cash", is_trade_in_subsidy=True,
            status=SalesOrder.Status.ALLOCATION_PENDING,
        )
        cls.unsubmitted = SubsidyItem.objects.create(order=cls.order, category="industry", item_name="產業發展署 汰舊", expected_amount=5000)
        cls.submitted = SubsidyItem.objects.create(
            order=cls.order, category="environment", item_name="環境部 汰舊", expected_amount=3000, status=SubsidyItem.Status.SUBMITTED,
        )

    def subsidy_tab(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("order_detail", args=[self.order.pk]), {"tab": "subsidy"})
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def select_tag(self, page, name):
        found = re.findall(rf'<select[^>]*name="{re.escape(name)}"[^>]*>', page)
        self.assertEqual(len(found), 1, name)
        return found[0]

    def test_unsubmitted_rows_get_red_class_and_submitted_rows_do_not(self):
        page = self.subsidy_tab()
        rows = {int(pk): index for index, pk in re.findall(r'name="subsidy_items-(\d+)-id" value="(\d+)"', page)}
        red = self.select_tag(page, f"subsidy_items-{rows[self.unsubmitted.pk]}-status")
        plain = self.select_tag(page, f"subsidy_items-{rows[self.submitted.pk]}-status")
        self.assertIn('class="subsidy-status is-unsubmitted"', red)
        self.assertIn("data-subsidy-status", red)
        self.assertIn('class="subsidy-status"', plain)
        self.assertIn("data-subsidy-status", plain, "已申請的列也要能被即時切換")
        self.assertNotIn("is-unsubmitted", plain)

    def test_new_row_template_defaults_to_unsubmitted(self):
        template = self.select_tag(self.subsidy_tab(), "subsidy_items-__prefix__-status")
        self.assertIn('class="subsidy-status is-unsubmitted"', template, "新增的補助項目預設未申請，一出現就是紅底")

    def test_only_the_status_select_is_marked(self):
        page = self.subsidy_tab()
        self.assertEqual(page.count("is-unsubmitted"), 2, "一列未申請＋新增列範本，別的元素都不帶")
        self.assertEqual(page.count("data-subsidy-status"), 3)
        category = self.select_tag(page, "subsidy_items-0-category")
        self.assertNotIn("subsidy-status", category)
        self.assertNotIn("class=", category, "類別下拉維持原樣")

    def test_bound_form_follows_submitted_value(self):
        data = {"category": "local", "item_name": "地方", "expected_amount": "0", "status": SubsidyItem.Status.SUBMITTED}
        self.assertEqual(SubsidyItemForm(data=data)["status"].field.widget.attrs["class"], "subsidy-status")
        data["status"] = SubsidyItem.Status.NOT_SUBMITTED
        self.assertEqual(SubsidyItemForm(data=data)["status"].field.widget.attrs["class"], "subsidy-status is-unsubmitted")

    def test_status_change_still_autosaves(self):
        # 既有行為：改狀態照常存檔，不受新 class 影響。
        self.client.force_login(self.user)
        items = list(self.order.subsidy_items.order_by("pk"))
        post = {
            "_order_revision": str(SalesOrder.objects.get(pk=self.order.pk).revision),
            "subsidy_items-TOTAL_FORMS": "2", "subsidy_items-INITIAL_FORMS": "2",
            "subsidy_items-MIN_NUM_FORMS": "0", "subsidy_items-MAX_NUM_FORMS": "1000",
        }
        for index, item in enumerate(items):
            post.update({
                f"subsidy_items-{index}-id": str(item.pk), f"subsidy_items-{index}-order": str(self.order.pk),
                f"subsidy_items-{index}-category": item.category, f"subsidy_items-{index}-item_name": item.item_name,
                f"subsidy_items-{index}-expected_amount": str(item.expected_amount),
                f"subsidy_items-{index}-status": SubsidyItem.Status.SUBMITTED,
            })
        response = self.client.post(reverse("subsidy_data_update", args=[self.order.pk]), post, HTTP_X_REQUESTED_WITH="XMLHttpRequest", HTTP_ACCEPT="application/json")
        self.assertLess(response.status_code, 400, response.content[:300])
        self.unsubmitted.refresh_from_db()
        self.assertEqual(self.unsubmitted.status, SubsidyItem.Status.SUBMITTED)
        self.assertNotIn("is-unsubmitted", re.sub(r"<template data-empty-form>.*?</template>", "", self.subsidy_tab(), flags=re.S))


class SubsidyStatusCssTests(SimpleTestCase):
    css = (Path(settings.BASE_DIR) / "static" / "css" / "app.css").read_text(encoding="utf-8")

    def test_red_fill_is_solid_and_scoped_to_the_subsidy_status_select(self):
        rules = re.findall(r"([^{}]*\.is-unsubmitted[^{}]*)\{([^}]*)\}", self.css)
        self.assertTrue(rules)
        for selector, body in rules:
            self.assertIn("[data-subsidy-items] select.subsidy-status.is-unsubmitted", selector, "只作用在補助申請項目的狀態下拉")
            for loose in ("transparent", "rgba", "color-mix", "opacity"):
                self.assertNotIn(loose, body, "實心底色，不用半透明（會被系統色蓋掉）")
        main = dict((s.strip().split("\n")[-1].strip(), b) for s, b in rules)["[data-subsidy-items] select.subsidy-status.is-unsubmitted"]
        self.assertIn("background-color: var(--red)", main)
        self.assertNotRegex(main, r"(^|[;\s])background:", "只換底色，保留全站下拉的箭頭圖")
