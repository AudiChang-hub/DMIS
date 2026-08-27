from django.db import migrations


PSEUDO_SOURCE_NAME = "代申請補助"
TEST_RIDE_NOTE = "試乘車"
TEST_RIDE_SOURCE_PAIRS = (
    ("東永", ("東永(試乘車)", "東永（試乘車）")),
)


def _join_unique_lines(*values):
    lines = []
    for value in values:
        for line in (value or "").splitlines():
            normalized = line.strip()
            if normalized and normalized not in lines:
                lines.append(normalized)
    return "\n".join(lines)


def _update_search_payload(payload):
    if not isinstance(payload, list):
        return payload

    updated = []
    note_found = False
    for item in payload:
        if not isinstance(item, dict):
            updated.append(item)
            continue
        label = item.get("label")
        value = item.get("value")
        if label == "來源名稱" and value == PSEUDO_SOURCE_NAME:
            continue
        copied = dict(item)
        if label == "訂單來源" and value == "合作車行":
            copied["value"] = "本店"
        elif label == "訂單來源" and value == "dealer":
            copied["value"] = "store"
        elif label == "備註":
            copied["value"] = _join_unique_lines(value, PSEUDO_SOURCE_NAME)
            note_found = True
        updated.append(copied)
    if not note_found:
        updated.append(
            {"label": "備註", "value": PSEUDO_SOURCE_NAME, "sensitive": False}
        )
    return updated


def _replace_text(value, replacements):
    if isinstance(value, str):
        for old, new in replacements:
            value = value.replace(old, new)
        return value
    if isinstance(value, list):
        return [_replace_text(item, replacements) for item in value]
    if isinstance(value, dict):
        return {key: _replace_text(item, replacements) for key, item in value.items()}
    return value


def _append_search_note(search_index, note, replacements=()):
    search_index.search_text = _join_unique_lines(
        _replace_text(search_index.search_text, replacements),
        note,
    )
    payload = _replace_text(search_index.match_payload, replacements)
    if isinstance(payload, list):
        note_item = next(
            (
                item
                for item in payload
                if isinstance(item, dict) and item.get("label") == "備註"
            ),
            None,
        )
        if note_item:
            note_item["value"] = _join_unique_lines(note_item.get("value", ""), note)
        else:
            payload.append({"label": "備註", "value": note, "sensitive": False})
    elif isinstance(payload, dict):
        payload["note"] = _join_unique_lines(payload.get("note", ""), note)
    search_index.match_payload = payload
    search_index.save(update_fields=["search_text", "match_payload", "updated_at"])


def _merge_test_ride_sources(apps):
    SalesSource = apps.get_model("sales", "SalesSource")
    SalesOrder = apps.get_model("sales", "SalesOrder")
    SearchIndex = apps.get_model("sales", "SalesOrderSearchIndex")
    OperationsProfile = apps.get_model("sales", "OrderOperationsProfile")
    MasterMapping = apps.get_model("sales", "LegacyImportMasterMapping")
    VehicleInventory = apps.get_model("sales", "VehicleInventory")
    CooperationProfile = apps.get_model("sales", "SalesSourceCooperationProfile")
    BrandPolicy = apps.get_model("sales", "SalesSourceBrandPolicy")
    VolumeBonusRule = apps.get_model("sales", "DealerVolumeBonusRule")

    relationship_priority = {"general": 0, "exclusive": 1, "shareholder": 2}
    for canonical_name, legacy_names in TEST_RIDE_SOURCE_PAIRS:
        canonical = SalesSource.objects.filter(
            source_type="dealer", name=canonical_name
        ).first()
        legacy_sources = list(
            SalesSource.objects.filter(
                source_type="dealer", name__in=legacy_names
            ).order_by("pk")
        )
        if not canonical and legacy_sources:
            canonical = legacy_sources.pop(0)
            canonical.name = canonical_name
            canonical.save(update_fields=["name", "updated_at"])
        if not canonical:
            continue

        replacements = tuple((name, canonical_name) for name in legacy_names)
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
                if relationship_priority.get(
                    profile.relationship_type, 0
                ) > relationship_priority.get(existing.relationship_type, 0):
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

            VolumeBonusRule.objects.filter(dealer_id=legacy.pk).update(
                dealer_id=canonical.pk
            )
            MasterMapping.objects.filter(sales_source_id=legacy.pk).update(
                sales_source_id=canonical.pk,
                note="特殊訂單註記：試乘車（通路已正規化）",
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
            OperationsProfile.objects.filter(order_id__in=legacy_order_ids).update(
                dealer_name=canonical_name
            )
            for search_index in SearchIndex.objects.filter(order_id__in=legacy_order_ids):
                _append_search_note(search_index, TEST_RIDE_NOTE, replacements)
            legacy.delete()

        canonical_test_ride_ids = list(
            SalesOrder.objects.filter(
                source_id=canonical.pk,
                transaction_type="test_ride",
            ).values_list("pk", flat=True)
        )
        for order in SalesOrder.objects.filter(pk__in=canonical_test_ride_ids):
            note = _join_unique_lines(order.note, TEST_RIDE_NOTE)
            if note != order.note:
                order.note = note
                order.save(update_fields=["note", "updated_at"])
        for search_index in SearchIndex.objects.filter(
            order_id__in=canonical_test_ride_ids
        ):
            _append_search_note(search_index, TEST_RIDE_NOTE, replacements)


def remove_subsidy_application_pseudo_source(apps, schema_editor):
    _merge_test_ride_sources(apps)

    SalesSource = apps.get_model("sales", "SalesSource")
    SalesOrder = apps.get_model("sales", "SalesOrder")
    SearchIndex = apps.get_model("sales", "SalesOrderSearchIndex")
    OperationsProfile = apps.get_model("sales", "OrderOperationsProfile")
    MasterMapping = apps.get_model("sales", "LegacyImportMasterMapping")
    VehicleInventory = apps.get_model("sales", "VehicleInventory")
    CooperationProfile = apps.get_model("sales", "SalesSourceCooperationProfile")
    BrandPolicy = apps.get_model("sales", "SalesSourceBrandPolicy")
    VolumeBonusRule = apps.get_model("sales", "DealerVolumeBonusRule")

    sources = list(
        SalesSource.objects.filter(
            source_type="dealer",
            name=PSEUDO_SOURCE_NAME,
        ).order_by("pk")
    )
    if not sources:
        return

    source_ids = [source.pk for source in sources]
    order_ids = list(
        SalesOrder.objects.filter(source_id__in=source_ids).values_list(
            "pk", flat=True
        )
    )
    for order in SalesOrder.objects.filter(pk__in=order_ids):
        order.source_id = None
        order.source_type = "store"
        order.note = _join_unique_lines(order.note, PSEUDO_SOURCE_NAME)
        order.save(
            update_fields=["source", "source_type", "note", "updated_at"]
        )

    OperationsProfile.objects.filter(order_id__in=order_ids).update(dealer_name="")
    for search_index in SearchIndex.objects.filter(order_id__in=order_ids):
        search_index.search_text = _join_unique_lines(
            search_index.search_text.replace("合作車行", "本店").replace(
                "dealer", "store"
            ),
            PSEUDO_SOURCE_NAME,
        )
        search_index.match_payload = _update_search_payload(
            search_index.match_payload
        )
        search_index.save(
            update_fields=["search_text", "match_payload", "updated_at"]
        )

    MasterMapping.objects.filter(sales_source_id__in=source_ids).update(
        sales_source_id=None,
        ignored=True,
        note="特殊訂單註記：代申請補助（不建立通路）",
    )
    VehicleInventory.objects.filter(current_dealer_id__in=source_ids).update(
        current_dealer_id=None
    )
    CooperationProfile.objects.filter(source_id__in=source_ids).delete()
    BrandPolicy.objects.filter(source_id__in=source_ids).delete()
    VolumeBonusRule.objects.filter(dealer_id__in=source_ids).delete()
    SalesSource.objects.filter(pk__in=source_ids).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("sales", "0091_merge_changsheng_test_ride_source"),
    ]

    operations = [
        migrations.RunPython(
            remove_subsidy_application_pseudo_source,
            migrations.RunPython.noop,
        ),
    ]
