"""報表讀取逐單台數獎金；先按訂單彙總，避免 JOIN 倍增。

台數獎金依規則自動計算（T-148）：期間未結束的是預估、結束後已入帳，兩者都列入報表；
2.0.0 前「確認結算」的舊分配（正式站 0 筆）一併加總，下一版收斂。
"""
from django.db.models import DecimalField, OuterRef, Subquery, Sum, Value
from django.db.models.functions import Coalesce
from sales.models import DealerVolumeBonusAllocation, OrderVolumeBonus


def with_saved_bonus(queryset):
    money = DecimalField(max_digits=20, decimal_places=2)
    allocations = (DealerVolumeBonusAllocation.objects.filter(order_id=OuterRef("pk"))
                   .order_by().values("order_id").annotate(total=Sum("amount")).values("total"))
    automatic = (OrderVolumeBonus.objects.filter(order_id=OuterRef("pk"))
                 .order_by().values("order_id").annotate(total=Sum("amount")).values("total"))
    return queryset.annotate(report_saved_bonus=(
        Coalesce(Subquery(allocations, output_field=money), Value(0), output_field=money)
        + Coalesce(Subquery(automatic, output_field=money), Value(0), output_field=money)))
