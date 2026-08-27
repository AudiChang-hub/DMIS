from django.db import migrations


CANONICAL_NAME = "昌勝"
LEGACY_NAMES = ("昌勝(試乘車)", "昌勝（試乘車）")
TEST_RIDE_NOTE = "試乘車"


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
        for legacy_name in LEGACY_NAMES:
            value = value.replace(legacy_name, CANONICAL_NAME)
        return value
    if isinstance(value, list):
        return [_replace_legacy_text(item) for item in value]
    if isinstance(value, dict):
        return {key: _replace_legacy_text(item) for key, item in value.items()}
    return value


def _mark_test_ride_orders(SalesOrder, SearchIndex, source_id):
    order_ids = list(
        SalesOrder.objects.filter(
            source_id=source_id,
            transaction_type="test_ride",
        ).values_list("pk", flat=True)
    )
    for order in SalesOrder.objects.filter(pk__in=order_ids):
        note = _join_unique_lines(order.note, TEST_RIDE_NOTE)
        if note != order.note:
            order.note = note
            order.save(update_fields=["note", "updated_at"])
    for search_index in SearchIndex.objects.filter(order_id__in=order_ids):
        search_index.search_text = _join_unique_lines(
            _replace_legacy_text(search_index.search_text),
            TEST_RIDE_NOTE,
        )
        search_index.match_payload = _replace_legacy_text(search_index.match_payload)
        if isinstance(search_index.match_payload, dict):
            search_index.match_payload["note"] = _join_unique_lines(
                search_index.match_payload.get("note", ""),
                TEST_RIDE_NOTE,
            )
        search_index.save(
            update_fields=["search_text", "match_payload", "updated_at"]
        )


def merge_changsheng_test_ride_source(apps, schema_editor):
    SalesSource = apps.get_model("sales", "SalesSource")
    CooperationProfile = apps.get_model("sales", "SalesSourceCooperationProfile")
    BrandPolicy = apps.get_model("sales", "SalesSourceBrandPolicy")
    VolumeBonusRule = apps.get_model("sales", "DealerVolumeBonusRule")
    MasterMapping = apps.get_model("sales", "LegacyImportMasterMapping")
    VehicleInventory = apps.get_model("sales", "VehicleInventory")
    SalesOrder = apps.get_model("sales", "SalesOrder")
    SearchIndex = apps.get_model("sales", "SalesOrderSearchIndex")

    canonical = SalesSource.objects.filter(
        source_type="dealer", name=CANONICAL_NAME
    ).first()
    legacy_sources = list(
        SalesSource.objects.filter(
            source_type="dealer", name__in=LEGACY_NAMES
        ).order_by("pk")
    )

    if not canonical and legacy_sources:
        canonical = legacy_sources.pop(0)
        canonical.name = CANONICAL_NAME
        canonical.save(update_fields=["name", "updated_at"])
    if not canonical:
        return

    relationship_priority = {"general": 0, "exclusive": 1, "shareholder": 2}
    for legacy in legacy_sources:
        changed_fields = []
        for field_name in (
            "code",
            "responsible_person",
            "phone",
            "phone_secondary",
            "mobile",
            "other_contact",
            "fax",
            "address",
        ):
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

        VolumeBonusRule.objects.filter(dealer_id=legacy.pk).update(dealer_id=canonical.pk)
        MasterMapping.objects.filter(sales_source_id=legacy.pk).update(
            sales_source_id=canonical.pk
        )
        VehicleInventory.objects.filter(current_dealer_id=legacy.pk).update(
            current_dealer_id=canonical.pk
        )
        legacy_order_ids = list(
            SalesOrder.objects.filter(source_id=legacy.pk).values_list("pk", flat=True)
        )
        for order in SalesOrder.objects.filter(pk__in=legacy_order_ids):
            order.source_id = canonical.pk
            order.transaction_type = "test_ride"
            order.note = _join_unique_lines(order.note, TEST_RIDE_NOTE)
            order.save(
                update_fields=["source", "transaction_type", "note", "updated_at"]
            )
        for search_index in SearchIndex.objects.filter(order_id__in=legacy_order_ids):
            search_index.search_text = _join_unique_lines(
                _replace_legacy_text(search_index.search_text),
                TEST_RIDE_NOTE,
            )
            search_index.match_payload = _replace_legacy_text(search_index.match_payload)
            if isinstance(search_index.match_payload, dict):
                search_index.match_payload["note"] = _join_unique_lines(
                    search_index.match_payload.get("note", ""),
                    TEST_RIDE_NOTE,
                )
            search_index.save(
                update_fields=["search_text", "match_payload", "updated_at"]
            )
        legacy.delete()

    _mark_test_ride_orders(SalesOrder, SearchIndex, canonical.pk)


class Migration(migrations.Migration):
    dependencies = [
        ("sales", "0090_merge_yijun_sales_sources"),
    ]

    operations = [
        migrations.RunPython(
            merge_changsheng_test_ride_source,
            migrations.RunPython.noop,
        ),
    ]
