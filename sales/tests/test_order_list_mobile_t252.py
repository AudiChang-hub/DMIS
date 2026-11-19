"""T-252（使用者 2026-11-19）：手機版全部訂單頁。

日期迄超出卡片右緣：iOS Safari 的原生日期欄位（appearance: auto）以自身內容決定寬度，不理會 width: 100%／min-width: 0，
放在兩欄的篩選格裡就會撐出卡片。訂單表單的 .form-control 日期欄早已用 display: block＋appearance: none 修過（f8202c91），
全部訂單的篩選日期欄不是 .form-control，沒有套到。
"""
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

STATIC = Path(settings.BASE_DIR) / "static"


def mobile_rule(css, selector):
    """回傳 @media (max-width: 860px) 區塊內指定選擇器的宣告。"""
    for block in re.finditer(r"@media \(max-width: 860px\) \{(.*?)\n\}", css, re.S):
        match = re.search(re.escape(selector) + r" \{([^}]*)\}", block.group(1))
        if match:
            return match.group(1)
    return ""


class OrderFilterDateWidthTests(SimpleTestCase):
    def test_mobile_date_inputs_drop_native_appearance_and_stay_inside_card(self):
        css = (STATIC / "css/app.css").read_text(encoding="utf-8")
        rule = mobile_rule(css, ".order-filter-bar input[type=date]")
        self.assertIn("display: block", rule)
        self.assertIn("-webkit-appearance: none", rule)
        self.assertIn("appearance: none", rule)
        self.assertIn("max-width: 100%", rule)
