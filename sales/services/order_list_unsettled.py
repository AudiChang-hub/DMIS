"""全部訂單列表的「款項未結清」紅色標記（T-139 p8，使用者 2026-11-09 選 A：只做顯示、不做篩選）。

判定：已交車之後（已交車／待領牌、已交車／待結案、已結案）且客戶應收－已確認客戶實收＞0
（payment_summary 的 customer_due）。車行現金單的客戶就是車行，所以車行掛帳也算；
分期撥款、平台撥款是事後對帳（lender_due），不算。取消類的單不顯示。
只計算目前這一頁的訂單。"""
from django.db.models import prefetch_related_objects

from .order_tabs import DELIVERED
from .payment_summary import payment_summary


def mark_unsettled(orders):
    rows = [order for order in orders if order.status in DELIVERED]
    prefetch_related_objects(rows, "payment_records", "accessories")
    for order in rows:
        due = payment_summary(order)["customer_due"]
        order.unsettled_due = due if due > 0 else None
    return orders
