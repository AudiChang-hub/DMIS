import re

from django.db import migrations


LEGACY_ODOO_NOTE_MARKER = re.compile(
    r"\[Odoo(?: [^\]\r\n]+)? 遷移 ID:[^\]\r\n]+\](?:\r?\n)?",
    flags=re.IGNORECASE,
)


def clean_legacy_odoo_note_markers(apps, schema_editor):
    targets = (
        ("SalesSource", "note", None),
        ("SalesSourceContact", "note", 250),
        ("SalesSourceBrandPolicy", "note", 250),
        ("DealerVolumeBonusRule", "note", None),
    )
    for model_name, field_name, max_length in targets:
        try:
            model = apps.get_model("sales", model_name)
        except LookupError:
            # 後續 migration 可能已移除舊模型；重跑清理工具時安全略過。
            continue
        queryset = model.objects.filter(
            **{f"{field_name}__icontains": "遷移 ID:"}
        )
        for instance in queryset.iterator():
            value = getattr(instance, field_name) or ""
            cleaned = LEGACY_ODOO_NOTE_MARKER.sub("", value).strip()
            if max_length:
                cleaned = cleaned[:max_length]
            if cleaned != value:
                setattr(instance, field_name, cleaned)
                instance.save(update_fields=[field_name])


class Migration(migrations.Migration):
    dependencies = [("sales", "0084_sales_source_cooperation_scope")]

    operations = [
        migrations.RunPython(
            clean_legacy_odoo_note_markers,
            migrations.RunPython.noop,
        ),
    ]
