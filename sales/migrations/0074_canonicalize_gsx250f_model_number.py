import re
import unicodedata

from django.db import migrations


CANONICAL_MODEL_NUMBER = "GSX250F"
CANONICAL_LOOKUP_KEY = "gsx250f"


def normalize(value):
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return re.sub(r"\s+", "", normalized)


def is_gsx250f(value):
    compact = re.sub(r"[-_]", "", normalize(value))
    return compact in {"gsx250f", "gsx250fgixxersf250"}


def merge_version(apps, source, target):
    VehicleModel = apps.get_model("sales", "VehicleModel")
    VehicleColor = apps.get_model("sales", "VehicleColor")
    VehicleInventory = apps.get_model("sales", "VehicleInventory")
    SalesOrder = apps.get_model("sales", "SalesOrder")
    VehiclePriceVersion = apps.get_model("sales", "VehiclePriceVersion")
    InstallmentPlanVersion = apps.get_model("sales", "InstallmentPlanVersion")
    LegacyImportMasterMapping = apps.get_model("sales", "LegacyImportMasterMapping")
    VehicleSettlementCostRule = apps.get_model("sales", "VehicleSettlementCostRule")
    VehicleIncentiveRule = apps.get_model("sales", "VehicleIncentiveRule")

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
        VehicleModel.objects.filter(pk=target.pk).update(**scalar_updates)

    target_colors = {
        color.name.strip().casefold(): color
        for color in VehicleColor.objects.filter(vehicle_model_id=target.pk)
    }
    for source_color in VehicleColor.objects.filter(vehicle_model_id=source.pk):
        target_color = target_colors.get(source_color.name.strip().casefold())
        if target_color:
            VehicleInventory.objects.filter(color_id=source_color.pk).update(
                color_id=target_color.pk
            )
            SalesOrder.objects.filter(color_id=source_color.pk).update(
                color_id=target_color.pk
            )
            if source_color.active and not target_color.active:
                VehicleColor.objects.filter(pk=target_color.pk).update(active=True)
            source_color.delete()
        else:
            VehicleColor.objects.filter(pk=source_color.pk).update(
                vehicle_model_id=target.pk
            )
            target_colors[source_color.name.strip().casefold()] = source_color

    relation_models = (
        VehiclePriceVersion,
        InstallmentPlanVersion,
        LegacyImportMasterMapping,
        VehicleSettlementCostRule,
        VehicleIncentiveRule,
    )
    for relation_model in relation_models:
        relation_model.objects.filter(vehicle_model_id=source.pk).update(
            vehicle_model_id=target.pk
        )
    VehicleInventory.objects.filter(vehicle_model_id=source.pk).update(
        vehicle_model_id=target.pk
    )
    SalesOrder.objects.filter(vehicle_model_id=source.pk).update(
        vehicle_model_id=target.pk
    )
    for code in source.factory_model_codes.all():
        target.factory_model_codes.add(code)
    source.delete()


def merge_factory_codes(VehicleFactoryModelCode, family_id):
    matching = [
        code
        for code in VehicleFactoryModelCode.objects.filter(
            family_id=family_id
        ).order_by("pk")
        if is_gsx250f(code.code)
    ]
    if not matching:
        return
    keep = next(
        (code for code in matching if code.code == CANONICAL_MODEL_NUMBER),
        matching[0],
    )
    for duplicate in matching:
        if duplicate.pk == keep.pk:
            continue
        for version in duplicate.versions.all().iterator():
            version.factory_model_codes.add(keep)
        duplicate.delete()
    VehicleFactoryModelCode.objects.filter(pk=keep.pk).update(
        code=CANONICAL_MODEL_NUMBER,
        normalized_code=CANONICAL_LOOKUP_KEY,
        active=True,
    )


def forwards(apps, schema_editor):
    VehicleModel = apps.get_model("sales", "VehicleModel")
    VehicleFactoryModelCode = apps.get_model("sales", "VehicleFactoryModelCode")
    LegacyImportMasterMapping = apps.get_model("sales", "LegacyImportMasterMapping")

    matching_models = [
        model
        for model in VehicleModel.objects.filter(brand__iexact="SUZUKI").order_by(
            "family_id", "model_year", "pk"
        )
        if is_gsx250f(model.model_number)
    ]
    groups = {}
    for model in matching_models:
        groups.setdefault((model.family_id, model.model_year), []).append(model)

    for (_family_id, _model_year), models in groups.items():
        canonical = next(
            (model for model in models if normalize(model.model_number) == "gsx250f"),
            None,
        )
        if canonical:
            for duplicate in list(models):
                if duplicate.pk != canonical.pk and normalize(
                    duplicate.model_number
                ) == "gsx250fgixxersf250":
                    merge_version(apps, duplicate, canonical)

    remaining = [
        model
        for model in VehicleModel.objects.filter(brand__iexact="SUZUKI").iterator()
        if is_gsx250f(model.model_number)
    ]
    family_ids = {model.family_id for model in remaining if model.family_id}
    VehicleModel.objects.filter(pk__in=[model.pk for model in remaining]).update(
        model_number=CANONICAL_MODEL_NUMBER
    )
    for family_id in family_ids:
        merge_factory_codes(VehicleFactoryModelCode, family_id)

    mappings = [
        mapping
        for mapping in LegacyImportMasterMapping.objects.filter(
            mapping_type="vehicle_model"
        ).order_by("pk")
        if is_gsx250f(mapping.source_value)
    ]
    if mappings:
        keep = next(
            (mapping for mapping in mappings if mapping.vehicle_model_id), mappings[0]
        )
        LegacyImportMasterMapping.objects.filter(
            pk__in=[mapping.pk for mapping in mappings if mapping.pk != keep.pk]
        ).delete()
        LegacyImportMasterMapping.objects.filter(pk=keep.pk).update(
            normalized_source_value=CANONICAL_LOOKUP_KEY
        )


class Migration(migrations.Migration):
    dependencies = [("sales", "0073_split_registration_fee_calculation_modes")]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
