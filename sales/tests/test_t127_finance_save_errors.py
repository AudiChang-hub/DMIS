"""T-127（使用者 2026-11-07 UAT p2，SO20261107-91529C）：收款自動儲存失敗時，原因一定要看得到。

訂單來源改成平台又改回本店時，同步建立又刪掉了平台撥款列；畫面還留著那一列，新增收款送出時錯誤落在隱藏的
列編號上，狀態列只寫「請依欄位旁的紅字修正」卻沒有任何紅字。改成回 409 與明確訊息，請使用者重新整理。"""
from django.test import TestCase
from django.urls import reverse

from sales.models import PaymentRecord
from sales.services.order_workspace import STALE_PAYMENT_ROWS_MESSAGE
from sales.tests import test_order_workspace as workspace_fixtures
from sales.tests import test_receipt_list as receipt_list


class FinanceSaveErrorTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        workspace_fixtures.OrderWorkspaceTests.setUpTestData.__func__(cls)

    setUp = receipt_list.ReceiptListTests.setUp
    payload = receipt_list.ReceiptListTests.payload

    def add_receipt(self, payload):
        index = int(payload["payments-TOTAL_FORMS"])
        payload.update({"payments-TOTAL_FORMS": str(index + 1),
                        f"payments-{index}-item_name": "收款", f"payments-{index}-receipt_kind": "customer",
                        f"payments-{index}-received_amount": "10000", f"payments-{index}-received_on": "2026-11-03",
                        f"payments-{index}-payment_method": "匯款", f"payments-{index}-confirmed": "on"})
        return payload

    def test_row_removed_by_sync_returns_clear_message(self):
        PaymentRecord.objects.create(order=self.order, system_key="platform_disbursement", item_name="平台撥款")
        payload = self.add_receipt(self.payload())
        PaymentRecord.objects.filter(order=self.order, system_key="platform_disbursement").delete()
        # 其他區塊（訂單資料）自動儲存後，版本號已在畫面上更新，但收款列還是舊的。
        payload["operations-financial_revision"] = self.payload()["operations-financial_revision"]
        response = self.client.post(reverse("order_operations", args=[self.order.pk]), payload, HTTP_X_ORDER_WORKSPACE="1")
        self.assertEqual(response.status_code, 409, response.content)
        self.assertEqual(response.json()["error"], STALE_PAYMENT_ROWS_MESSAGE)
        self.assertEqual(response.json()["errors"], {})
        self.assertFalse(self.order.payment_records.filter(item_name="收款").exists())

    def test_normal_receipt_still_saves(self):
        response = self.client.post(reverse("order_operations", args=[self.order.pk]), self.add_receipt(self.payload()),
                                    HTTP_X_ORDER_WORKSPACE="1")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(self.order.payment_records.filter(item_name="收款", confirmed=True).exists())
