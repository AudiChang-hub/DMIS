"""使用者 2026-11-05 回報的畫面問題（T-121）。

1. 舊車出廠年月存好後輸入框變成「2012-02-01」、下方換算出現 NaN：自動儲存回傳要用畫面上的 6 碼 YYYYMM。
2. 配件列按「刪除」沒反應：配件區的版面規則蓋過了「待刪除列收起」，收起規則要一律優先。
"""
import datetime
from pathlib import Path

from django.test import SimpleTestCase

from sales.tests import test_old_manufactured_ym_t93 as t93


class OldVehicleYearMonthSyncTests(t93.OldVehicleYearMonthPageTests.__bases__[0]):
    setUp = t93.OldVehicleYearMonthPageTests.setUp
    make_order = t93.OldVehicleYearMonthPageTests.make_order
    login_admin = t93.OldVehicleYearMonthPageTests.login_admin
    save = t93.OldVehicleYearMonthPageTests.save

    def test_autosave_sync_returns_yyyymm(self):
        self.login_admin()
        order, _vehicle = self.make_order()
        response = self.save(order, "201202")
        self.assertEqual(response.status_code, 200, response.content)
        synced = response.json()["sync"]["operations"]["operations-old_vehicle_manufactured_on"]
        self.assertEqual(synced, "201202")
        order.operations.refresh_from_db()
        self.assertEqual(order.operations.old_vehicle_manufactured_on, datetime.date(2012, 2, 1))


class PendingDeleteRowTests(SimpleTestCase):
    def test_pending_delete_rows_always_hidden(self):
        css = Path("static/css/app.css").read_text(encoding="utf-8")
        self.assertIn(".dynamic-row.is-pending-delete { display: none !important; }", css)
        # 配件列本身是 dynamic-row（建單精靈與訂單頁共用），刪除後才會跟著收起。
        row = Path("templates/sales/_order_accessory_row.html").read_text(encoding="utf-8")
        self.assertIn('class="accessory-row dynamic-row', row)
