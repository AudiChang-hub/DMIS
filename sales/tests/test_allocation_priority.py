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

    def test_manual_on_stays_manual_after_aging_and_legacy_off_is_ignored(self):
        fresh = self.vehicle("FRESH", months_ago(0))
        self.set_override(fresh, True)
        self.assertTrue(fresh.allocation_priority)
        self.assertEqual(fresh.allocation_priority_source_label, "人工")
        # 人工開啟起頭的車到期後仍為人工。
        aged_manual = self.vehicle("AGED-MANUAL", months_ago(8))
        self.set_override(aged_manual, True)
        self.assertEqual(aged_manual.allocation_priority_source_label, "人工")
        # 超過門檻一律優先：舊版留下的人工關閉值不再生效。
        legacy_off = self.vehicle("LEGACY-OFF", months_ago(8))
        self.set_override(legacy_off, False)
        self.assertTrue(legacy_off.allocation_priority)
        self.assertEqual(legacy_off.allocation_priority_source_label, "自動")
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
        self.vehicle("OLDER-NORMAL", months_ago(2))
        manual = self.vehicle("MANUAL", months_ago(0))
        self.set_override(manual, True)
        form = AllocationForm(order, {"vehicle": manual.pk})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["skip_notes"], [])

    def toggle(self, vehicle, value):
        return self.client.post(
            reverse("inventory_allocation_priority", args=[vehicle.pk]),
            {"priority": value},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

    def test_aged_vehicle_cannot_be_turned_off(self):
        old = self.vehicle("AGED", months_ago(6))
        self.client.force_login(self.user)
        response = self.toggle(old, "0")
        self.assertEqual(response.status_code, 400)
        self.assertIn("不能關閉", response.json()["message"])
        self.assertEqual(self.toggle(old, "1").json()["source"], "自動")
        old.refresh_from_db()
        self.assertIsNone(old.allocation_priority_override)
        self.assertFalse(VehicleInventoryHistory.objects.filter(vehicle=old, reason="切換優先配車").exists())

    def test_manual_on_then_off_returns_to_auto_when_aged(self):
        # 規則一：人工開啟後又關閉，到期自動開啟並標示「自動」。
        car = self.vehicle("RULE1", months_ago(1))
        self.client.force_login(self.user)
        self.assertEqual(self.toggle(car, "1").json()["source"], "人工")
        response = self.toggle(car, "0")
        self.assertEqual(response.json()["priority"], False)
        car.refresh_from_db()
        self.assertIsNone(car.allocation_priority_override)
        entries = VehicleInventoryHistory.objects.filter(vehicle=car, reason="切換優先配車").order_by("pk")
        self.assertEqual(
            [(h.changes["allocation_priority"]["before"], h.changes["allocation_priority"]["after"]) for h in entries],
            [("關閉", "開啟（人工）"), ("開啟（人工）", "關閉")],
        )
        VehicleInventory.objects.filter(pk=car.pk).update(manufactured_year_month=months_ago(6))
        car.refresh_from_db()
        self.assertTrue(car.allocation_priority)
        self.assertEqual(car.allocation_priority_source_label, "自動")

    def test_manual_on_off_on_stays_manual_and_locks_when_aged(self):
        # 規則二、三：人工開啟（含關掉再開）到期後仍為人工，且不能再關閉。
        car = self.vehicle("RULE2", months_ago(1))
        self.client.force_login(self.user)
        self.toggle(car, "1")
        self.toggle(car, "0")
        self.toggle(car, "1")
        VehicleInventory.objects.filter(pk=car.pk).update(manufactured_year_month=months_ago(6))
        car.refresh_from_db()
        self.assertTrue(car.allocation_priority)
        self.assertEqual(car.allocation_priority_source_label, "人工")
        self.assertEqual(self.toggle(car, "0").status_code, 400)
        car.refresh_from_db()
        self.assertIs(car.allocation_priority_override, True)
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
        # 超過門檻的開關鎖定不能關閉。
        self.assertEqual(html.count("data-priority-locked"), 1)
        history = self.client.get(reverse("inventory_list"), {"scope": "history"})
        self.assertNotContains(history, "優先配車規則")
