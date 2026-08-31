import re
import unicodedata

from django.db import migrations


SOURCE_NAMES = (
    "上海商銀員購",
    "台新銀員購",
    "台新銀行員購",
    "華新麗華員購",
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


def _update_search_payload(payload, source_name):
    if isinstance(payload, list):
        updated = []
        note_found = False
        for item in payload:
            if not isinstance(item, dict):
                updated.append(item)
                continue
            label = item.get("label")
            value = item.get("value")
            if label == "來源名稱" and value == source_name:
                continue
            copied = dict(item)
            if label == "訂單來源" and value == "網路平台":
                copied["value"] = "本店"
            elif label == "訂單來源" and value == "platform":
                copied["value"] = "store"
            elif label == "備註":
                copied["value"] = _join_unique_lines(value, source_name)
                note_found = True
            updated.append(copied)
        if not note_found:
            updated.append(
                {"label": "備註", "value": source_name, "sensitive": False}
            )
        return updated
    if isinstance(payload, dict):
        updated = dict(payload)
        for key in ("source_name", "dealer_name"):
            if updated.get(key) == source_name:
                updated[key] = ""
        for key in ("source_type", "order_source"):
            if updated.get(key) in {"platform", "網路平台"}:
                updated[key] = "store" if updated[key] == "platform" else "本店"
        updated["note"] = _join_unique_lines(updated.get("note", ""), source_name)
        return updated
    return payload


def convert_employee_purchase_platforms_to_store(apps, schema_editor):
    SalesSource = apps.get_model("sales", "SalesSource")
    SalesOrder = apps.get_model("sales", "SalesOrder")
    OperationsProfile = apps.get_model("sales", "OrderOperationsProfile")
    SearchIndex = apps.get_model("sales", "SalesOrderSearchIndex")
    Mapping = apps.get_model("sales", "LegacyImportMasterMapping")
    VehicleInventory = apps.get_model("sales", "VehicleInventory")
    CooperationProfile = apps.get_model("sales", "SalesSourceCooperationProfile")
    BrandPolicy = apps.get_model("sales", "SalesSourceBrandPolicy")
    VolumeBonusRule = apps.get_model("sales", "DealerVolumeBonusRule")

    for source_name in SOURCE_NAMES:
        normalized_source_name = _normalize_mapping_value(source_name)
        mapping_exists = Mapping.objects.filter(
            mapping_type="sales_source",
            normalized_source_value=normalized_source_name,
        ).exists()
        sources = list(
            SalesSource.objects.filter(
                source_type="platform", name=source_name
            ).order_by("pk")
        )
        source_ids = [source.pk for source in sources]
        order_ids = list(
            SalesOrder.objects.filter(source_id__in=source_ids).values_list(
                "pk", flat=True
            )
        )

        for order in SalesOrder.objects.filter(pk__in=order_ids):
            order.source_id = None
            order.source_type = "store"
            order.note = _join_unique_lines(order.note, source_name)
            order.save(
                update_fields=["source", "source_type", "note", "updated_at"]
            )

        OperationsProfile.objects.filter(order_id__in=order_ids).update(
            dealer_name=""
        )
        for index in SearchIndex.objects.filter(order_id__in=order_ids):
            index.search_text = _join_unique_lines(
                (index.search_text or "")
                .replace("網路平台", "本店")
                .replace("platform", "store"),
                source_name,
            )
            index.match_payload = _update_search_payload(
                index.match_payload, source_name
            )
            index.save(
                update_fields=["search_text", "match_payload", "updated_at"]
            )

        Mapping.objects.filter(sales_source_id__in=source_ids).update(
            sales_source_id=None,
            ignored=True,
            note=f"特殊平台註記：{source_name}（改列本店訂單）",
        )
        VehicleInventory.objects.filter(current_dealer_id__in=source_ids).update(
            current_dealer_id=None
        )
        CooperationProfile.objects.filter(source_id__in=source_ids).delete()
        BrandPolicy.objects.filter(source_id__in=source_ids).delete()
        VolumeBonusRule.objects.filter(dealer_id__in=source_ids).delete()
        SalesSource.objects.filter(pk__in=source_ids).delete()

        if sources or mapping_exists:
            Mapping.objects.update_or_create(
                mapping_type="sales_source",
                normalized_source_value=normalized_source_name,
                defaults={
                    "source_value": source_name,
                    "sales_source_id": None,
                    "vehicle_model_id": None,
                    "ignored": True,
                    "note": f"特殊平台註記：{source_name}（改列本店訂單）",
                    "updated_by": "system",
                },
            )


class Migration(migrations.Migration):

    dependencies = [
        ("sales", "0101_merge_special_platform_sources"),
    ]

    operations = [
        migrations.RunPython(
            convert_employee_purchase_platforms_to_store,
            migrations.RunPython.noop,
        ),
    ]
