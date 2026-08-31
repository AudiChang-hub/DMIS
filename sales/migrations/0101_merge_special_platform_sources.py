import re
import unicodedata

from django.db import migrations


SOURCE_RULES = (
    ("momo", "momo員購", "momo員購"),
    ("小樹購", "小樹購員購", "小樹購員購"),
    ("Yahoo", "Yahoo+假展場", "Yahoo+假展場"),
)


def _normalize_mapping_value(value):
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return re.sub(r"\s+", "", normalized)


def _join_unique_lines(*values):
    lines = []
    for value in values:
        for line in (value or "").splitlines():
            normalized = line.strip()
            if normalized and normalized not in lines:
                lines.append(normalized)
    return "\n".join(lines)


def _replace_text(value, old, new):
    if isinstance(value, str):
        return value.replace(old, new)
    if isinstance(value, list):
        return [_replace_text(item, old, new) for item in value]
    if isinstance(value, dict):
        return {key: _replace_text(item, old, new) for key, item in value.items()}
    return value


def _update_search_index(index, legacy_name, canonical_name, order_note):
    index.search_text = _join_unique_lines(
        (index.search_text or "").replace(legacy_name, canonical_name),
        order_note,
    )
    payload = _replace_text(index.match_payload, legacy_name, canonical_name)
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
            note_item["value"] = _join_unique_lines(
                note_item.get("value", ""), order_note
            )
        else:
            payload.append(
                {"label": "備註", "value": order_note, "sensitive": False}
            )
    elif isinstance(payload, dict):
        payload["note"] = _join_unique_lines(payload.get("note", ""), order_note)
    index.match_payload = payload
    index.save(update_fields=["search_text", "match_payload", "updated_at"])


def merge_special_platform_sources(apps, schema_editor):
    SalesSource = apps.get_model("sales", "SalesSource")
    SalesOrder = apps.get_model("sales", "SalesOrder")
    OperationsProfile = apps.get_model("sales", "OrderOperationsProfile")
    SearchIndex = apps.get_model("sales", "SalesOrderSearchIndex")
    Mapping = apps.get_model("sales", "LegacyImportMasterMapping")
    VehicleInventory = apps.get_model("sales", "VehicleInventory")

    for canonical_name, legacy_name, order_note in SOURCE_RULES:
        legacy = SalesSource.objects.filter(
            source_type="platform", name=legacy_name
        ).first()
        canonical = SalesSource.objects.filter(
            source_type="platform", name=canonical_name
        ).first()
        if not canonical and legacy:
            canonical = legacy
            canonical.name = canonical_name
            canonical.save(update_fields=["name", "updated_at"])
        if not canonical:
            continue

        affected_order_ids = []
        if legacy:
            affected_order_ids = list(
                SalesOrder.objects.filter(source_id=legacy.pk).values_list(
                    "pk", flat=True
                )
            )
            for order in SalesOrder.objects.filter(pk__in=affected_order_ids):
                order.source_id = canonical.pk
                order.source_type = "platform"
                order.note = _join_unique_lines(order.note, order_note)
                order.save(
                    update_fields=["source", "source_type", "note", "updated_at"]
                )

            OperationsProfile.objects.filter(
                order_id__in=affected_order_ids
            ).update(dealer_name=canonical_name)
            for index in SearchIndex.objects.filter(order_id__in=affected_order_ids):
                _update_search_index(
                    index, legacy_name, canonical_name, order_note
                )

            Mapping.objects.filter(sales_source_id=legacy.pk).update(
                sales_source_id=canonical.pk,
                ignored=False,
                note=f"特殊平台註記：{order_note}（通路已正規化）",
            )
            VehicleInventory.objects.filter(current_dealer_id=legacy.pk).update(
                current_dealer_id=canonical.pk
            )
            if legacy.pk != canonical.pk:
                legacy.delete()

        Mapping.objects.update_or_create(
            mapping_type="sales_source",
            normalized_source_value=_normalize_mapping_value(legacy_name),
            defaults={
                "source_value": legacy_name,
                "sales_source_id": canonical.pk,
                "vehicle_model_id": None,
                "ignored": False,
                "note": f"特殊平台註記：{order_note}（通路已正規化）",
                "updated_by": "system",
            },
        )


class Migration(migrations.Migration):

    dependencies = [
        ("sales", "0100_merge_baifu_sales_sources"),
    ]

    operations = [
        migrations.RunPython(
            merge_special_platform_sources,
            migrations.RunPython.noop,
        ),
    ]
