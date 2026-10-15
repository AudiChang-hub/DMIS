"""全部訂單的四個頁籤（使用者 2026-10-12；2026-10-15 改為人工結案）：進行中／已交車／已結案／已取消。

- 進行中：還沒交車也沒取消（待接單、配車、領牌、待交車等）。
- 已交車：已交車，還沒由人員按「確認結案」（含待補領牌文件）。
- 已結案：人員已確認結案；只有人能判斷補助是否跑完，系統不自動結案、也不設關卡。
- 已取消：已取消、取消待退款（退款仍在此處理）與例外結案。

只是列表分類，不改訂單狀態，營運報表的成交與完成數字不受影響。
Excel 匯入的歷史已完成訂單在 migration 0187 一次標為已結案。
"""
from django.db.models import Count, IntegerField, OuterRef, Q, Subquery, Value
from django.db.models.functions import Coalesce

from sales.models import SalesOrder, SubsidyItem

TABS = (
    ("open", "進行中", "還沒交車的訂單"),
    ("delivered", "已交車", "待人員確認結案"),
    ("closed", "已結案", "人員已確認結案"),
    ("cancelled", "已取消", "含取消待退款與例外結案"),
)
TAB_KEYS = tuple(key for key, _label, _hint in TABS)
DELIVERED = (SalesOrder.Status.DELIVERED_DOCS_PENDING, SalesOrder.Status.COMPLETED)
CANCELLED = (SalesOrder.Status.CANCELLED, SalesOrder.Status.CANCEL_REFUND_PENDING, SalesOrder.Status.EXCEPTION_CLOSED)


def with_subsidy_progress(orders):
    # 用子查詢計數，不讓主查詢 GROUP BY，避免與搜尋的 DISTINCT、排序註記互相影響（PostgreSQL）。
    pending = SubsidyItem.objects.filter(order=OuterRef("pk"), status=SubsidyItem.Status.NOT_SUBMITTED)
    pending_count = pending.order_by().values("order").annotate(total=Count("pk")).values("total")[:1]
    return orders.annotate(
        pending_subsidy_count=Coalesce(Subquery(pending_count, output_field=IntegerField()), Value(0)),
    )


def tab_filter(key):
    closed = Q(status__in=DELIVERED, closed_at__isnull=False)
    return {
        "open": ~Q(status__in=DELIVERED + CANCELLED),
        "delivered": Q(status__in=DELIVERED, closed_at__isnull=True),
        "closed": closed,
        "cancelled": Q(status__in=CANCELLED),
    }[key]
