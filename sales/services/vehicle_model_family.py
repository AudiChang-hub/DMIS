from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from sales.models import (
    VehicleFactoryModelCode,
    VehicleModel,
    VehicleModelFamily,
    normalize_vehicle_model_master_value,
)


DELETE_BLOCKING_RELATIONS = (
    ("vehicleinventory_set", "庫存"),
    ("salesorder_set", "訂單"),
    ("price_versions", "售價版本"),
    ("installment_plan_versions", "分期方案"),
    ("settlement_cost_rules", "代銷結算成本"),
    ("incentive_rules", "原廠獎勵與補助"),
    ("legacy_import_mappings", "歷史匯入對應"),
)


def vehicle_model_relation_summary(vehicle_model):
    return {
        "colors": vehicle_model.colors.count(),
        "inventory": vehicle_model.vehicleinventory_set.count(),
        "orders": vehicle_model.salesorder_set.count(),
        "prices": vehicle_model.price_versions.count(),
        "installments": vehicle_model.installment_plan_versions.count(),
        "settlements": vehicle_model.settlement_cost_rules.count(),
        "incentives": vehicle_model.incentive_rules.count(),
    }


def vehicle_model_delete_blockers(vehicle_model):
    blockers = []
    for accessor, label in DELETE_BLOCKING_RELATIONS:
        count = getattr(vehicle_model, accessor).count()
        if count:
            blockers.append({"label": label, "count": count})
    return blockers


def _remove_empty_family(family):
    if family is None or family.versions.exists():
        return False
    family.factory_model_codes.filter(versions__isnull=True).delete()
    if family.factory_model_codes.exists():
        return False
    family.delete()
    return True


@transaction.atomic
def correct_vehicle_model_year(*, vehicle_model_id, model_year):
    vehicle_model = (
        VehicleModel.objects.select_for_update()
        .select_related("family")
        .get(pk=vehicle_model_id)
    )
    original_year = vehicle_model.model_year
    if model_year == original_year:
        raise ValidationError("目前已是這個年份，不需要修正。")

    if vehicle_model.family_id:
        duplicate = vehicle_model.family.versions.exclude(pk=vehicle_model.pk).filter(
            model_year=model_year,
            model_code=vehicle_model.model_code,
        )
    else:
        duplicate = VehicleModel.objects.exclude(pk=vehicle_model.pk).filter(
            brand__iexact=vehicle_model.brand,
            name__iexact=vehicle_model.name,
            model_year=model_year,
            model_code=vehicle_model.model_code,
        )
    if duplicate.select_for_update().exists():
        raise ValidationError(
            f"此機種已存在 {model_year} 年、{vehicle_model.get_model_code_display()} 的年式／規格，不能直接覆蓋。"
        )

    VehicleModel.objects.filter(pk=vehicle_model.pk).update(
        model_year=model_year,
        updated_at=timezone.now(),
    )
    vehicle_model.refresh_from_db()
    return vehicle_model, original_year


@transaction.atomic
def move_vehicle_model_to_family(*, vehicle_model_id, target_family_id):
    vehicle_model = (
        VehicleModel.objects.select_for_update()
        .select_related("family")
        .get(pk=vehicle_model_id)
    )
    target_family = VehicleModelFamily.objects.select_for_update().get(
        pk=target_family_id
    )
    source_family = vehicle_model.family
    if source_family and source_family.pk == target_family.pk:
        raise ValidationError("目前已屬於這個機種，不需要移動。")
    if target_family.brand.casefold() != vehicle_model.brand.casefold():
        raise ValidationError("只能移動到相同品牌的機種。")
    if target_family.versions.exclude(pk=vehicle_model.pk).filter(
        model_year=vehicle_model.model_year,
        model_code=vehicle_model.model_code,
    ).exists():
        raise ValidationError(
            "目標機種已有相同年份與型式；請先確認兩筆資料是否需要進一步合併。"
        )

    source_codes = list(vehicle_model.factory_model_codes.all())
    if not source_codes and vehicle_model.model_number:
        source_codes = [
            VehicleFactoryModelCode(
                code=vehicle_model.model_number,
                normalized_code=normalize_vehicle_model_master_value(
                    vehicle_model.model_number
                ),
            )
        ]
    target_codes = []
    for source_code in source_codes:
        normalized_code = normalize_vehicle_model_master_value(source_code.code)
        target_code, created = VehicleFactoryModelCode.objects.get_or_create(
            family=target_family,
            normalized_code=normalized_code,
            defaults={"code": source_code.code, "active": True},
        )
        if not created and not target_code.active:
            target_code.active = True
            target_code.save(update_fields=["active", "updated_at"])
        target_codes.append(target_code)

    VehicleModel.objects.filter(pk=vehicle_model.pk).update(
        family=target_family,
        brand=target_family.brand,
        name=target_family.name,
        updated_at=timezone.now(),
    )
    vehicle_model.refresh_from_db()
    vehicle_model.factory_model_codes.set(target_codes)
    source_removed = _remove_empty_family(source_family)
    return vehicle_model, source_removed


@transaction.atomic
def delete_unused_vehicle_model(*, vehicle_model_id):
    vehicle_model = (
        VehicleModel.objects.select_for_update()
        .select_related("family")
        .get(pk=vehicle_model_id)
    )
    blockers = vehicle_model_delete_blockers(vehicle_model)
    if blockers:
        details = "、".join(
            f"{item['label']} {item['count']} 筆" for item in blockers
        )
        raise ValidationError(f"此年式仍有關聯資料，不能永久刪除：{details}。")
    source_family = vehicle_model.family
    vehicle_model.colors.all().delete()
    vehicle_model.delete()
    source_removed = _remove_empty_family(source_family)
    return source_removed
