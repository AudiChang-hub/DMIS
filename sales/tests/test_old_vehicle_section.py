from django.contrib.auth import get_user_model
from django.urls import reverse

from sales.tests import test_order_lifecycle as lifecycle


class OldVehicleSectionTests(lifecycle.OrderLifecycleTests.__bases__[0]):
    setUp = lifecycle.OrderLifecycleTests.setUp
    make_order = lifecycle.OrderLifecycleTests.make_order

    def login_admin(self):
        admin = get_user_model().objects.create_superuser("admin", password="Old-vehicle-test-61!")
        self.client.force_login(admin)

    def test_subsidy_step_edits_old_vehicle_data_in_place(self):
        self.login_admin()
        order, _vehicle = self.make_order()
        html = self.client.get(reverse("order_detail", args=[order.pk])).content.decode()
        self.assertNotIn("僅供查看", html)
        self.assertIn('value="old_vehicle"', html)
        self.assertIn('id="ops_old_vehicle_operations-old_vehicle_engine_number"', html)
        # 舊車與報廢資料併入「汰舊與舊車資料」卡、只出現一次；補助撥款追蹤整區拿掉（2026-10-22 T-81、T-82）。
        self.assertEqual(html.count("<h4>舊車與報廢</h4>"), 1)
        self.assertLess(html.index('id="tradein-card-title"'), html.index("<h4>舊車與報廢</h4>"))
        self.assertNotIn("補助撥款追蹤", html)
        self.assertIn('form="ops-old-vehicle-form"', html)

    def test_old_vehicle_section_saves_without_touching_subsidy_tracking(self):
        self.login_admin()
        order, _vehicle = self.make_order()
        profile = order.operations
        profile.bank_name = "測試銀行"
        profile.save(update_fields=["bank_name"])
        payload = {
            "_section": "old_vehicle", "operations-financial_revision": profile.updated_at.isoformat(),
            "operations-old_vehicle_engine_number": "5FH-604355", "operations-old_vehicle_brand": "山葉",
            "operations-old_vehicle_displacement_cc": "49", "operations-scrapped_on": "2026-10-12",
        }
        self.client.post(reverse("order_operations", args=[order.pk]), payload)
        profile.refresh_from_db()
        self.assertEqual(profile.old_vehicle_engine_number, "5FH-604355")
        self.assertEqual(profile.old_vehicle_displacement_cc, 49)
        self.assertEqual(str(profile.scrapped_on), "2026-10-12")
        self.assertEqual(profile.bank_name, "測試銀行")
