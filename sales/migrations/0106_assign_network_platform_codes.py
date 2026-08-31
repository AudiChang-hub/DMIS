import re

from django.db import migrations


CODE_STEM = "N260831"


def assign_network_platform_codes(apps, schema_editor):
    SalesSource = apps.get_model("sales", "SalesSource")
    used_suffixes = set()
    for code in SalesSource.objects.filter(code__startswith=CODE_STEM).values_list(
        "code", flat=True
    ):
        match = re.fullmatch(rf"{CODE_STEM}(\d{{2}})", code or "")
        if match:
            used_suffixes.add(int(match.group(1)))

    available_suffixes = iter(range(max(used_suffixes, default=0) + 1, 100))
    missing_platforms = SalesSource.objects.filter(
        source_type="platform",
        code="",
    ).order_by("id")
    for platform in missing_platforms.iterator():
        try:
            suffix = next(available_suffixes)
        except StopIteration as exc:
            raise RuntimeError(f"{CODE_STEM} 當日來源代碼已用盡。") from exc
        SalesSource.objects.filter(pk=platform.pk, code="").update(
            code=f"{CODE_STEM}{suffix:02d}"
        )


class Migration(migrations.Migration):

    dependencies = [
        ("sales", "0105_staff_store_and_commission"),
    ]

    operations = [
        migrations.RunPython(
            assign_network_platform_codes,
            migrations.RunPython.noop,
        ),
    ]
