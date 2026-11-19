"""T-243：舊 Excel 匯入（營運進銷貨與車行名冊）停用，批次修改改用全部訂單的匯出／匯回（T-232）。

舊網址（上傳、預覽、確認、結果頁與預覽中的逐列修正）一律導回全部訂單並說明，GET、POST 都不執行原本的 view，
所以不會再建立批次或寫入資料。匯入程式（services/legacy_import.py）、model 與已匯入的資料都保留。
`LEGACY_IMPORT_UI_ENABLED` 只給保留下來的舊匯入測試用，正式設定不定義它。
"""
from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.shortcuts import redirect

RETIRED_MESSAGE = "舊 Excel 匯入已停用，批次修改請用全部訂單的匯出／匯回。"


def retired(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if getattr(settings, "LEGACY_IMPORT_UI_ENABLED", False):
            return view(request, *args, **kwargs)
        messages.info(request, RETIRED_MESSAGE)
        return redirect("order_list")
    return wrapper
