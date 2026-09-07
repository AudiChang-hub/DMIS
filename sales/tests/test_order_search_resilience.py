from unittest.mock import Mock, patch

from django.test import TestCase, override_settings

from sales.models import SalesOrder, SalesOrderSearchIndex, VehicleColor, VehicleModel


class OrderSearchQueueFallbackTests(TestCase):
    def setUp(self):
        vehicle_model = VehicleModel.objects.create(
            brand="測試品牌",
            name="搜尋降級測試車型",
            energy_type=VehicleModel.EnergyType.GAS,
        )
        color = VehicleColor.objects.create(
            vehicle_model=vehicle_model,
            name="黑",
        )
        self.order = SalesOrder.objects.create(
            owner_name="原始車主",
            owner_phone="0911222333",
            owner_address="新北市測試區",
            owner_id_number="A123456789",
            vehicle_model=vehicle_model,
            color=color,
        )

    @override_settings(REDIS_URL="redis://search-queue.invalid:6379/0")
    @patch("sales.services.order_search.django_rq.get_queue")
    def test_save_falls_back_to_synchronous_index_when_enqueue_fails(self, get_queue):
        queue = Mock()
        queue.enqueue.side_effect = RuntimeError("redis unavailable")
        get_queue.return_value = queue
        SalesOrderSearchIndex.objects.filter(order=self.order).delete()

        with self.assertLogs("sales.services.order_search", level="ERROR") as logs:
            with self.captureOnCommitCallbacks(execute=True):
                self.order.owner_name = "Redis 故障仍可搜尋"
                self.order.save(update_fields=["owner_name", "updated_at"])

        queue.enqueue.assert_called_once()
        search_index = SalesOrderSearchIndex.objects.get(order=self.order)
        self.assertIn("redis故障仍可搜尋", search_index.search_text)
        self.assertTrue(any("改用同步重建" in message for message in logs.output))
