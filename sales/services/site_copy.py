"""可維護說明的固定白名單，不接受任意模板、HTML 或程式片段。"""
import json
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def catalog():
    return json.loads((Path(__file__).resolve().parent.parent / "site_copy_catalog.json").read_text(encoding="utf-8"))


def text_for(request, key):
    from sales.models import SiteTextOverride
    entries = catalog()
    if key not in entries:
        return ""
    if not hasattr(request, "_site_text_overrides"):
        request._site_text_overrides = dict(SiteTextOverride.objects.values_list("key", "text"))
    return request._site_text_overrides.get(key, entries[key]["default"])


def print_copy(pdf, key, default):
    from types import SimpleNamespace
    if not hasattr(pdf, "_site_copy_context"):
        pdf._site_copy_context = SimpleNamespace()
    code = "print." + key
    return text_for(pdf._site_copy_context, code) if code in catalog() else default


# 說明文字管理頁的頁籤：依文字實際所在的頁面歸到 8 個區域（使用者 2026-10-13）。
COPY_AREAS = (
    ("order", "訂單", ("訂單", "選一台適合的車", "台數歸屬", "接待", "刪除審核", "營運資料", "核對領牌改期", "退訂換買家", "解鎖淨利")),
    ("print", "列印文件", ("列印", "機車訂購合約")),
    ("vehicle", "車輛與庫存", ("車輛", "快速進車", "機種", "售價版本", "選車展示", "車款展示", "展示圖片", "配件")),
    ("dealer", "車行與通路", ("車行", "合作車行", "通路", "年節送禮", "分配與排序", "台數獎金")),
    ("finance", "財務與規則", ("分期", "原廠獎勵", "領牌與強制險", "工作日與假日", "統一撥款對帳")),
    ("home", "首頁與報表", ("首頁", "我的可用功能", "常用功能", "營運總表", "報表", "客戶查詢")),
    ("system", "系統與管理", ("資料維護區", "帳號", "重設密碼", "公告", "系統", "畫面與列印說明文字", "匯入")),
    ("common", "共通與欄位提示", ("共通畫面說明", "欄位提示說明")),
)
COPY_AREA_LABELS = {key: label for key, label, _words in COPY_AREAS}
# 名稱容易誤判的頁面直接指定。
COPY_PAGE_AREAS = {
    "畫面與列印說明文字": "system",
    "人員畫面權限總覽": "system",
    "價格表分發": "dealer",
    "內部接單": "order",
    "下單身分與所屬通路": "dealer",
}


def copy_area(key, page):
    """列印範本（print.*）一律歸列印文件；其他依頁面名稱比對，先比對到的區域優先。"""
    if key.startswith("print."):
        return "print"
    if page in COPY_PAGE_AREAS:
        return COPY_PAGE_AREAS[page]
    for area, _label, words in COPY_AREAS:
        if any(word in page for word in words):
            return area
    return "common"
