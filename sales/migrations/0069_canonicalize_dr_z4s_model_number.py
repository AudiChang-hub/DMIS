import re
import unicodedata

from django.db import migrations


CANONICAL_MODEL_NUMBER = "DR-Z4S"
CANONICAL_LOOKUP_KEY = "dr-z4s"


def is_dr_z4s(value):
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    normalized = re.sub(r"\s+", "", normalized)
    compact = re.sub(r"[-_]", "", normalized)
    return compact == "drz4s"


def merge_factory_codes(VehicleFactoryModelCode, family_id):
    matching = [
        code
        for code in VehicleFactoryModelCode.objects.filter(
            family_id=family_id
        ).order_by("pk")
        if is_dr_z4s(code.code)
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
    LegacyImportMasterMapping = apps.get_model(
        "sales", "LegacyImportMasterMapping"
    )

    matching_models = [
        model
        for model in VehicleModel.objects.filter(brand__iexact="SUZUKI").iterator()
        if is_dr_z4s(model.model_number)
    ]
    family_ids = {model.family_id for model in matching_models if model.family_id}
    for model in matching_models:
        VehicleModel.objects.filter(pk=model.pk).update(
            model_number=CANONICAL_MODEL_NUMBER
        )

    for family_id in family_ids:
        merge_factory_codes(VehicleFactoryModelCode, family_id)

    mappings = [
        mapping
        for mapping in LegacyImportMasterMapping.objects.filter(
            mapping_type="vehicle_model"
        ).order_by("pk")
        if is_dr_z4s(mapping.source_value)
    ]
    if mappings:
        keep = next(
            (mapping for mapping in mappings if mapping.vehicle_model_id),
            mappings[0],
        )
        LegacyImportMasterMapping.objects.filter(
            pk__in=[mapping.pk for mapping in mappings if mapping.pk != keep.pk]
        ).delete()
        LegacyImportMasterMapping.objects.filter(pk=keep.pk).update(
            normalized_source_value=CANONICAL_LOOKUP_KEY
        )


class Migration(migrations.Migration):
    dependencies = [("sales", "0068_canonicalize_dr_z4sm")]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
