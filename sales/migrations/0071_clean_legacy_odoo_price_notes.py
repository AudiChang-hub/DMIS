import re

from django.db import migrations


ODOO_PRICE_MARKER = re.compile(
    r"^\[Odoo 價格 遷移 ID:[^\]]+\](?:\r?\n)?",
    flags=re.IGNORECASE,
)


def clean_legacy_price_notes(apps, schema_editor):
    VehiclePriceVersion = apps.get_model("sales", "VehiclePriceVersion")
    for version in VehiclePriceVersion.objects.filter(
        source_note__startswith="[Odoo 價格 遷移 ID:"
    ).iterator():
        note = ODOO_PRICE_MARKER.sub("", version.source_note or "").strip()
        if not note or note == "Odoo 現行價格":
            note = "歷史價格資料匯入"
        version.source_note = note[:250]
        version.save(update_fields=["source_note"])


class Migration(migrations.Migration):
    dependencies = [("sales", "0070_installment_extra_disbursement_bonus")]

    operations = [
        migrations.RunPython(clean_legacy_price_notes, migrations.RunPython.noop),
    ]
