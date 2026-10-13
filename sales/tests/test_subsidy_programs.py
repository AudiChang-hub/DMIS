"""1.64.0：補助方案主檔、訂車多選帶入訂單補助項目、補助文字欄位選填。"""
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from sales.forms import SubsidyItemForm
from sales.models import SalesOrder, SubsidyItem, SubsidyProgram
from sales.tests import test_completed_order_corrections as correction_tests


class SubsidyProgramTests(TestCase):
    setUpTestData = classmethod(correction_tests.CompletedOrderCorrectionTests.setUpTestData.__func__)
    setUp = correction_tests.CompletedOrderCorrectionTests.setUp
    order = correction_tests.CompletedOrderCorrectionTests.order
    payload = correction_tests.CompletedOrderCorrectionTests.payload
    post = correction_tests.CompletedOrderCorrectionTests.post
    assert_saved = correction_tests.CompletedOrderCorrectionTests.assert_saved

    def setUp(self):
        correction_tests.CompletedOrderCorrectionTests.setUp(self)
        self.trade_in = SubsidyProgram.objects.get(name="汰舊換新")  # 0176 預先建立
        self.new_purchase = SubsidyProgram.objects.get(name="貨物稅補助")
        self.new_purchase.default_amount = Decimal("3000")
        self.new_purchase.save()
        self.pending = self.order(status=SalesOrder.Status.ALLOCATION_PENDING, registration_date=None)

    def edit(self, programs, **extra):
        return self.post(self.pending, subsidy_programs=[str(p.pk) for p in programs], subsidy_programs_present="1",
                         confirm_completed_correction="", registration_date="", **extra)

    def test_seeded_programs_and_master_page(self):
        self.assertTrue(self.trade_in.requires_old_vehicle)
        self.assertTrue(SubsidyProgram.objects.filter(name="貨物稅補助").exists())
        page = self.client.get(reverse("subsidy_program_list"))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "貨物稅補助")
        response = self.client.post(reverse("subsidy_program_list"), {
            "name": "電動車補助", "category": "environment", "default_amount": "", "active": "on", "sort_order": "40",
        })
        self.assertRedirects(response, reverse("subsidy_program_list"))
        created = SubsidyProgram.objects.get(name="電動車補助")
        self.assertIsNone(created.default_amount)

    def test_selecting_programs_creates_items_with_defaults(self):
        self.assert_saved(self.edit([self.trade_in, self.new_purchase]), self.pending)
        items = {item.item_name: item for item in self.pending.subsidy_items.all()}
        self.assertEqual(set(items), {"汰舊換新", "貨物稅補助"})
        self.assertEqual(items["貨物稅補助"].expected_amount, Decimal("3000"))
        self.assertEqual(items["汰舊換新"].expected_amount, Decimal("0"))
        self.assertTrue(self.pending.is_trade_in_subsidy, "汰舊類方案開啟汰舊補助流程")
        self.assertIn("汰舊換新", self.pending.subsidy_type)

    def test_unchecking_removes_only_unsubmitted_items(self):
        self.assert_saved(self.edit([self.trade_in, self.new_purchase]), self.pending)
        SubsidyItem.objects.filter(order=self.pending, program=self.trade_in).update(status=SubsidyItem.Status.SUBMITTED)
        self.assert_saved(self.edit([]), self.pending)
        names = set(self.pending.subsidy_items.values_list("item_name", flat=True))
        self.assertEqual(names, {"汰舊換新"}, "已送出申請的保留，未申請的移除")

    def test_without_marker_programs_untouched(self):
        self.assert_saved(self.edit([self.new_purchase]), self.pending)
        # 沒有 subsidy_programs_present 標記（例如其他不含此欄位的儲存）就算沒勾選也不動補助項目。
        response = self.post(self.pending, confirm_completed_correction="", registration_date="", subsidy_programs=[])
        self.assert_saved(response, self.pending)
        self.assertEqual(self.pending.subsidy_items.count(), 1)

    def test_subsidy_text_fields_are_optional(self):
        form = SubsidyItemForm({"item_name": "", "expected_amount": "500", "category": "", "status": "not_submitted"})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["item_name"], "補助")

    def test_edit_page_shows_program_picker(self):
        page = self.client.get(reverse("order_edit", args=[self.pending.pk]))
        self.assertContains(page, "申請補助（可多選）")
        self.assertContains(page, 'name="subsidy_programs_present"')
        self.assertContains(page, "貨物稅補助")

    def test_other_subsidy_names_create_items_once(self):
        # 1.70.0：政府清單外的補助勾「其他」自填名稱，可用「、」填多個；重複儲存不重複建立。
        page = self.client.get(reverse("order_edit", args=[self.pending.pk]))
        self.assertContains(page, "data-subsidy-other-toggle")
        self.assertContains(page, 'name="subsidy_other"')
        self.assert_saved(self.edit([self.new_purchase], subsidy_other="縣市加碼補助、 節能補助"), self.pending)
        self.assert_saved(self.edit([self.new_purchase], subsidy_other="縣市加碼補助"), self.pending)
        others = self.pending.subsidy_items.filter(program__isnull=True)
        self.assertEqual(sorted(others.values_list("item_name", flat=True)), ["節能補助", "縣市加碼補助"])
        self.assertTrue(all(item.category == SubsidyItem.Category.OTHER for item in others))
        self.assertIn("縣市加碼補助", self.pending.subsidy_type)

    def test_programs_follow_vehicle_kind_and_exclusive_groups(self):
        # 1.73.3：油車＝貨物稅補助、汰舊換新；電動車＝環保局新購／汰舊、環境部、產發署新購／汰舊；同單位新購與汰舊擇一。
        self.assertFalse(SubsidyProgram.objects.get(name="新購補助").active)
        gas_page = self.client.get(reverse("order_edit", args=[self.pending.pk])).content.decode()
        for name in ("貨物稅補助", "汰舊換新"):
            self.assertIn(name, gas_page)
        self.assertNotIn("各縣市環保局 新購", gas_page)
        self.assertIn("data-subsidy-group", gas_page)
        from sales.models import VehicleModel
        VehicleModel.objects.filter(pk=self.pending.vehicle_model_id).update(energy_type=VehicleModel.EnergyType.ELECTRIC)
        electric_page = self.client.get(reverse("order_edit", args=[self.pending.pk])).content.decode()
        for name in ("各縣市環保局 新購", "各縣市環保局 汰舊", "環境部", "產業發展署 新購", "產業發展署 汰舊"):
            self.assertIn(name, electric_page)
        self.assertNotIn(">貨物稅補助<", electric_page)
        new, old = (SubsidyProgram.objects.get(name=f"各縣市環保局 {kind}") for kind in ("新購", "汰舊"))
        self.assertEqual(new.exclusive_group, old.exclusive_group)
        response = self.edit([new, old], vehicle_energy_type="electric")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "只能擇一")
        self.assert_saved(self.edit([new, SubsidyProgram.objects.get(name="產業發展署 汰舊")], subsidy_other="縣市加碼",
                                    vehicle_energy_type="electric"), self.pending)
        names = set(self.pending.subsidy_items.values_list("item_name", flat=True))
        self.assertEqual(names, {"各縣市環保局 新購", "產業發展署 汰舊", "縣市加碼"})
        self.assertTrue(self.pending.is_trade_in_subsidy, "選了汰舊類方案開啟汰舊補助流程")
