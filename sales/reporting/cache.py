"""報表中心卡片結果快取（T-281 g，使用者 2026-11-21 選 A）。

報表中心首頁一次算 4 張卡片，兩條依匯入列 JSON 分類的 SQL 各約 650ms（正式站 2.35.1 共 1.9 秒）。

- 快取後端沿用專案的 default cache（正式站 Redis，與營運總表同一套）；本機與測試是 LocMem。
- key＝報表 id＋版號（CURRENT_VERSION 與程式雜湊）＋展開後的報表設定＋篩選條件＋今天日期（年齡分組依今天計算）
  ＋資料版本。
- 資料版本：這頁卡片實際讀到的每張資料表（執行時從 SQL 擷取，另固定加上分類規則表）各算一個指紋。
  PostgreSQL 用「筆數＋全部列的 ctid／xmin」：任何新增、刪除、修改（含 QuerySet.update()、批次寫入、
  同一交易內的連續修改）都會改變；SQLite（本機、測試）直接雜湊整張表的內容。其他資料庫不快取。
- 第一次只記下這頁讀哪些表，第二次起才存結果：存的結果一定對應「計算前」量到的資料版本，
  計算途中有人改資料，下一次指紋不同就會重算，不會把舊數字存到新版本底下。
- `REPORT_CARD_CACHE_SECONDS = 0` 可關閉；快取服務出錯時直接重算，不影響頁面。

同一請求內共用相同 SQL（`shared_queries`）：同一頁的卡片範圍相同時，合計 COUNT／SUM 與相同的分組查詢只跑一次。
"""
import copy
import hashlib
import json
import re
from contextlib import contextmanager
from contextvars import ContextVar

from django.apps import apps
from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.utils import timezone

CACHE_VERSION = 1
DEFAULT_SECONDS = 3600
DEPENDENCY_SECONDS = 86400
ALWAYS_DEPENDS_ON = ("sales_reportclassification",)  # 分類規則在同一請求內有快取，SQL 不一定每次出現

_shared = ContextVar("report_shared_queries", default=None)
_IDENTIFIER = re.compile(r'"([A-Za-z0-9_]+)"')


@contextmanager
def shared_queries():
    """同一次 results() 內，SQL 與參數完全相同的查詢只執行一次。"""
    token = _shared.set({})
    try:
        yield
    finally:
        _shared.reset(token)


def shared(kind, queryset, compute):
    memo = _shared.get()
    if memo is None:
        return compute()
    try:
        sql, params = queryset.query.sql_with_params()
    except Exception:  # 空範圍（.none()）等無法產生 SQL 的情況照原本方式執行
        return compute()
    key = (kind, sql, repr(params))
    if key not in memo:
        memo[key] = compute()
    return copy.deepcopy(memo[key])


def _table_names():
    return {model._meta.db_table for model in apps.get_models(include_auto_created=True)}


@contextmanager
def capture_tables(found):
    known = _table_names()

    def wrapper(execute, sql, params, many, context):
        found.update(name for name in _IDENTIFIER.findall(sql) if name in known)
        return execute(sql, params, many, context)

    with connection.execute_wrapper(wrapper):
        yield


def data_version(tables):
    """這些資料表目前內容的指紋；不支援的資料庫回傳 None（不快取）。"""
    known = _table_names()
    tables = sorted(name for name in tables if name in known)
    quote = connection.ops.quote_name
    with connection.cursor() as cursor:
        if connection.vendor == "postgresql":
            parts = ", ".join(
                f"(SELECT count(*)::text || ':' || coalesce(md5(string_agg(ctid::text || ':' || xmin::text, ',' ORDER BY ctid)), '') "
                f"FROM {quote(name)})" for name in tables)
            cursor.execute(f"SELECT {parts}" if parts else "SELECT ''")
            values = [str(value) for value in cursor.fetchone()]
        elif connection.vendor == "sqlite":
            values = []
            for name in tables:
                cursor.execute(f"SELECT * FROM {quote(name)} ORDER BY rowid")
                values.append(hashlib.sha256(repr(cursor.fetchall()).encode()).hexdigest())
        else:
            return None
    return hashlib.sha256(json.dumps([tables, values]).encode()).hexdigest()[:32]


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()[:32]


def _get(key):
    try:
        return cache.get(key)
    except Exception:
        return None


def _set(key, value, seconds):
    try:
        cache.set(key, value, seconds)
    except Exception:
        pass


def cached_results(report_id, config, filters, retain_candidates, compute):
    seconds = getattr(settings, "REPORT_CARD_CACHE_SECONDS", DEFAULT_SECONDS)
    if not seconds or report_id is None or connection.vendor not in ("postgresql", "sqlite"):
        return compute()
    from config.app_version import get_app_version
    from config.release_notes import CURRENT_VERSION

    base = _digest([CACHE_VERSION, CURRENT_VERSION, get_app_version(), report_id, config, filters,
                    bool(retain_candidates), timezone.localdate()])
    dependency_key = f"report-cards:deps:{base}"
    dependencies = _get(dependency_key)
    key = None
    if dependencies:
        version = data_version(dependencies)
        key = f"report-cards:{base}:{version}" if version else None
        hit = _get(key) if key else None
        if hit is not None:
            return hit
    tables = set(ALWAYS_DEPENDS_ON)
    with capture_tables(tables):
        items = compute()
    if key and tables <= set(dependencies):
        _set(key, items, seconds)
    else:
        _set(dependency_key, sorted(tables | set(dependencies or ())), DEPENDENCY_SECONDS)
    return items
