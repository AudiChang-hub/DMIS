from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models.deletion import ProtectedError

from sales.models import SalesSource


@dataclass(frozen=True)
class SalesSourceDeleteBlocker:
    key: str
    label: str
    count: int


_DEALER_DELETE_RELATIONS = (
    ("salesorder_set", "訂單"),
    ("credited_orders", "台數與傭金歸屬訂單"),
    ("located_vehicles", "目前停放於此車行的庫存車輛"),
    ("volume_bonus_rules", "台數獎金規則"),
    ("volume_bonus_settlements", "台數獎金結算"),
    ("legacy_import_mappings", "舊資料匯入對應"),
)


def sales_source_delete_blockers(source):
    """列出會阻止合作車行永久刪除的營運資料。"""
    blockers = []
    for relation_name, label in _DEALER_DELETE_RELATIONS:
        count = getattr(source, relation_name).count()
        if count:
            blockers.append(
                SalesSourceDeleteBlocker(
                    key=relation_name,
                    label=label,
                    count=count,
                )
            )
    return blockers


@transaction.atomic
def delete_unused_dealer(*, source_id):
    """鎖定並刪除未被營運資料引用的合作車行。"""
    try:
        source = SalesSource.objects.select_for_update().get(
            pk=source_id,
            source_type=SalesSource.SourceType.DEALER,
        )
    except SalesSource.DoesNotExist as exc:
        raise ValidationError("找不到要刪除的合作車行。") from exc

    blockers = sales_source_delete_blockers(source)
    if blockers:
        raise ValidationError("此車行已有營運資料，只能停用，不能永久刪除。")

    source_name = source.name
    try:
        source.delete()
    except ProtectedError as exc:
        raise ValidationError(
            "刪除前偵測到新的營運資料，系統已取消永久刪除，請重新檢查。"
        ) from exc
    return source_name
