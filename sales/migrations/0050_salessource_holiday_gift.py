from django.db import migrations, models


LEGACY_GIFT_LABEL = "需安排年節送禮"


def split_legacy_gift_flag(apps, schema_editor):
    SalesSource = apps.get_model("sales", "SalesSource")
    for source in SalesSource.objects.exclude(relationship_note="").iterator():
        parts = [
            part.strip()
            for part in (source.relationship_note or "").replace("，", "、").split("、")
            if part.strip()
        ]
        if LEGACY_GIFT_LABEL not in parts:
            continue
        source.holiday_gift = True
        source.relationship_note = "、".join(
            part for part in parts if part != LEGACY_GIFT_LABEL
        )
        source.save(update_fields=["holiday_gift", "relationship_note"])


def merge_legacy_gift_flag(apps, schema_editor):
    SalesSource = apps.get_model("sales", "SalesSource")
    for source in SalesSource.objects.filter(holiday_gift=True).iterator():
        parts = [
            part.strip()
            for part in (source.relationship_note or "").replace("，", "、").split("、")
            if part.strip()
        ]
        if LEGACY_GIFT_LABEL not in parts:
            parts.append(LEGACY_GIFT_LABEL)
        source.relationship_note = "、".join(parts)
        source.save(update_fields=["relationship_note"])


class Migration(migrations.Migration):
    dependencies = [("sales", "0049_paymentrecord_payment_order_confirmed_idx_and_more")]

    operations = [
        migrations.AddField(
            model_name="salessource",
            name="holiday_gift",
            field=models.BooleanField(
                default=False,
                help_text="勾選後可在車行列表一鍵篩選。",
                verbose_name="列入年節送禮名單",
            ),
        ),
        migrations.AlterField(
            model_name="salessource",
            name="relationship_note",
            field=models.TextField(blank=True, verbose_name="關係備註"),
        ),
        migrations.RunPython(split_legacy_gift_flag, merge_legacy_gift_flag),
    ]
