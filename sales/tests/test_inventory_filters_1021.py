"""車輛庫存篩選列不破版（使用者 2026-10-21 投影片 T-63）。"""
from pathlib import Path

from django.test import SimpleTestCase

CSS = Path("static/css/app.css").read_text(encoding="utf-8")


class InventoryFilterLayoutTests(SimpleTestCase):
    def test_grid_wraps_by_available_width_and_keeps_buttons_right(self):
        self.assertIn(".inventory-filters.inventory-filters--stock { grid-template-columns: repeat(auto-fit, minmax(196px, 1fr)); }", CSS)
        self.assertIn(".inventory-filters.inventory-filters--stock > :is(.inventory-filter--search, .inventory-filter--sort) { grid-column: span 2; }", CSS)
        self.assertIn("> .inventory-filter-actions { grid-column: -2 / -1; justify-self: end;", CSS)
        # 複選後多出已選標籤的欄位變高，同列搜尋框仍對齊；按鈕前補一行欄名高度的空白。
        self.assertIn(".inventory-filters.inventory-filters--stock { align-items: start; }", CSS)
        self.assertIn('.inventory-filter-actions::before { flex-basis: 100%; font-size: var(--text-sm); font-weight: 900; content: "\\00a0"; }', CSS)
        self.assertNotIn("repeat(7, minmax(112px, 1fr))", CSS)

    def test_searchable_inputs_leave_room_for_icon_and_arrow(self):
        self.assertIn(".inventory-filter .searchable-select__input { min-height: 42px; padding-block: 0; padding-right: calc(var(--space-6) + var(--space-2)); text-overflow: ellipsis; }", CSS)
        self.assertIn(".inventory-filter .searchable-select__toggle { width: 40px; height: 42px; }", CSS)
        self.assertIn(".inventory-filter .searchable-select__search-icon { top: 21px; }", CSS)
        # 放大鏡對齊搜尋框而不是整個元件（下方有已選標籤時不再往下掉）。
        self.assertIn("position: absolute; z-index: 2; top: 24px; left: 15px;", CSS)
        self.assertNotIn("\x00", CSS)
