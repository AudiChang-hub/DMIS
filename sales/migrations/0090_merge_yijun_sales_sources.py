from django.db import migrations


CANONICAL_NAME = "奕鈞工坊"
LEGACY_NAME = "奕鈞"


def _join_unique_lines(*values):
    lines = []
    for value in values:
        for line in (value or "").splitlines():
            normalized = line.strip()
            if normalized and normalized not in lines:
                lines.append(normalized)
    return "\n".join(lines)


def _replace_legacy_text(value):
    if isinstance(value, str):
        return value.replace(LEGACY_NAME, CANONICAL_NAME)
    if isinstance(value, list):
        return [_replace_legacy_text(item) for item in value]
    if isinstance(value, dict):
        return {key: _replace_legacy_text(item) for key, item in value.items()}
    return value


def merge_yijun_sales_sources(apps, schema_editor):
    SalesSource = apps.get_model("sales", "SalesSource")
    CooperationProfile = apps.get_model(
        "sales", "SalesSourceCooperationProfile"
    )
    BrandPolicy = apps.get_model("sales", "SalesSourceBrandPolicy")
    VolumeBonusRule = apps.get_model("sales", "DealerVolumeBonusRule")
    MasterMapping = apps.get_model("sales", "LegacyImportMasterMapping")
    VehicleInventory = apps.get_model("sales", "VehicleInventory")
    SalesOrder = apps.get_model("sales", "SalesOrder")
    SearchIndex = apps.get_model("sales", "SalesOrderSearchIndex")

    canonical = SalesSource.objects.filter(
        source_type="dealer", name=CANONICAL_NAME
    ).first()
    legacy = SalesSource.objects.filter(
        source_type="dealer", name=LEGACY_NAME
    ).first()

    if not legacy:
        return
    if not canonical:
        legacy.name = CANONICAL_NAME
        legacy.save(update_fields=["name", "updated_at"])
        return

    text_fields = (
        "code",
        "responsible_person",
        "phone",
        "phone_secondary",
        "mobile",
        "other_contact",
        "fax",
        "address",
    )
    changed_fields = []
    for field_name in text_fields:
        if not getattr(canonical, field_name) and getattr(legacy, field_name):
            setattr(canonical, field_name, getattr(legacy, field_name))
            changed_fields.append(field_name)

    combined_note = _join_unique_lines(canonical.note, legacy.note)
    if combined_note != canonical.note:
        canonical.note = combined_note
        changed_fields.append("note")
    for field_name in ("holiday_gift", "has_line_group", "active"):
        merged_value = getattr(canonical, field_name) or getattr(legacy, field_name)
        if merged_value != getattr(canonical, field_name):
            setattr(canonical, field_name, merged_value)
            changed_fields.append(field_name)
    if canonical.vehicle_capacity is None and legacy.vehicle_capacity is not None:
        canonical.vehicle_capacity = legacy.vehicle_capacity
        changed_fields.append("vehicle_capacity")
    if canonical.category_id is None and legacy.category_id is not None:
        canonical.category_id = legacy.category_id
        changed_fields.append("category")
    if changed_fields:
        canonical.save(update_fields=[*changed_fields, "updated_at"])

    relationship_priority = {"general": 0, "exclusive": 1, "shareholder": 2}
    for profile in CooperationProfile.objects.filter(source_id=legacy.pk):
        existing = CooperationProfile.objects.filter(
            source_id=canonical.pk,
            cooperation_scope=profile.cooperation_scope,
        ).first()
        if not existing:
            profile.source_id = canonical.pk
            profile.save(update_fields=["source", "updated_at"])
            continue
        existing.cooperates = existing.cooperates or profile.cooperates
        if relationship_priority.get(profile.relationship_type, 0) > relationship_priority.get(
            existing.relationship_type, 0
        ):
            existing.relationship_type = profile.relationship_type
        capacities = [
            value
            for value in (existing.vehicle_capacity, profile.vehicle_capacity)
            if value is not None
        ]
        existing.vehicle_capacity = max(capacities) if capacities else None
        existing.note = _join_unique_lines(existing.note, profile.note)
        existing.save(
            update_fields=[
                "cooperates",
                "relationship_type",
                "vehicle_capacity",
                "note",
                "updated_at",
            ]
        )
        profile.delete()

    for policy in BrandPolicy.objects.filter(source_id=legacy.pk):
        conflict = BrandPolicy.objects.filter(
            source_id=canonical.pk,
            effective_from=policy.effective_from,
        ).filter(
            brand=policy.brand,
            cooperation_scope=policy.cooperation_scope,
        ).first()
        if conflict:
            conflict.cooperates = conflict.cooperates or policy.cooperates
            if not conflict.commission_adjustment and policy.commission_adjustment:
                conflict.commission_adjustment = policy.commission_adjustment
            conflict.note = _join_unique_lines(conflict.note, policy.note)
            conflict.save(
                update_fields=[
                    "cooperates",
                    "commission_adjustment",
                    "note",
                    "updated_at",
                ]
            )
            policy.delete()
        else:
            policy.source_id = canonical.pk
            policy.save(update_fields=["source", "updated_at"])

    # 目前正式資料沒有重疊的台數獎金期間；直接保留規則及其所有門檻、結算關聯。
    VolumeBonusRule.objects.filter(dealer_id=legacy.pk).update(
        dealer_id=canonical.pk
    )
    MasterMapping.objects.filter(sales_source_id=legacy.pk).update(
        sales_source_id=canonical.pk
    )
    VehicleInventory.objects.filter(current_dealer_id=legacy.pk).update(
        current_dealer_id=canonical.pk
    )
    order_ids = list(
        SalesOrder.objects.filter(source_id=legacy.pk).values_list("pk", flat=True)
    )
    SalesOrder.objects.filter(pk__in=order_ids).update(source_id=canonical.pk)

    for search_index in SearchIndex.objects.filter(order_id__in=order_ids):
        search_index.search_text = _replace_legacy_text(search_index.search_text)
        search_index.match_payload = _replace_legacy_text(search_index.match_payload)
        search_index.save(
            update_fields=["search_text", "match_payload", "updated_at"]
        )

    legacy.delete()


class Migration(migrations.Migration):
    dependencies = [
        ("sales", "0089_remove_salessource_line_group_scope"),
    ]

    operations = [
        migrations.RunPython(merge_yijun_sales_sources, migrations.RunPython.noop),
    ]
