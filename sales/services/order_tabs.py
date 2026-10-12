"""全部訂單的三個頁籤（使用者 2026-10-12）：進行中／已交車／已結案。

- 進行中：還沒交車（含待接單、配車、領牌、取消等）。
- 已交車：已交車，但領牌文件未完成，或還有補助項目未到「已申請完成」。
- 已結案：已交車且領牌完成，沒有待處理的補助；沒申請補助的訂單交車後直接結案。

只是列表分類，不改訂單狀態，營運報表的成交與完成數字不受影響。補助只看訂單上的補助項目；
Excel 匯入的歷史訂單沒有補助項目，交車領牌完成即為已結案。
"""
from django.db.models import Count, Exists, IntegerField, OuterRef, Q, Subquery, Value
from django.db.models.functions import Coalesce

from sales.models import SalesOrder, SubsidyItem

TABS = (
    ("open", "進行中", "還沒交車的訂單"),
    ("delivered", "已交車", "待補領牌文件或補助未完成"),
    ("closed", "已結案", "交車完成且沒有待處理補助"),
)
TAB_KEYS = tuple(key for key, _label, _hint in TABS)
DELIVERED = (SalesOrder.Status.DELIVERED_DOCS_PENDING, SalesOrder.Status.COMPLETED)


def with_subsidy_progress(orders):
    # 用子查詢計數，不讓主查詢 GROUP BY，避免與搜尋的 DISTINCT、排序註記互相影響（PostgreSQL）。
    pending = SubsidyItem.objects.filter(order=OuterRef("pk")).exclude(status=SubsidyItem.Status.COMPLETED)
    pending_count = pending.order_by().values("order").annotate(total=Count("pk")).values("total")[:1]
    return orders.annotate(
        has_pending_subsidy=Exists(pending),
        pending_subsidy_count=Coalesce(Subquery(pending_count, output_field=IntegerField()), Value(0)),
    )


def tab_filter(key):
    closed = Q(status=SalesOrder.Status.COMPLETED, has_pending_subsidy=False)
    return {
        "open": ~Q(status__in=DELIVERED),
        "delivered": Q(status__in=DELIVERED) & ~closed,
        "closed": closed,
    }[key]
