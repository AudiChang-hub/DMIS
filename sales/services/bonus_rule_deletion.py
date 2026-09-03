import json

from django.core import signing
from django.core.exceptions import ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.db.models.deletion import ProtectedError

from sales.models import DealerVolumeBonusDeletion, DealerVolumeBonusRule
from .dealer_commission import eligible_volume_bonus_orders


CONFIRMATION_SALT = "sales.bonus-rule-delete.v1"


def bonus_rule_snapshot(rule):
    """只保存規則設定，不複製訂單個資；刪除後仍能稽核原設定。"""
    snapshot = {
        "rule": {field.name: getattr(rule, field.attname) for field in rule._meta.fields},
        "brands": list(rule.brands.order_by("pk").values("id", "brand")),
        "vehicle_models": list(rule.vehicle_models.order_by("pk").values_list("pk", flat=True)),
        "periods": list(rule.periods.order_by("pk").values("id", "starts_on", "ends_on")),
        "tiers": list(rule.tiers.order_by("pk").values("id", "minimum_quantity", "bonus_per_vehicle")),
    }
    return json.loads(json.dumps(snapshot, cls=DjangoJSONEncoder))


def bonus_rule_delete_preview(rule, actor):
    settlement_count = rule.settlements.count()
    periods = list(rule.periods.all())
    return {
        "settlement_count": settlement_count,
        "periods": periods,
        "tiers": list(rule.tiers.all()),
        "matching_orders": sum(eligible_volume_bonus_orders(rule, period=period).count() for period in periods) if not settlement_count else 0,
        "confirmation_token": signing.dumps({"actor_id": actor.pk, "snapshot": bonus_rule_snapshot(rule)}, salt=CONFIRMATION_SALT, compress=True) if not settlement_count else "",
    }


@transaction.atomic
def delete_bonus_rule(*, rule_id, actor, confirmation_token):
    if not actor.is_authenticated:
        raise ValidationError("請先登入後再刪除規則。")
    try:
        rule = DealerVolumeBonusRule.objects.select_for_update().get(pk=rule_id)
    except DealerVolumeBonusRule.DoesNotExist as exc:
        raise ValidationError("規則已不存在，未重複執行刪除。") from exc
    if rule.settlements.exists():
        raise ValidationError("此規則已有結算，只能停用，不能刪除。")
    try:
        confirmed = signing.loads(confirmation_token, salt=CONFIRMATION_SALT, max_age=3600)
    except signing.BadSignature as exc:
        raise ValidationError("刪除確認已失效，請重新檢查規則後再確認。") from exc
    snapshot = bonus_rule_snapshot(rule)
    if confirmed != {"actor_id": actor.pk, "snapshot": snapshot}:
        raise ValidationError("規則設定已變更，請重新檢查最新內容後再確認刪除。")
    name = rule.display_name
    DealerVolumeBonusDeletion.objects.create(
        original_rule_id=rule.pk, rule_name=name, actor=actor,
        actor_name=actor.get_username(), snapshot=snapshot,
    )
    try:
        rule.delete()
    except ProtectedError as exc:
        raise ValidationError("此規則已有關聯結算，系統已取消刪除。") from exc
    return name
