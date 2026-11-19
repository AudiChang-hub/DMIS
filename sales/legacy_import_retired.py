"""T-243：舊營運 Excel 匯入（銷貨、進貨）停用，批次修改改用全部訂單的匯出／匯回（T-232）；車行／網路平台名冊匯入保留。

- 上傳：只收名冊；送營運 Excel 一律導回全部訂單並說明，不建立批次。
- 批次頁（預覽、狀態、確認、刪除、封存、來源檔、逐列修正、主檔對應）：名冊批次照常；營運批次導回，不執行原本的 view。
- 只屬銷貨的功能（既有訂單比對、換買家、改領牌日）一律導回。
匯入程式（services/legacy_import.py）、model 與已匯入的資料都保留。
`LEGACY_IMPORT_UI_ENABLED` 只給保留下來的營運匯入測試用，正式設定不定義它。
"""
from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect

RETIRED_MESSAGE = "舊 Excel 匯入已停用，批次修改請用全部訂單的匯出／匯回。"


def operations_import_enabled():
    return getattr(settings, "LEGACY_IMPORT_UI_ENABLED", False)


def _retired_response(request):
    messages.info(request, RETIRED_MESSAGE)
    return redirect("order_list")


def retired(view):
    """只屬營運匯入的路由：一律導回。"""
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if operations_import_enabled():
            return view(request, *args, **kwargs)
        return _retired_response(request)
    return wrapper


def channels_only_upload(view):
    """上傳頁：GET 照常（只剩名冊），POST 不是名冊就導回。"""
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        from sales.models import LegacyImportBatch
        if (not operations_import_enabled() and request.method == "POST"
                and request.POST.get("import_type") != LegacyImportBatch.ImportType.CHANNELS):
            return _retired_response(request)
        return view(request, *args, **kwargs)
    return wrapper


def channels_batch_only(view):
    """批次路由：名冊批次照常，營運批次導回。"""
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        from sales.models import LegacyImportBatch
        if not operations_import_enabled():
            batch = get_object_or_404(LegacyImportBatch.objects.only("import_type"), pk=kwargs["pk"])
            if batch.import_type != LegacyImportBatch.ImportType.CHANNELS:
                return _retired_response(request)
        return view(request, *args, **kwargs)
    return wrapper
