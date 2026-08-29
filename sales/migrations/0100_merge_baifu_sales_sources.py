from django.db import migrations


CANONICAL_NAME = "百福(馳機)"
LEGACY_NAME = "百福"


def _merge_text(current, incoming):
    values = []
    for value in (current, incoming):
        for line in (value or "").splitlines():
            line = line.strip()
            if line and line not in values:
                values.append(line)
    return "\n".join(values)


def _replace_legacy_value(value):
    if isinstance(value, str):
        return value.replace(LEGACY_NAME, CANONICAL_NAME)
    if isinstance(value, list):
        return [_replace_legacy_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _replace_legacy_value(item) for key, item in value.items()}
    return value


def merge_baifu_sources(apps, schema_editor):
    SalesSource = apps.get_model("sales", "SalesSource")
    Profile = apps.get_model("sales", "SalesSourceCooperationProfile")
    BrandPolicy = apps.get_model("sales", "SalesSourceBrandPolicy")
    BonusRule = apps.get_model("sales", "DealerVolumeBonusRule")
    Mapping = apps.get_model("sales", "LegacyImportMasterMapping")
    VehicleInventory = apps.get_model("sales", "VehicleInventory")
    SalesOrder = apps.get_model("sales", "SalesOrder")
    SearchIndex = apps.get_model("sales", "SalesOrderSearchIndex")

    canonical = SalesSource.objects.filter(
        source_type="dealer", name=CANONICAL_NAME
    ).first()
    legacy = SalesSource.objects.filter(
        source_type="dealer", name=LEGACY_NAME
    ).first()

    if not canonical and legacy:
        legacy.name = CANONICAL_NAME
        legacy.save(update_fields=["name"])
        canonical = legacy
        legacy = None

    if canonical and legacy:
        text_fields = (
            "code",
            "responsible_person",
            "phone",
            "phone_secondary",
            "mobile",
            "other_contact",
            "fax",
            "address",
            "city",
            "district",
        )
        for field_name in text_fields:
            if not getattr(canonical, field_name) and getattr(legacy, field_name):
                setattr(canonical, field_name, getattr(legacy, field_name))
        if not canonical.category_id and legacy.category_id:
            canonical.category_id = legacy.category_id
        canonical.holiday_gift = canonical.holiday_gift or legacy.holiday_gift
        canonical.has_line_group = canonical.has_line_group or legacy.has_line_group
        canonical.active = canonical.active or legacy.active
        canonical.note = _merge_text(canonical.note, legacy.note)
        for field_name in ("sym_vehicle_capacity", "suzuki_vehicle_capacity"):
            values = [
                value
                for value in (
                    getattr(canonical, field_name),
                    getattr(legacy, field_name),
                )
                if value is not None
            ]
            setattr(canonical, field_name, max(values) if values else None)
        canonical.save()

        for profile in Profile.objects.filter(source_id=legacy.pk):
            target = Profile.objects.filter(
                source_id=canonical.pk,
                cooperation_scope=profile.cooperation_scope,
            ).first()
            if not target:
                profile.source_id = canonical.pk
                profile.save(update_fields=["source_id"])
                continue
            target.cooperates = target.cooperates or profile.cooperates
            if profile.relationship_type == "exclusive":
                target.relationship_type = "exclusive"
            target.note = _merge_text(target.note, profile.note)
            target.save()
            profile.delete()

        for policy in BrandPolicy.objects.filter(source_id=legacy.pk):
            target = BrandPolicy.objects.filter(
                source_id=canonical.pk,
                brand=policy.brand,
                cooperation_scope=policy.cooperation_scope,
                effective_from=policy.effective_from,
            ).first()
            if not target:
                policy.source_id = canonical.pk
                policy.save(update_fields=["source_id"])
                continue
            target.cooperates = target.cooperates or policy.cooperates
            if not target.commission_adjustment and policy.commission_adjustment:
                target.commission_adjustment = policy.commission_adjustment
            target.note = _merge_text(target.note, policy.note)
            target.save()
            policy.delete()

        for rule in BonusRule.objects.filter(dealer_id=legacy.pk):
            rule.dealer_id = canonical.pk
            rule.save(update_fields=["dealer_id"])

        Mapping.objects.filter(sales_source_id=legacy.pk).update(
            sales_source_id=canonical.pk
        )
        VehicleInventory.objects.filter(current_dealer_id=legacy.pk).update(
            current_dealer_id=canonical.pk
        )
        SalesOrder.objects.filter(source_id=legacy.pk).update(source_id=canonical.pk)

        for index in SearchIndex.objects.filter(
            order__source_id=canonical.pk
        ).iterator():
            updated_search_text = (index.search_text or "").replace(
                LEGACY_NAME, CANONICAL_NAME
            )
            updated_payload = _replace_legacy_value(index.match_payload)
            if (
                updated_search_text != index.search_text
                or updated_payload != index.match_payload
            ):
                index.search_text = updated_search_text
                index.match_payload = updated_payload
                index.save(update_fields=["search_text", "match_payload"])

        legacy.delete()

    if canonical:
        Mapping.objects.update_or_create(
            mapping_type="sales_source",
            normalized_source_value=LEGACY_NAME,
            defaults={
                "source_value": LEGACY_NAME,
                "sales_source_id": canonical.pk,
                "vehicle_model_id": None,
                "ignored": False,
                "note": "",
                "updated_by": "system",
            },
        )


class Migration(migrations.Migration):

    dependencies = [
        ("sales", "0099_shared_dealer_vehicle_capacity"),
    ]

    operations = [
        migrations.RunPython(merge_baifu_sources, migrations.RunPython.noop),
    ]
