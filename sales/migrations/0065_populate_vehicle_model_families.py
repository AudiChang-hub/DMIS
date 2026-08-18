import re
import unicodedata

from django.db import migrations


def normalize(value):
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return re.sub(r"\s+", "", normalized)


def canonical_machine_name(name):
    value = normalize(name).replace("（", "(").replace("）", ")")
    if value in {"dr-z4sm(滑胎版)", "dr-z4sm（滑胎版）"}:
        return "DR-Z4SM"
    return str(name or "").strip()


def forwards(apps, schema_editor):
    VehicleModel = apps.get_model("sales", "VehicleModel")
    VehicleModelFamily = apps.get_model("sales", "VehicleModelFamily")
    VehicleFactoryModelCode = apps.get_model("sales", "VehicleFactoryModelCode")

    families = {}
    for family in VehicleModelFamily.objects.all().iterator():
        families[(family.brand.casefold(), family.name.casefold())] = family

    for model in VehicleModel.objects.order_by("pk").iterator():
        family_name = canonical_machine_name(model.name)
        key = (model.brand.strip().casefold(), family_name.casefold())
        family = families.get(key)
        if family is None:
            family = VehicleModelFamily.objects.create(
                brand=model.brand.strip(),
                name=family_name,
                active=model.active,
            )
            families[key] = family
        elif model.active and not family.active:
            family.active = True
            family.save(update_fields=["active", "updated_at"])

        VehicleModel.objects.filter(pk=model.pk).update(family_id=family.pk)

        if model.model_number:
            normalized_code = normalize(model.model_number)
            factory_code, _ = VehicleFactoryModelCode.objects.get_or_create(
                family_id=family.pk,
                normalized_code=normalized_code,
                defaults={"code": model.model_number.strip(), "active": True},
            )
            model.factory_model_codes.add(factory_code)

        if family_name != model.name:
            collision = VehicleModel.objects.filter(
                brand__iexact=model.brand,
                name__iexact=family_name,
                model_number__iexact=model.model_number,
                model_year=model.model_year,
                model_code=model.model_code,
            ).exclude(pk=model.pk)
            if not collision.exists():
                VehicleModel.objects.filter(pk=model.pk).update(name=family_name)


class Migration(migrations.Migration):
    dependencies = [("sales", "0064_vehicle_model_family")]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
