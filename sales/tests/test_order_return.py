"""交車後退車與匯入錯誤作廢（1.86.22，使用者 2026-10-19 選方案 A）。"""
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from sales.access.models import ScreenAccessGrant, UserAccessState
from sales.models import (
    DealerVolumeBonusAllocation, DealerVolumeBonusRule, DealerVolumeBonusSettlement, DealerVolumeBonusTier,
    LegacyImportBatch, LegacyImportRow, LegacySalesSnapshot, OrderChange, OrderEvent, OrderOperationsProfile,
    PaymentRecord, SalesOrder, SalesSource, Store, SubsidyItem, VehicleColor, VehicleInventory, VehicleModel,
)
from sales.reporting.engine import EXCLUDED_STATUSES
from sales.services.order_deletion import (DELIVERED_BLOCKER, change_deletion, confirmation_token,
                                           permanent_deletion_blockers)
from sales.services.order_return import EVENT_TYPE, return_after_delivery, return_blockers
from sales.services.order_tabs import tab_filter
from sales.services.sales_metrics import CANCELLED_STATUSES

Status = SalesOrder.Status


class ReturnFixtures:
    @classmethod
    def setUpTestData(cls):
        cls.root = get_user_model().objects.create_superuser("admin", password="Return-test-only-482!")
        cls.staff = get_user_model().objects.create_user("staff")
        UserAccessState.objects.create(user=cls.staff, configured=True)
        ScreenAccessGrant.objects.create(user=cls.staff, screen_key="work", view=True, operate=True)
        cls.model = VehicleModel.objects.create(brand="QA", name="退車測試車", model_year=2026)
        cls.color = VehicleColor.objects.create(vehicle_model=cls.model, name="白")
        cls.store = Store.objects.create(name="合成門市")

    def setUp(self):
        self.client.force_login(self.root)

    def vehicle(self, status=VehicleInventory.Status.DELIVERED, frame="QA-RET-AB1234"):
        return VehicleInventory.objects.create(vehicle_model=self.model, color=self.color, ownership_store=self.store,
                                               location_store=self.store, status=status, frame_number=frame)

    def delivered_order(self, vehicle=None, **extra):
        now = timezone.now()
        fields = dict(owner_name="合成客戶", owner_phone="0900000000", owner_address="合成地址", owner_id_number="A123456789",
                      vehicle_model=self.model, color=self.color, status=Status.COMPLETED, allocated_vehicle=vehicle,
                      final_plate_number="QAA-0001", registration_date=date(2026, 9, 1), registration_completed_at=now,
                      delivered_at=now, delivered_by="交車人員", closed_at=now, closed_by="結案人員")
        fields.update(extra)
        order = SalesOrder.objects.create(**fields)
        SalesOrder.objects.filter(pk=order.pk).update(**{k: v for k, v in fields.items() if k in {"status", "closed_at", "closed_by"}})
        order.refresh_from_db()
        return order

    def receipt(self, order, amount, kind="customer", confirmed=True):
        return PaymentRecord.objects.create(order=order, item_name="收款", received_amount=Decimal(amount), receipt_kind=kind,
                                            received_on=date(2026, 9, 1), payment_method="匯款", confirmed=confirmed)

    def imported(self, order, identifier="", **extra):
        batch = LegacyImportBatch.objects.create(import_type="operations", original_filename="synthetic.xlsx", file_size=0)
        row = LegacyImportRow.objects.create(batch=batch, sheet_name="銷貨", source_row=order.pk, fingerprint=f"return-{order.pk}")
        LegacySalesSnapshot.objects.create(order=order, import_row=row, vehicle_identifier=identifier, **extra)
        return SalesOrder.objects.get(pk=order.pk)

    def do_return(self, order, **extra):
        order.refresh_from_db()
        payload = dict(user=self.root, order_id=order.pk, reason="交車後車況爭議，客戶退車", refunded_on=date(2026, 10, 19),
                       expected_updated_at=order.updated_at.isoformat(), confirm_identifier="1234", resale_price=52000,
                       actor_name="管理員")
        payload.update(extra)
        result = return_after_delivery(**payload)
        order.refresh_from_db()
        return result



class OrderReturnTests(ReturnFixtures, TestCase):
    def test_return_refunds_releases_registered_vehicle_and_leaves_reports(self):
        vehicle = self.vehicle()
        order = self.delivered_order(vehicle)
        self.receipt(order, "50000")
        self.assertEqual(return_blockers(order), [])
        self.do_return(order, forfeited_amount=5000, forfeit_reason="車損折舊", method=SalesOrder.PaymentMethod.TRANSFER,
                       reference="末五碼 12345")
        vehicle.refresh_from_db()
        self.assertEqual(order.status, Status.EXCEPTION_CLOSED)
        self.assertTrue(order.is_returned_after_delivery)
        self.assertEqual(order.display_status, "已退車")
        self.assertTrue(order.is_cancelled_sale)
        self.assertIsNone(order.closed_at)
        self.assertIsNone(order.allocated_vehicle_id)
        self.assertEqual(order.exception_vehicle_id, vehicle.pk)
        self.assertEqual((order.refund_amount, order.forfeited_amount), (Decimal("45000"), Decimal("5000")))
        self.assertEqual(order.payment_records.get(entry_type="refund").received_amount, Decimal("-45000"))
        self.assertEqual((vehicle.status, vehicle.registered_plate_number, vehicle.resale_price),
                         (VehicleInventory.Status.AVAILABLE, "QAA-0001", Decimal("52000")))
        self.assertIn("交車後退車", vehicle.history_entries.get().reason)
        change = OrderChange.objects.get(order=order)
        self.assertEqual(change.changes["訂單狀態"]["after"], "已退車（例外結案）")
        self.assertIn("確認結案", change.changes)
        self.assertTrue(OrderEvent.objects.filter(order=order, event_type=EVENT_TYPE, description__contains="退車前").exists())
        # 有效售出、報表與列表頁籤都靠例外結案排除。
        self.assertIn(order.status, CANCELLED_STATUSES)
        self.assertIn(order.status, EXCLUDED_STATUSES)
        self.assertTrue(SalesOrder.objects.filter(tab_filter("cancelled"), pk=order.pk).exists())
        self.assertFalse(SalesOrder.objects.filter(tab_filter("closed"), pk=order.pk).exists())
        # 退車後不能再退，也不能刪除（已交車）。
        with self.assertRaises(ValidationError):
            self.do_return(order)
        self.assertIn(DELIVERED_BLOCKER, permanent_deletion_blockers(order))
        page = self.client.get(reverse("order_detail", args=[order.pk]))
        self.assertContains(page, "交車後退車")
        self.assertContains(page, "已退車")

    def test_only_admin_and_identifier_reason_and_version_checked(self):
        order = self.delivered_order(self.vehicle())
        with self.assertRaises(PermissionDenied):
            self.do_return(order, user=self.staff)
        with self.assertRaisesMessage(ValidationError, "備註最多"):
            self.do_return(order, reason="x" * 501)
        with self.assertRaisesMessage(ValidationError, "訂單已被更新"):
            self.do_return(order, expected_updated_at="2000-01-01T00:00:00+00:00")
        with self.assertRaisesMessage(ValidationError, "末 4 碼"):
            self.do_return(order, confirm_identifier="9999")
        with self.assertRaisesMessage(ValidationError, "再售價"):
            self.do_return(order, resale_price=None)
        self.assertEqual(order.status, Status.COMPLETED)
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(reverse("order_return", args=[order.pk])).status_code, 403)
        self.client.force_login(self.root)
        self.assertContains(self.client.get(reverse("order_detail", args=[order.pk])), reverse("order_return", args=[order.pk]))

    def test_blockers_and_money_rules(self):
        pending = self.delivered_order(status=Status.DELIVERY_PENDING, delivered_at=None, delivered_by="", closed_at=None)
        self.assertIn("還沒交車", return_blockers(pending)[0][0])
        order = self.delivered_order(self.vehicle())
        self.receipt(order, "30000")
        unconfirmed = self.receipt(order, "1000", confirmed=False)
        self.assertTrue(any("未確認" in text for text, _url, _label in return_blockers(order)))
        unconfirmed.delete()
        with self.assertRaisesMessage(ValidationError, "沒收金額須介於"):
            self.do_return(order, forfeited_amount=30001, forfeit_reason="x", method="cash")
        with self.assertRaisesMessage(ValidationError, "退款方式"):
            self.do_return(order)
        SubsidyItem.objects.create(order=order, category=SubsidyItem.Category.LOCAL, item_name="汰舊", expected_amount=1000)
        with self.assertRaisesMessage(ValidationError, "補助"):
            self.do_return(order, method="cash")
        self.do_return(order, method="cash", subsidy_handled=True, forfeited_amount=30000, forfeit_reason="全額沒收")
        self.assertEqual(order.refund_amount, 0)
        self.assertFalse(order.payment_records.filter(entry_type="refund").exists())
        self.assertIn("補助已確認撤回", OrderEvent.objects.get(order=order, event_type=EVENT_TYPE).description)

    def test_installment_requires_lender_clawback_and_zeroes_disbursement(self):
        from sales.services.operations_sync import sync_payment_financials
        order = self.delivered_order(self.vehicle(), payment_type=SalesOrder.PaymentType.INSTALLMENT)
        self.receipt(order, "60000", kind="lender")
        profile, _ = OrderOperationsProfile.objects.get_or_create(order=order)
        OrderOperationsProfile.objects.filter(pk=profile.pk).update(actual_disbursement=60000)
        with self.assertRaisesMessage(ValidationError, "分期公司沖回金額"):
            self.do_return(order)
        with self.assertRaisesMessage(ValidationError, "分期公司沖回金額"):
            self.do_return(order, lender_clawback=60001)
        self.do_return(order, lender_clawback=60000, lender_reference="解約 001")
        profile.refresh_from_db()
        self.assertEqual(profile.actual_disbursement, 0)
        self.assertIn("actual_disbursement", profile.manual_financial_fields)
        self.assertEqual(order.payment_records.get(entry_type="refund", receipt_kind="lender").received_amount, Decimal("-60000"))
        self.assertEqual(OrderChange.objects.get(order=order).changes["實際撥款"], {"before": "60,000", "after": "0"})
        sync_payment_financials(order.pk)
        profile.refresh_from_db()
        self.assertEqual(profile.actual_disbursement, 0)

    def test_imported_order_finds_vehicle_by_identifier_or_only_records(self):
        sold = self.vehicle(VehicleInventory.Status.SOLD, frame="LEG-0009")
        order = self.imported(self.delivered_order(delivered_by="歷史資料匯入"), identifier="leg-0009")
        self.do_return(order, confirm_identifier="0009")
        sold.refresh_from_db()
        self.assertEqual(order.exception_vehicle_id, sold.pk)
        self.assertEqual(sold.status, VehicleInventory.Status.AVAILABLE)

        missing = self.imported(self.delivered_order(payment_type=SalesOrder.PaymentType.INSTALLMENT,
                                                     delivered_at=None, delivered_by="歷史資料匯入"), identifier="NOT-IN-STOCK")
        OrderOperationsProfile.objects.update_or_create(order=missing, defaults={"actual_disbursement": 45000})
        self.do_return(missing, confirm_identifier="TOCK", resale_price=None, lender_clawback=45000)
        self.assertIsNone(missing.exception_vehicle_id)
        self.assertEqual(missing.display_status, "已退車")
        self.assertFalse(missing.payment_records.filter(entry_type="refund").exists(), "帳本沒有撥款就不寫負向列")
        self.assertEqual(OrderOperationsProfile.objects.get(order=missing).actual_disbursement, 0)
        self.assertEqual(VehicleInventory.objects.count(), 1, "車不在庫存時不新建庫存車")
        self.assertContains(self.client.get(reverse("order_detail", args=[missing.pk])), "不在庫存，只記錄退車")

    def test_imported_order_allows_manual_refund_within_excel_cap(self):
        order = self.imported(self.delivered_order(delivered_by="歷史資料匯入"), identifier="NO-STOCK-0042",
                              historical_received_price=85000, cash_received=20000, card_received=0)
        self.receipt(order, "20000")
        with self.assertRaisesMessage(ValidationError, "手填應退金額須為 1～85,000"):
            self.do_return(order, confirm_identifier="0042", manual_refund=85001, manual_refund_reason="x", method="cash")
        with self.assertRaisesMessage(ValidationError, "不另計沒收"):
            self.do_return(order, confirm_identifier="0042", manual_refund=60000, manual_refund_reason="x",
                           forfeited_amount=1000, forfeit_reason="y", method="cash")
        with self.assertRaisesMessage(ValidationError, "退款方式"):
            self.do_return(order, confirm_identifier="0042", manual_refund=60000, manual_refund_reason="Excel 收款價扣折舊")
        page = self.client.get(reverse("order_return", args=[order.pk]))
        self.assertContains(page, "手填應退金額")
        self.assertContains(page, "收款價 $85,000")
        self.do_return(order, confirm_identifier="0042", manual_refund=60000, manual_refund_reason="Excel 收款價扣折舊",
                       method="cash", resale_price=None)
        self.assertEqual(order.refund_amount, Decimal("60000"))
        refund = order.payment_records.get(entry_type="refund")
        self.assertEqual(refund.received_amount, Decimal("-60000"))
        self.assertIn("手填應退 60,000", refund.adjustment_reason)
        change = OrderChange.objects.get(order=order)
        self.assertEqual(change.changes["應退金額（手填）"], {"before": "帳本計算 20,000", "after": "60,000；Excel 收款價扣折舊"})
        self.assertIn("手填應退 60,000 元（帳本計算 20,000 元），備註：Excel 收款價扣折舊",
                      OrderEvent.objects.get(order=order, event_type=EVENT_TYPE).description)

    def test_system_order_cannot_use_manual_refund(self):
        order = self.delivered_order(self.vehicle())
        self.receipt(order, "30000")
        with self.assertRaisesMessage(ValidationError, "只有 Excel 匯入的訂單可以手填"):
            self.do_return(order, manual_refund=1000, manual_refund_reason="x", method="cash")
        self.assertNotContains(self.client.get(reverse("order_return", args=[order.pk])), "手填應退金額")

    def test_settled_volume_bonus_is_deducted_like_deletion(self):
        dealer = SalesSource.objects.create(name="合成車行", source_type="dealer")
        rule = DealerVolumeBonusRule.objects.create(dealer=dealer, starts_on=date(2026, 9, 1), ends_on=date(2026, 9, 30))
        DealerVolumeBonusTier.objects.create(rule=rule, minimum_quantity=1, bonus_per_vehicle=100)
        DealerVolumeBonusTier.objects.create(rule=rule, minimum_quantity=2, bonus_per_vehicle=200)
        settlement = DealerVolumeBonusSettlement.objects.create(rule=rule, dealer=dealer, qualified_quantity=2,
                                                                expected_amount=400, actual_amount=400, bonus_per_vehicle=200)
        order = self.delivered_order(self.vehicle())
        mine = DealerVolumeBonusAllocation.objects.create(settlement=settlement, order=order, amount=200)
        other = SalesOrder.objects.create(
            owner_name="其他", owner_phone="0", owner_address="x", owner_id_number="B123456789", vehicle_model=self.model, color=self.color)
        DealerVolumeBonusAllocation.objects.create(settlement=settlement, order=other, amount=200)
        self.do_return(order)
        settlement.refresh_from_db()
        mine = DealerVolumeBonusAllocation.all_objects.get(pk=mine.pk)
        self.assertIsNotNone(mine.voided_at)
        self.assertEqual((settlement.qualified_quantity, settlement.actual_amount), (1, 200))
        self.assertTrue(settlement.adjustments.filter(reason__contains="交車後退車").exists())

    def test_confirm_page_get_and_post(self):
        vehicle = self.vehicle()
        order = self.delivered_order(vehicle)
        url = reverse("order_return", args=[order.pk])
        page = self.client.get(url)
        self.assertContains(page, "交車後退車")
        self.assertContains(page, "領牌車再售價")
        self.assertNotContains(page, "分期公司沖回金額")
        response = self.client.post(url, {
            "expected_updated_at": order.updated_at.isoformat(), "refunded_on": "2026-10-19", "resale_price": "50000",
            "reason": "客戶退車", "confirm_identifier": "1234",
        })
        self.assertRedirects(response, reverse("order_detail", args=[order.pk]), fetch_redirect_response=False)
        order.refresh_from_db()
        self.assertEqual(order.status, Status.EXCEPTION_CLOSED)
        blocked = self.client.get(url)
        self.assertContains(blocked, "目前不能退車")


class ImportedOrderVoidTests(ReturnFixtures, TestCase):
    """匯入錯誤的歷史已完成單：admin 可作廢（軟刪除、可還原），一般已交車單仍不能刪。"""

    def test_imported_delivered_order_can_be_voided_and_restored(self):
        order = self.imported(self.delivered_order(delivered_by="歷史資料匯入"), identifier="IMP-1")
        self.receipt(order, "40000")
        self.assertNotIn(DELIVERED_BLOCKER, permanent_deletion_blockers(order))
        change_deletion(user=self.root, order_id=order.pk, restore=False, force=True, reason="Excel 匯入錯誤",
                        expected_updated_at=order.updated_at.isoformat(), confirmation=confirmation_token(order, self.root))
        self.assertFalse(SalesOrder.objects.filter(pk=order.pk).exists())
        deleted = SalesOrder.all_objects.get(pk=order.pk)
        change_deletion(user=self.root, order_id=order.pk, restore=True, reason="誤刪",
                        expected_updated_at=deleted.updated_at.isoformat())
        self.assertTrue(SalesOrder.objects.filter(pk=order.pk, status=Status.COMPLETED).exists())

    def test_forfeited_imported_order_still_cannot_be_deleted(self):
        order = self.imported(self.delivered_order(forfeited_amount=1000))
        self.assertEqual(len(permanent_deletion_blockers(order)), 1)
        self.assertNotIn(DELIVERED_BLOCKER, permanent_deletion_blockers(order))

    def test_system_delivered_order_still_blocked(self):
        order = self.delivered_order()
        self.assertIn(DELIVERED_BLOCKER, permanent_deletion_blockers(order))
