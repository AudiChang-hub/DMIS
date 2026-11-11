"""獎勵活動共用條件（T-149）：品牌、能源別、指定年式與期間。

語意與台數獎金規則相同：同一條件內任一符合即可、不同條件須同時符合，空白代表不限。
活動數量少，比對在 Python 做，資料庫只先篩期間與啟用。
"""
from django.db.models import Q

from sales.models import VehicleModel

ELECTRIC_ENERGY_TYPES = tuple(
    value for value, _label in VehicleModel.EnergyType.choices if value != VehicleModel.EnergyType.GAS
)


def active_on(queryset, day):
    """指定日期啟用中且在期間內的活動。"""
    return queryset.filter(active=True, effective_from__lte=day).filter(
        Q(effective_to__isnull=True) | Q(effective_to__gte=day)
    )


def _model_ids(campaign):
    cached = getattr(campaign, "_prefetched_objects_cache", {}).get("vehicle_models")
    if cached is not None:
        return {model.pk for model in cached}
    return set(campaign.vehicle_models.values_list("pk", flat=True))


def vehicle_matches(campaign, vehicle_model, model_ids=None):
    if vehicle_model is None:
        return False
    model_ids = _model_ids(campaign) if model_ids is None else model_ids
    if not has_vehicle_condition(campaign.brands, campaign.energy_types, model_ids):
        # 沒有任何車輛條件（例如唯一指定的年式被刪除）不套用，避免變成全部車輛都適用。
        return False
    brands = {str(brand).casefold() for brand in campaign.brands or []}
    if brands and (vehicle_model.brand or "").casefold() not in brands:
        return False
    if campaign.energy_types and vehicle_model.energy_type not in campaign.energy_types:
        return False
    return not model_ids or vehicle_model.pk in model_ids


def has_vehicle_condition(brands, energy_types, model_ids):
    return bool(brands or energy_types or model_ids)


def matching_models(brands=(), energy_types=(), model_ids=()):
    """條件符合的年式（不限啟用狀態）；表單預覽與「條件沒有交集」檢查共用。"""
    models = VehicleModel.objects.all()
    if brands:
        brand_q = Q()
        for brand in brands:
            brand_q |= Q(brand__iexact=brand)
        models = models.filter(brand_q)
    if energy_types:
        models = models.filter(energy_type__in=list(energy_types))
    if model_ids:
        models = models.filter(pk__in=list(model_ids))
    return models.order_by("brand", "name", "-model_year", "model_code", "pk")


def campaigns_for_vehicle_model(queryset, vehicle_model):
    """會套用到此年式的活動（不限期間與啟用），供機種工作區唯讀列出。"""
    return [
        campaign for campaign in queryset.prefetch_related("vehicle_models")
        if vehicle_matches(campaign, vehicle_model)
    ]


def condition_summary(campaign):
    """條件的文字摘要，只列有設定的條件，例如「SUZUKI・油車・任一年式」或「SUI 125 2026」。"""
    models = list(campaign.vehicle_models.all())
    if not has_vehicle_condition(campaign.brands, campaign.energy_types, models):
        return "沒有車輛條件，不會套用"
    parts = []
    if campaign.brands:
        parts.append("、".join(campaign.brands))
    if campaign.energy_types:
        parts.append("、".join(campaign.energy_type_labels))
    if models:
        names = [f"{model.name} {model.model_year or ''}".strip() for model in models[:3]]
        more = f" 等 {len(models)} 個年式" if len(models) > 3 else ""
        parts.append("、".join(names) + more)
    else:
        parts.append("任一年式")
    return "・".join(parts)
