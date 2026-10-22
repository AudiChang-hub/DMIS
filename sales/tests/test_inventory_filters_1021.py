"""車輛庫存篩選列不破版（使用者 2026-10-21 投影片 T-63；10-22 T-66 縮短搜尋、按鈕改在欄位群組外）。"""
from pathlib import Path

from django.test import SimpleTestCase

CSS = Path("static/css/app.css").read_text(encoding="utf-8")


class InventoryFilterLayoutTests(SimpleTestCase):
    def test_grid_wraps_by_available_width_and_keeps_buttons_right(self):
        self.assertIn(".inventory-filter-fields { display: grid; min-width: 0; grid-template-columns: minmax(200px, 1.3fr) repeat(auto-fit, minmax(164px, 1fr)); align-items: start; gap: var(--space-3); }", CSS)
        self.assertIn("> .inventory-filter-actions { grid-column: auto; justify-self: end;", CSS)
        # 按鈕前補一行欄名高度的空白，與搜尋框齊平。
        self.assertIn('.inventory-filter-actions::before { flex-basis: 100%; font-size: var(--text-sm); font-weight: 900; content: "\\00a0"; }', CSS)
        self.assertNotIn("repeat(7, minmax(112px, 1fr))", CSS)
        self.assertNotIn("repeat(auto-fit, minmax(196px, 1fr))", CSS)

    def test_searchable_inputs_leave_room_for_icon_and_arrow(self):
        self.assertIn(".inventory-filter .searchable-select__input { min-height: 42px; padding-block: 0; padding-right: calc(var(--space-6) + var(--space-2)); text-overflow: ellipsis; }", CSS)
        self.assertIn(".inventory-filter .searchable-select__toggle { width: 40px; height: 42px; }", CSS)
        self.assertIn(".inventory-filter .searchable-select__search-icon { top: 21px; }", CSS)
        self.assertIn("position: absolute; z-index: 2; top: 24px; left: 15px;", CSS)
        self.assertNotIn("\x00", CSS)
