from django.db import migrations, models


def _append_unique(paragraphs, value):
    cleaned = (value or "").strip()
    if cleaned and cleaned not in paragraphs:
        paragraphs.append(cleaned)


def consolidate_sales_source_notes(apps, schema_editor):
    SalesSource = apps.get_model("sales", "SalesSource")
    SalesSourceContact = apps.get_model("sales", "SalesSourceContact")

    for source in SalesSource.objects.all().iterator():
        paragraphs = []
        for line in (source.note or "").splitlines():
            _append_unique(paragraphs, line)
        for line in (source.relationship_note or "").splitlines():
            _append_unique(paragraphs, line)

        contacts = SalesSourceContact.objects.filter(source_id=source.pk).order_by("id")
        for contact in contacts.iterator():
            identity = contact.name.strip()
            if contact.relationship.strip():
                identity = f"{identity}（{contact.relationship.strip()}）"
            details = []
            if contact.phone.strip():
                phone = contact.phone.strip()
                if contact.extension.strip():
                    phone = f"{phone} 分機 {contact.extension.strip()}"
                details.append(f"電話：{phone}")
            elif contact.extension.strip():
                details.append(f"分機：{contact.extension.strip()}")
            if contact.mobile.strip():
                details.append(f"手機：{contact.mobile.strip()}")
            if contact.email.strip():
                details.append(f"Email：{contact.email.strip()}")
            if contact.note.strip():
                details.append(contact.note.strip())
            line = f"歷史聯絡資料：{identity}"
            if details:
                line = f"{line}｜{'／'.join(details)}"
            _append_unique(paragraphs, line)

        merged_note = "\n".join(paragraphs)
        if merged_note != source.note:
            SalesSource.objects.filter(pk=source.pk).update(note=merged_note)


class Migration(migrations.Migration):

    dependencies = [
        ("sales", "0086_sales_source_line_group"),
    ]

    operations = [
        migrations.RunPython(consolidate_sales_source_notes, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="salessource",
            name="relationship_note",
        ),
        migrations.AlterField(
            model_name="salessource",
            name="note",
            field=models.TextField(blank=True, verbose_name="備註"),
        ),
        migrations.DeleteModel(
            name="SalesSourceContact",
        ),
    ]
