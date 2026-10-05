from datetime import date

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from sales.forms import AllocationForm
from sales.models import (
    OrderEvent,
    VehicleInventory,
    VehicleInventoryHistory,
    allocation_priority_cutoff,
)
from sales.tests import test_state_integrity as integrity


def months_ago(months):
    today = timezone.localdate()
    index = today.year * 12 + today.month - 1 - months
    return f"{index // 12:04d}/{index % 12 + 1:02d}"


class AllocationPriorityTests(TestCase):
    setUp = integrity.StateIntegrityTests.setUp
    make_order = integrity.StateIntegrityTests.make_order
    vehicle = integrity.StateIntegrityTests.vehicle
    pending_order = integrity.StateIntegrityTests.pending_order

    def clean_pending_order(self):
        order = self.pending_order()
        # 共用夾具會留下一台可售車，先停用以免影響排序斷言。
        VehicleInventory.objects.update(status=VehicleInventory.Status.INACTIVE)
        return order

    def set_override(self, vehicle, value):
        VehicleInventory.objects.filter(pk=vehicle.pk).update(allocation_priority_override=value)
        vehicle.refresh_from_db()

    def test_cutoff_requires_more_than_three_months(self):
        self.assertEqual(allocation_priority_cutoff(date(2026, 10, 5)), "2026/06")
        self.assertEqual(allocation_priority_cutoff(date(2026, 2, 28)), "2025/10")
        self.assertTrue(self.vehicle("AGE4", months_ago(4)).allocation_priority)
        self.assertFalse(self.vehicle("AGE3", months_ago(3)).allocation_priority)
        self.assertFalse(self.vehicle("BLANK").allocation_priority)

    def test_manual_override_wins_over_age(self):
        old = self.vehicle("OLD", months_ago(8))
        self.set_override(old, False)
        self.assertFalse(old.allocation_priority)
        self.assertEqual(old.allocation_priority_source_label, "人工")
        fresh = self.vehicle("FRESH", months_ago(0))
        self.set_override(fresh, True)
        self.assertTrue(fresh.allocation_priority)

    def test_dropdown_lists_priority_first_then_oldest_with_blank_last(self):
        order = self.clean_pending_order()
        blank = self.vehicle("BLANK")
        newer = self.vehicle("NEWER", months_ago(1))
        older = self.vehicle("OLDER", months_ago(2))
        auto_priority = self.vehicle("AUTO", months_ago(6))
        manual_priority = self.vehicle("MANUAL", months_ago(0))
        self.set_override(manual_priority, True)
        form = AllocationForm(order)
        ids = list(form.fields["vehicle"].queryset.values_list("pk", flat=True))
        self.assertEqual(ids, [auto_priority.pk, manual_priority.pk, older.pk, newer.pk, blank.pk])
        self.assertEqual(form.priority_vehicle_count, 2)
        html = str(form["vehicle"])
        self.assertIn(f"★ 優先配車｜SI-AUTO｜出廠 {months_ago(6)}", html)
        self.assertIn(f"SI-OLDER｜出廠 {months_ago(2)}", html)
        self.assertIn("SI-BLANK｜出廠 未填寫", html)
        self.assertEqual(html.count('data-allocation-priority="true"'), 2)

    def test_skipping_priority_vehicle_suggests_reason_without_requiring_it(self):
        order = self.clean_pending_order()
        priority = self.vehicle("PRI", months_ago(6))
        normal = self.vehicle("NORMAL", months_ago(1))
        form = AllocationForm(order, {"vehicle": normal.pk})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertIn("尚有優先配車車輛 SI-PRI", form.cleaned_data["skip_notes"])
        self.client.force_login(self.user)
        self.client.post(reverse("allocate_vehicle", args=[order.pk]), {"vehicle": normal.pk})
        order.refresh_from_db()
        self.assertEqual(order.allocated_vehicle_id, normal.pk)
        description = OrderEvent.objects.get(order=order, event_type="allocated").description
        self.assertIn("尚有優先配車車輛 SI-PRI", description)
        self.assertIn("原因：未填寫", description)
        self.assertEqual(priority.pk, AllocationForm(order).fields["vehicle"].queryset.first().pk)

    def test_fifo_within_priority_tier_still_requires_reason(self):
        order = self.clean_pending_order()
        oldest = self.vehicle("P-OLD", months_ago(9))
        newer = self.vehicle("P-NEW", months_ago(5))
        form = AllocationForm(order, {"vehicle": newer.pk})
        self.assertFalse(form.is_valid())
        self.assertIn("較早出廠的車輛 SI-P-OLD", str(form.errors))
        self.assertTrue(AllocationForm(order, {"vehicle": oldest.pk}).is_valid())

    def test_choosing_manual_priority_over_older_normal_vehicle_needs_no_reason(self):
        order = self.clean_pending_order()
        old_normal = self.vehicle("OLD", months_ago(7))
        self.set_override(old_normal, False)
        manual = self.vehicle("MANUAL", months_ago(0))
        self.set_override(manual, True)
        form = AllocationForm(order, {"vehicle": manual.pk})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["skip_notes"], [])

    def test_toggle_records_manual_override_and_returns_to_auto(self):
        old = self.vehicle("TOGGLE", months_ago(6))
        self.client.force_login(self.user)
        url = reverse("inventory_allocation_priority", args=[old.pk])
        response = self.client.post(url, {"priority": "0"}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(response.json()["priority"], False)
        self.assertEqual(response.json()["source"], "人工")
        old.refresh_from_db()
        self.assertIs(old.allocation_priority_override, False)
        history = VehicleInventoryHistory.objects.get(vehicle=old, reason="切換優先配車")
        self.assertEqual(history.changes["allocation_priority"]["before"], "開啟（自動）")
        self.assertEqual(history.changes["allocation_priority"]["after"], "關閉（人工）")

        response = self.client.post(url, {"priority": "1", "next": reverse("inventory_list")})
        self.assertRedirects(response, reverse("inventory_list"), fetch_redirect_response=False)
        old.refresh_from_db()
        self.assertIsNone(old.allocation_priority_override)
        self.assertTrue(old.allocation_priority)
        self.assertEqual(VehicleInventoryHistory.objects.filter(vehicle=old, reason="切換優先配車").count(), 2)

    def test_toggle_manually_enables_vehicle_younger_than_threshold(self):
        # 正式站 1.35.0 曾因鎖定含 LEFT JOIN 的查詢在 PostgreSQL 回 500；CI 以 PostgreSQL 執行本檔。
        fresh = self.vehicle("FRESH-ON", months_ago(1))
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("inventory_allocation_priority", args=[fresh.pk]),
            {"priority": "1"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["priority"], True)
        self.assertEqual(response.json()["source"], "人工")
        fresh.refresh_from_db()
        self.assertIs(fresh.allocation_priority_override, True)

    def test_toggle_rejects_historical_vehicle(self):
        vehicle = self.vehicle("DONE", months_ago(6))
        VehicleInventory.objects.filter(pk=vehicle.pk).update(status=VehicleInventory.Status.DELIVERED)
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("inventory_allocation_priority", args=[vehicle.pk]),
            {"priority": "0"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 400)
        vehicle.refresh_from_db()
        self.assertIsNone(vehicle.allocation_priority_override)

    def test_inventory_list_shows_switch_rule_and_priority_sort(self):
        priority = self.vehicle("LIST-P", months_ago(6))
        self.vehicle("LIST-N", months_ago(1))
        self.client.force_login(self.user)
        response = self.client.get(reverse("inventory_list"), {"sort": "priority"})
        self.assertContains(response, "優先配車規則")
        self.assertContains(response, f"目前為 {allocation_priority_cutoff()} 以前出廠")
        self.assertContains(response, reverse("inventory_allocation_priority", args=[priority.pk]))
        vehicles = list(response.context["vehicles"])
        self.assertEqual(vehicles[0].pk, priority.pk)
        # 「自動」只標在因車齡自動開啟的車；一般車不顯示來源標籤。
        html = response.content.decode()
        self.assertEqual(html.count("data-priority-source"), 2)
        self.assertEqual(html.count("hidden>自動</small>"), 1)
        self.assertEqual(html.count('系統自動開啟">自動</small>'), 1)
        history = self.client.get(reverse("inventory_list"), {"scope": "history"})
        self.assertNotContains(history, "優先配車規則")
