import re
import unicodedata

from django.db import migrations


CANONICAL_MACHINE_NAME = "DR-Z4SM (滑胎版)"
CANONICAL_MODEL_NUMBER = "DR-Z4SM"
CANONICAL_LOOKUP_KEY = "dr-z4sm"


def is_dr_z4sm(value):
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    normalized = re.sub(r"\s+", "", normalized)
    normalized = normalized.replace("（", "(").replace("）", ")")
    compact = re.sub(r"[-_]", "", normalized)
    return compact in {"drz4sm", "drz4sm(滑胎版)"}


def merge_factory_codes(VehicleFactoryModelCode, target_family):
    codes = list(
        VehicleFactoryModelCode.objects.filter(family_id=target_family.pk).order_by(
            "pk"
        )
    )
    matching = [code for code in codes if is_dr_z4sm(code.code)]
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
    VehicleModelFamily = apps.get_model("sales", "VehicleModelFamily")
    VehicleModel = apps.get_model("sales", "VehicleModel")
    VehicleFactoryModelCode = apps.get_model("sales", "VehicleFactoryModelCode")
    LegacyImportMasterMapping = apps.get_model(
        "sales", "LegacyImportMasterMapping"
    )

    families = [
        family
        for family in VehicleModelFamily.objects.filter(brand__iexact="SUZUKI")
        if is_dr_z4sm(family.name)
    ]
    if families:
        target_family = next(
            (
                family
                for family in families
                if family.name == CANONICAL_MACHINE_NAME
            ),
            families[0],
        )
        for duplicate_family in families:
            if duplicate_family.pk == target_family.pk:
                continue
            VehicleModel.objects.filter(family_id=duplicate_family.pk).update(
                family_id=target_family.pk
            )
            for code in VehicleFactoryModelCode.objects.filter(
                family_id=duplicate_family.pk
            ).iterator():
                existing = VehicleFactoryModelCode.objects.filter(
                    family_id=target_family.pk,
                    normalized_code=code.normalized_code,
                ).first()
                if existing:
                    for version in code.versions.all().iterator():
                        version.factory_model_codes.add(existing)
                    code.delete()
                else:
                    VehicleFactoryModelCode.objects.filter(pk=code.pk).update(
                        family_id=target_family.pk
                    )
            duplicate_family.delete()

        VehicleModelFamily.objects.filter(pk=target_family.pk).update(
            name=CANONICAL_MACHINE_NAME,
            active=True,
        )
        VehicleModel.objects.filter(family_id=target_family.pk).update(
            name=CANONICAL_MACHINE_NAME
        )

        for model in VehicleModel.objects.filter(family_id=target_family.pk).iterator():
            if is_dr_z4sm(model.model_number):
                VehicleModel.objects.filter(pk=model.pk).update(
                    model_number=CANONICAL_MODEL_NUMBER
                )

        merge_factory_codes(VehicleFactoryModelCode, target_family)

    mappings = [
        mapping
        for mapping in LegacyImportMasterMapping.objects.filter(
            mapping_type="vehicle_model"
        ).order_by("pk")
        if is_dr_z4sm(mapping.source_value)
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
    dependencies = [("sales", "0067_installment_disbursement_modes")]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
