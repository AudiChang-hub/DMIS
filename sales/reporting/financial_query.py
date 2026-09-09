"""報表只讀取已保存的獎金分配；先按訂單彙總，避免 JOIN 倍增。"""
from django.db.models import DecimalField, OuterRef, Subquery, Sum, Value
from django.db.models.functions import Coalesce
from sales.models import DealerVolumeBonusAllocation


def with_saved_bonus(queryset):
    allocations = (DealerVolumeBonusAllocation.objects.filter(order_id=OuterRef("pk"))
                   .order_by().values("order_id").annotate(total=Sum("amount")).values("total"))
    money = DecimalField(max_digits=20, decimal_places=2)
    return queryset.annotate(report_saved_bonus=Coalesce(
        Subquery(allocations, output_field=money), Value(0), output_field=money))
