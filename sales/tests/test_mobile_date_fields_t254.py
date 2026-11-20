"""T-254（使用者 2026-11-19「6 個日期欄一起修」）：手機（iOS Safari）原生日期欄依內容決定寬度、不理會 width: 100%，
放在兩欄的窄格裡會撐出卡片（T-252 全部訂單「日期迄」同一根因）。

375 寬實測各頁日期欄寬度：撥款對帳 153px、車行給付 157px、機種工具（批次、分期批次）153px，與全部訂單出問題時的 151px
同一級，套 T-252 的修法；進車紀錄、調車簽收（317px 整列）、營業日設定（214／313px）寬度足夠，不動。
"""
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

APP_CSS = Path(settings.BASE_DIR) / "static" / "css" / "app.css"


def mobile_rules(css):
    return "".join(block.group(1) for block in re.finditer(r"@media \(max-width: 860px\) \{(.*?)\n\}", css, re.S))


class MobileDateFieldWidthTests(SimpleTestCase):
    def test_narrow_two_column_date_fields_drop_native_appearance(self):
        rules = mobile_rules(APP_CSS.read_text(encoding="utf-8"))
        match = re.search(r":is\(([^)]*)\) input\[type=date\] \{([^}]*)\}", rules)
        self.assertIsNotNone(match)
        containers = {name.strip() for name in match.group(1).split(",")}
        self.assertEqual(containers, {".operations-filters", ".payout-filters", ".model-tool-filters"})
        for declaration in ("display: block", "-webkit-appearance: none", "appearance: none", "max-width: 100%", "min-width: 0"):
            self.assertIn(declaration, match.group(2))

    def test_wide_date_fields_are_left_alone(self):
        rules = mobile_rules(APP_CSS.read_text(encoding="utf-8"))
        for untouched in (".holiday-calendar", ".receipt-filters", "transfer-signoff"):
            self.assertNotRegex(rules, re.escape(untouched) + r"[^{]*input\[type=date\]")
