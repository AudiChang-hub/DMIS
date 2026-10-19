"""訂單來源標記（使用者 2026-10-19）：手動開單／Excel 匯入／Excel 匯入已修改，顯示在訂單編號下方。

- Excel 匯入：訂單有匯入快照（`LegacySalesSnapshot`）；其餘都是系統裡建立的「手動開單」。
- 已修改：匯入單有任何一筆「使用者修改」的訂單事件（`OrderEvent`）。每條修改訂單的路徑都會寫事件，
  檢視、列印、結案分類、刪除申請、匯入程式、重新匯入（含領牌改期、退訂換買家、用 Excel 補車牌完成交車）、
  財務核對修復與 migration／指令碼的資料整理都不算；自動儲存沒有任何變動（「0 個項目／欄位」）也不算。
- 只讀既有紀錄，不寫入、不加欄位；列表用 `with_order_origin`（子查詢）或 `attach_order_origin`（一次查詢）避免 N+1。
"""
from dataclasses import dataclass
from datetime import datetime

from django.db.models import Exists, OuterRef, Subquery
from django.utils import timezone

from sales.models import LegacySalesSnapshot, OrderEvent, SalesOrder

MANUAL, IMPORTED, IMPORTED_EDITED = "manual", "imported", "imported_edited"
LABELS = {MANUAL: "手動開單", IMPORTED: "Excel 匯入", IMPORTED_EDITED: "Excel 匯入已修改"}

# 不改訂單內容的事件：檢視與列印、結案分類（只分列表）、刪除申請／還原、客戶文件授權、配件主檔學習（隨修改一起寫）。
VIEW_OR_CLASSIFY_EVENTS = {
    "secret_viewed", "payout_account_viewed", "identity_document_printed",
    "order_closed", "order_reopened", "soft_deleted", "restored",
    "customer_access_updated", "accessory_master_added",
}
# 匯入程式、重新匯入與系統整理寫的事件。
IMPORT_OR_SYSTEM_EVENTS = {
    "legacy_import_update", "legacy_import_delivery_completed", "legacy_finance_repaired",
    "historical_date_changed", "historical_buyer_replaced", "historical_buyer_replacement",
    "historical_delivery_reopened", "system_corrected",
}
NON_EDIT_EVENTS = frozenset(VIEW_OR_CLASSIFY_EVENTS | IMPORT_OR_SYSTEM_EVENTS)
NON_EDIT_EVENT_PREFIXES = ("deletion_",)
# 自動儲存的事件說明帶變動數；「（0 個項目）」「（0 個欄位）」代表打開後存檔但沒有改任何東西。
AUTOSAVE_EVENTS = ("updated", "operations_updated")
NO_CHANGE_MARKER = "（0 個"
# 非人員操作：匯入、財務核對指令、migration（「系統…」）與依使用者指示執行的資料整理指令碼（「…（依使用者…）」）。
SYSTEM_ACTORS = ("歷史資料匯入", "歷史財務核對修復")
SYSTEM_ACTOR_PREFIX = "系統"
SCRIPT_ACTOR_MARKER = "（依使用者"


def user_edit_events():
    events = OrderEvent.objects.exclude(event_type__in=NON_EDIT_EVENTS)
    for prefix in NON_EDIT_EVENT_PREFIXES:
        events = events.exclude(event_type__startswith=prefix)
    return (
        events.exclude(actor_name="")
        .exclude(actor_name__in=SYSTEM_ACTORS)
        .exclude(actor_name__startswith=SYSTEM_ACTOR_PREFIX)
        .exclude(actor_name__contains=SCRIPT_ACTOR_MARKER)
        .exclude(event_type__in=AUTOSAVE_EVENTS, description__contains=NO_CHANGE_MARKER)
    )


def with_order_origin(orders):
    """替訂單查詢加上 origin_imported／origin_edited_at／origin_edited_by（最後一次使用者修改）。"""
    last_edit = user_edit_events().filter(order=OuterRef("pk")).order_by("-created_at", "-pk")
    return orders.annotate(
        origin_imported=Exists(LegacySalesSnapshot.objects.filter(order=OuterRef("pk"))),
        origin_edited_at=Subquery(last_edit.values("created_at")[:1]),
        origin_edited_by=Subquery(last_edit.values("actor_name")[:1]),
    )


ORIGIN_FIELDS = ("origin_imported", "origin_edited_at", "origin_edited_by")


def attach_order_origin(orders):
    """已取出的訂單（例如分頁後的關聯訂單）一次查詢補上來源標記；回傳原清單。"""
    orders = [order for order in orders if order is not None]
    pending = {order.pk: order for order in orders if not hasattr(order, "origin_imported")}
    if pending:
        rows = with_order_origin(SalesOrder.all_objects.filter(pk__in=pending)).values("pk", *ORIGIN_FIELDS)
        found = {row["pk"]: row for row in rows}
        for pk, order in pending.items():
            # 查不到（尚未存檔或已不存在）視為手動開單。
            row = found.get(pk, {"origin_imported": False, "origin_edited_at": None, "origin_edited_by": None})
            for name in ORIGIN_FIELDS:
                setattr(order, name, row[name])
    return orders


@dataclass(frozen=True)
class OrderOrigin:
    key: str
    edited_at: datetime | None = None
    edited_by: str = ""

    @property
    def label(self):
        return LABELS[self.key]

    @property
    def detail(self):
        if self.key == MANUAL:
            return "在系統裡建立的訂單"
        if self.key == IMPORTED:
            return "從 Excel 匯入，匯入後沒有人修改"
        when = timezone.localtime(self.edited_at).strftime("%Y/%m/%d %H:%M") if self.edited_at else ""
        return f"從 Excel 匯入，匯入後有人修改；最後一次 {self.edited_by} {when}".strip()


def order_origin(order):
    if not hasattr(order, "origin_imported"):
        attach_order_origin([order])
    if not order.origin_imported:
        return OrderOrigin(MANUAL)
    if order.origin_edited_at:
        return OrderOrigin(IMPORTED_EDITED, order.origin_edited_at, order.origin_edited_by or "")
    return OrderOrigin(IMPORTED)


def current_order_origin(order):
    """剛存檔後重新判斷（略過先前取出的標記）。"""
    for name in ORIGIN_FIELDS:
        order.__dict__.pop(name, None)
    return order_origin(order)
