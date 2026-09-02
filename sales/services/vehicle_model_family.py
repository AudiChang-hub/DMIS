from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from sales.models import (
    VehicleFactoryModelCode,
    VehicleModel,
    VehicleModelFamily,
    canonical_vehicle_model_name,
    normalize_vehicle_model_master_value,
)


DELETE_BLOCKING_RELATIONS = (
    ("vehicleinventory_set", "庫存"),
    ("salesorder_set", "訂單"),
    ("price_versions", "售價版本"),
    ("installment_plan_versions", "分期方案"),
    ("settlement_cost_rules", "車輛結算成本"),
    ("incentive_rules", "原廠獎勵與補助"),
    ("legacy_import_mappings", "歷史匯入對應"),
)

MERGE_VERSIONED_RELATIONS = (
    ("price_versions", ("effective_from",), "售價版本"),
    ("installment_plan_versions", ("effective_from",), "分期方案"),
    (
        "settlement_cost_rules",
        ("effective_from",),
        "車輛結算成本",
    ),
    ("incentive_rules", ("effective_from",), "原廠獎勵與補助"),
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


@transaction.atomic
def rename_vehicle_model_family(*, family_id, new_name):
    """Rename one machine family and keep every linked year/version in sync."""
    family = VehicleModelFamily.objects.select_for_update().get(pk=family_id)
    original_name = family.name
    normalized_name = canonical_vehicle_model_name(new_name)
    if not normalized_name:
        raise ValidationError("請填寫機種名稱。")
    version_count = family.versions.count()
    if normalized_name == original_name:
        return family, original_name, version_count

    if (
        VehicleModelFamily.objects.select_for_update()
        .filter(brand__iexact=family.brand, name__iexact=normalized_name)
        .exclude(pk=family.pk)
        .exists()
    ):
        raise ValidationError(
            f"{family.brand} 已有「{normalized_name}」機種；請使用年式資料修正的合併或移動功能，避免產生重複機種。"
        )

    if (
        VehicleModel.objects.select_for_update()
        .filter(brand__iexact=family.brand, name__iexact=normalized_name)
        .exclude(family_id=family.pk)
        .exists()
    ):
        raise ValidationError(
            f"{family.brand} 已有其他資料使用「{normalized_name}」；請先整理重複機種後再改名。"
        )

    family.name = normalized_name
    family.save(update_fields=["name", "updated_at"])
    family.versions.update(
        brand=family.brand,
        name=normalized_name,
        updated_at=timezone.now(),
    )
    return family, original_name, version_count


def _versioned_relation_conflicts(source, target):
    conflicts = []
    for accessor, key_fields, label in MERGE_VERSIONED_RELATIONS:
        source_keys = set(getattr(source, accessor).values_list(*key_fields))
        target_keys = set(getattr(target, accessor).values_list(*key_fields))
        overlap = source_keys & target_keys
        if overlap:
            conflicts.append(f"{label} {len(overlap)} 筆")
    return conflicts


def _price_version_business_values(price_version):
    ignored_fields = {"id", "vehicle_model", "created_at", "updated_at"}
    return {
        field.name: getattr(price_version, field.attname)
        for field in price_version._meta.concrete_fields
        if field.name not in ignored_fields
    }


def _deduplicate_identical_price_versions(source, target):
    """Remove exact duplicate price rows so a safe model merge can continue."""
    target_by_date = {
        item.effective_from: item
        for item in target.price_versions.select_for_update().all()
    }
    for source_price in source.price_versions.select_for_update().all():
        target_price = target_by_date.get(source_price.effective_from)
        if target_price is None:
            continue
        if _price_version_business_values(source_price) != _price_version_business_values(
            target_price
        ):
            continue
        source_price.orders.update(price_version=target_price)
        source_price.delete()


def _copy_factory_codes_to_target_family(source, target):
    code_values = list(source.factory_model_codes.values_list("code", flat=True))
    if not code_values and source.model_number:
        code_values = [source.model_number]
    target_codes = []
    for code_value in code_values:
        normalized_code = normalize_vehicle_model_master_value(code_value)
        target_code, created = VehicleFactoryModelCode.objects.get_or_create(
            family=target.family,
            normalized_code=normalized_code,
            defaults={"code": code_value, "active": True},
        )
        if not created and not target_code.active:
            target_code.active = True
            target_code.save(update_fields=["active", "updated_at"])
        target_codes.append(target_code)
    return target_codes


def _merge_locked_vehicle_model_versions(*, source, target, allow_cross_family=False):
    source_family = source.family
    if source.family_id != target.family_id:
        if not allow_cross_family:
            raise ValidationError("只能合併同一機種下的年式資料。")
        if source.brand.casefold() != target.brand.casefold():
            raise ValidationError("只能合併相同品牌的年式資料。")
        if source.model_code != target.model_code:
            raise ValidationError("只能合併相同型式的重複資料。")
    if source.model_year != target.model_year:
        raise ValidationError("只能合併相同年份的重複資料。")
    if source.energy_type != target.energy_type:
        raise ValidationError("兩筆資料的能源別不同，請先人工確認，不能直接合併。")

    # 歷史匯入常建立兩筆內容完全相同的售價版本。這類資料可安全去重；
    # 同日但金額或條件不同的版本仍由下方衝突檢查攔截。
    _deduplicate_identical_price_versions(source, target)
    conflicts = _versioned_relation_conflicts(source, target)
    if conflicts:
        raise ValidationError(
            "兩筆資料有相同生效日的商務設定，請先確認後再合併："
            + "、".join(conflicts)
            + "。"
        )

    scalar_updates = {}
    for field_name in (
        "model_code",
        "displacement_cc",
        "motor_power_kw",
        "horsepower_hp",
        "electric_registration_class",
    ):
        if not getattr(target, field_name) and getattr(source, field_name):
            scalar_updates[field_name] = getattr(source, field_name)
    if not target.base_dealer_commission and source.base_dealer_commission:
        scalar_updates["base_dealer_commission"] = source.base_dealer_commission
    if source.active and not target.active:
        scalar_updates["active"] = True
    if scalar_updates:
        scalar_updates["updated_at"] = timezone.now()
        VehicleModel.objects.filter(pk=target.pk).update(**scalar_updates)

    target_colors = {
        color.name.strip().casefold(): color
        for color in target.colors.select_for_update().all()
    }
    for source_color in source.colors.select_for_update().all():
        color_key = source_color.name.strip().casefold()
        target_color = target_colors.get(color_key)
        if target_color:
            source_color.vehicleinventory_set.update(color=target_color)
            source_color.salesorder_set.update(color=target_color)
            if source_color.active and not target_color.active:
                type(target_color).objects.filter(pk=target_color.pk).update(
                    active=True,
                    updated_at=timezone.now(),
                )
            source_color.delete()
        else:
            type(source_color).objects.filter(pk=source_color.pk).update(
                vehicle_model=target,
                updated_at=timezone.now(),
            )
            target_colors[color_key] = source_color

    for accessor, _key_fields, _label in MERGE_VERSIONED_RELATIONS:
        getattr(source, accessor).update(vehicle_model=target)
    source.legacy_import_mappings.update(vehicle_model=target)
    source.vehicleinventory_set.update(vehicle_model=target)
    source.salesorder_set.update(vehicle_model=target)
    target.factory_model_codes.add(*_copy_factory_codes_to_target_family(source, target))
    source.delete()
    source_removed = _remove_empty_family(source_family)
    target.refresh_from_db()
    return target, source_removed


@transaction.atomic
def merge_vehicle_model_versions(*, source_model_id, target_model_id):
    if source_model_id == target_model_id:
        raise ValidationError("不能將年式資料合併到自己。")
    locked = {
        item.pk: item
        for item in VehicleModel.objects.select_for_update()
        .select_related("family")
        .filter(pk__in=[source_model_id, target_model_id])
    }
    source = locked.get(source_model_id)
    target = locked.get(target_model_id)
    if source is None or target is None:
        raise ValidationError("找不到要合併的年式資料，請重新整理後再試。")
    target, _source_removed = _merge_locked_vehicle_model_versions(
        source=source,
        target=target,
    )
    return target


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
    # family 可為空；PostgreSQL 不允許對 LEFT OUTER JOIN 的 nullable side
    # 套用 FOR UPDATE。先只鎖定年式本身，後續需要 family 時再個別查詢。
    vehicle_model = VehicleModel.objects.select_for_update().get(
        pk=vehicle_model_id
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
    # 與年份修正相同，只鎖定年式本身，避免 PostgreSQL 拒絕 nullable
    # family 外連接上的 FOR UPDATE。
    vehicle_model = VehicleModel.objects.select_for_update().get(
        pk=vehicle_model_id
    )
    target_family = VehicleModelFamily.objects.select_for_update().get(
        pk=target_family_id
    )
    source_family = vehicle_model.family
    if source_family and source_family.pk == target_family.pk:
        raise ValidationError("目前已屬於這個機種，不需要移動。")
    if target_family.brand.casefold() != vehicle_model.brand.casefold():
        raise ValidationError("只能移動到相同品牌的機種。")
    duplicate = target_family.versions.exclude(pk=vehicle_model.pk).filter(
        model_year=vehicle_model.model_year,
        model_code=vehicle_model.model_code,
    ).select_for_update().order_by("id").first()
    if duplicate:
        merged_model, source_removed = _merge_locked_vehicle_model_versions(
            source=vehicle_model,
            target=duplicate,
            allow_cross_family=True,
        )
        return merged_model, source_removed, True

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
    return vehicle_model, source_removed, False


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
