"""T-232：舊「匯出營運資料」網址改導到新的訂單匯出頁；舊測試沿用的取檔輔助。

走一遍使用者的實際流程：舊網址 → 導到匯出頁（帶入舊口徑的範圍）→ 預設欄位直接按「確認匯出」，
再把新檔案換回舊版面（去掉隱藏的欄位代碼列與 A 欄系統編號），讓舊測試照原本的欄位位置讀值。
"""
from io import BytesIO
from urllib.parse import parse_qs, urlsplit

from django.urls import reverse
from openpyxl import Workbook, load_workbook

from sales.order_exchange.columns import DEFAULT_COLUMNS
from sales.order_exchange.workbook import SHEET_TITLE


def legacy_export_sheet(client, params=None):
    redirected = client.get(reverse("operations_report_export"), params or {})
    assert redirected.status_code == 302, redirected.status_code
    target = urlsplit(redirected["Location"])
    assert target.path == reverse("order_export"), target.path
    data = {key: values for key, values in parse_qs(target.query).items()}
    data["cols"] = list(DEFAULT_COLUMNS)
    response = client.post(reverse("order_export_download"), data)
    assert response.status_code == 200, response.status_code
    sheet = load_workbook(BytesIO(response.content))[SHEET_TITLE]
    legacy = Workbook().active
    for row in sheet.iter_rows(min_row=2, values_only=True):
        legacy.append(list(row[1:]))
    return legacy
