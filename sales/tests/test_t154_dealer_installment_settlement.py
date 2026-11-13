"""T-154（使用者 2026-11-12 選 B）：系統建立的分期車行單，牌險、選號、配件等由車行付的費用與傭金互抵。

使用者：「就算是選號費，也是要算在跟車行收款的費用裡。所以這裡付給車行的金額=800」。
分期總價本身仍固定、不扣傭金；掛帳（尾款）＝費用－傭金（不含台數獎金），傭金比費用多時尾款 0、差額付給車行；
T-150 給付列表的傭金拆成「抵扣／另付」。Excel 匯入單與現金單不變。
"""
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.utils import timezone

from sales.models import AccessoryLine, OrderOperationsProfile, PaymentRecord, SalesOrder
from sales.reporting import payouts
from sales.services.customer_receivable import customer_receivable_total, dealer_account_due
from sales.services.dealer_commission import apply_order_dealer_commission
from sales.services.dealer_credit import dealer_outstanding
from sales.services.dealer_settlement import dealer_settlement
from sales.services.operations_sync import sync_order_operations
from sales.services.payment_summary import payment_summary
from sales.tests import test_finance_ledger as ledger

INSTALLMENT = dict(
    payment_type="installment", installment_company="和潤", installment_amount=Decimal("79800"),
    installment_periods=24, installment_monthly=3600, plate_insurance_fee=Decimal("0"),
    payment_splits=[{"method": "installment", "amount": 79800}],
)


class DealerInstallmentBase(ledger.FinanceLedgerTestBase):
    """基底車行傭金 2,000＋品牌加成 300＝2,300。"""

    def order(self, v2=True, **kwargs):
        order = self.make_order(cash_receivable_v2=v2, **{**INSTALLMENT, **kwargs})
        apply_order_dealer_commission(order)
        sync_order_operations(order.pk)
        return SalesOrder.objects.get(pk=order.pk)

    def balance_row(self, order):
        return PaymentRecord.objects.get(order=order, system_key="balance").expected_amount


class DealerInstallmentSettlementTests(DealerInstallmentBase):
    def test_plate_selection_fee_offsets_commission(self):
        # 截圖 SO20261111-60DB77：選號 1,200、傭金 2,000 → 付給車行 800（此處傭金 2,300 → 1,100）。
        order = self.order(plate_choice="watch", plate_selection_fee=Decimal("1200"))
        settlement = dealer_settlement(order)
        self.assertEqual([term["key"] for term in settlement["terms"]], ["plate_selection", "accessories", "commission"])
        self.assertEqual((settlement["total"], settlement["label"], settlement["amount"]), (-1100, "付給車行", 1100))
        self.assertTrue(settlement["installment_fees"])
        self.assertEqual(dealer_account_due(order), Decimal("-1100"))
        # 選號費已從付給車行的錢扣掉，不再向車行收。
        self.assertEqual(self.balance_row(order), 0)
        summary = payment_summary(order)
        self.assertEqual(summary["customer_due"], 0)
        self.assertEqual(customer_receivable_total(order), 0)
        # 分期公司撥款不變（分期總價固定）。
        self.assertEqual(PaymentRecord.objects.get(order=order, system_key="installment_disbursement").expected_amount,
                         summary["lender_expected"])
        self.assertGreater(summary["lender_expected"], 0)

    def test_fees_exceeding_commission_leave_the_difference_to_collect(self):
        order = self.order(plate_insurance_fee=Decimal("1369"), plate_choice="watch", plate_selection_fee=Decimal("1200"))
        AccessoryLine.objects.create(order=order, name="後架", amount=1000, labor_fee=200)
        order = SalesOrder.objects.get(pk=order.pk)
        sync_order_operations(order.pk)
        settlement = dealer_settlement(order)
        self.assertEqual([term["key"] for term in settlement["terms"]],
                         ["plate_insurance", "plate_selection", "accessories", "commission"])
        # 1,369＋1,200＋1,200－2,300
        self.assertEqual((settlement["total"], settlement["label"]), (1469, "向車行收"))
        self.assertEqual(self.balance_row(order), 1469)

    def test_deposit_is_deducted_from_balance(self):
        order = self.order(plate_insurance_fee=Decimal("3000"), deposit_amount=Decimal("500"))
        # 3,000－2,300＝700，訂金 500 → 尾款 200；結算卡不扣訂金。
        self.assertEqual(dealer_settlement(order)["total"], 700)
        self.assertEqual(self.balance_row(order), 200)
        self.assertEqual(customer_receivable_total(order), 700)

    def test_volume_bonus_is_paid_separately_not_offset(self):
        with patch("sales.services.dealer_commission.commission_volume_bonus", return_value=Decimal("500")):
            order = self.order(plate_insurance_fee=Decimal("3000"))
            OrderOperationsProfile.objects.filter(order=order).update(dealer_commission_expense=2800)
            order = SalesOrder.objects.get(pk=order.pk)
            # 卡片列傭金全額 2,800（含獎金），掛帳只扣 2,300。
            self.assertEqual(dealer_settlement(order)["total"], 200)
            self.assertEqual(dealer_account_due(order), Decimal("700"))

    def test_commission_change_resyncs_unpaid_balance_row(self):
        order = self.order(plate_insurance_fee=Decimal("3000"))
        self.assertEqual(self.balance_row(order), 700)
        self.model.base_dealer_commission = Decimal("500")
        self.model.save(update_fields=["base_dealer_commission"])
        apply_order_dealer_commission(SalesOrder.objects.get(pk=order.pk))
        self.assertEqual(self.balance_row(order), 2200)

    def test_dealer_credit_outstanding_drops_the_offset_fees(self):
        order = self.order(plate_choice="watch", plate_selection_fee=Decimal("1200"))
        SalesOrder.all_objects.filter(pk=order.pk).update(status="completed")
        self.assertEqual(dealer_outstanding(self.dealer.pk), 0)

    def test_old_orders_keep_accessories_minus_commission(self):
        order = self.order(v2=False, plate_choice="watch", plate_selection_fee=Decimal("1200"))
        settlement = dealer_settlement(order)
        self.assertEqual([term["key"] for term in settlement["terms"]], ["accessories", "commission"])
        self.assertFalse(settlement["installment_fees"])
        self.assertIsNone(dealer_account_due(order))

    def test_store_installment_orders_are_unchanged(self):
        order = self.make_order(cash_receivable_v2=True, source_type="store", source=self.staff,
                                **{**INSTALLMENT, "plate_choice": "watch", "plate_selection_fee": Decimal("1200")})
        sync_order_operations(order.pk)
        self.assertIsNone(dealer_account_due(order))
        self.assertEqual(self.balance_row(order), 1200)


class DealerInstallmentPayoutTests(DealerInstallmentBase):
    def registered(self, **kwargs):
        order = self.order(**kwargs)
        SalesOrder.all_objects.filter(pk=order.pk).update(
            registration_date=date(2026, 10, 20), registration_completed_at=timezone.now(), status="completed")
        return SalesOrder.objects.get(pk=order.pk)

    def item(self, order):
        return payouts.current_item(f"commission:order:{order.pk}")

    def test_commission_split_into_deduction_and_separate(self):
        item = self.item(self.registered(plate_choice="watch", plate_selection_fee=Decimal("1200")))
        self.assertEqual((item.amount, item.deduction_amount, item.separate_amount), (2300, 1200, 1100))
        self.assertEqual(item.methods, ("deduction", "separate"))
        self.assertEqual(item.method_label, "抵扣 $1,200／另付 $1,100")
        keys = lambda method: [i.source_key for i in payouts.filter_items(payouts.collect_items(), method=method)]
        self.assertIn(item.source_key, keys("deduction"))
        self.assertIn(item.source_key, keys("separate"))

    def test_full_deduction_and_no_fees(self):
        full = self.item(self.registered(plate_insurance_fee=Decimal("3000")))
        self.assertEqual((full.deduction_amount, full.method_label), (2300, "抵扣應收"))
        none = self.item(self.registered())
        self.assertEqual((none.deduction_amount, none.method_label), (0, "另付"))

    def test_deposit_already_received_is_not_offset(self):
        item = self.item(self.registered(plate_insurance_fee=Decimal("1500"), deposit_amount=Decimal("500")))
        self.assertEqual((item.deduction_amount, item.separate_amount), (1000, 1300))
