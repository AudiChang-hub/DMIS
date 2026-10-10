"""訂單頁編輯不含汰舊補助欄位（改在「汰舊補助」分頁），不能留下空白的確認框。"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from sales.models import SalesOrder, VehicleColor, VehicleModel


class OrderEditTradeInFieldsTests(TestCase):
    def test_edit_page_has_no_empty_trade_in_boxes(self):
        root = get_user_model().objects.create_superuser("admin", password="Local-trade-in-984!")
        self.client.force_login(root)
        model = VehicleModel.objects.create(brand="QA", name="測試車", model_year=2026)
        color = VehicleColor.objects.create(vehicle_model=model, name="灰")
        order = SalesOrder.objects.create(
            owner_name="甲", owner_phone="0900000000", owner_address="地址", owner_id_number="A123456789",
            vehicle_model=model, color=color, status=SalesOrder.Status.COMPLETED, trade_in_intent="yes",
        )
        response = self.client.get(reverse("order_edit", args=[order.pk]))
        self.assertNotIn("is_trade_in_subsidy", response.context["form"].fields)
        self.assertNotContains(response, '<label for=""></label>')
        self.assertContains(response, "舊車主資料與補助申請請到訂單的「汰舊補助」分頁填寫。")
