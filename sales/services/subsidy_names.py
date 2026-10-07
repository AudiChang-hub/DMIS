"""補助名稱輸入提示：依過去用過的次數由多到少列出，讓同一種補助用同一個名稱。"""
from django.db.models import Count

from sales.models import SubsidyItem

SUGGESTION_LIMIT = 50


def subsidy_name_suggestions():
    rows = (
        SubsidyItem.objects.filter(order__deleted_at__isnull=True)
        .exclude(item_name="")
        .values("item_name")
        .annotate(uses=Count("id"))
        .order_by("-uses", "item_name")[:SUGGESTION_LIMIT]
    )
    return [row["item_name"] for row in rows]
