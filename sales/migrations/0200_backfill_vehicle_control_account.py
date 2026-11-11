from django.db import migrations
from django.db.models import Q

# 使用者 2026-11-11 T-144 方案 A：既有電動車訂單車控帳號空白的，補上新車主 Email 中第一個 @ 之前的部分。
# 只補空白（None 或空字串）；已有值不動；Email 空白或沒有 @ 跳過；燃油車不動。重跑不會改到已補的值。
# reverse 只把「值等於該車主 Email 前綴」的清回空白（使用者已知可能誤清原本就是這個值的帳號）。
GAS = "gas"


def email_local_part(email):
    local, at, _domain = (email or "").strip().partition("@")
    local = local.strip()
    return local if at and local else ""


def _electric_profiles(apps):
    Profile = apps.get_model("sales", "OrderOperationsProfile")
    return (
        Profile.objects.select_related("order")
        .filter(order__vehicle_model__isnull=False)
        .exclude(order__vehicle_model__energy_type=GAS)
    )


def backfill_accounts(apps):
    Profile = apps.get_model("sales", "OrderOperationsProfile")
    max_length = Profile._meta.get_field("vehicle_control_account").max_length
    changed = []
    profiles = _electric_profiles(apps).filter(Q(vehicle_control_account="") | Q(vehicle_control_account__isnull=True))
    for profile in profiles.iterator():
        local = email_local_part(profile.order.owner_email)
        if local:
            profile.vehicle_control_account = local[:max_length]
            changed.append(profile)
    Profile.objects.bulk_update(changed, ["vehicle_control_account"], batch_size=500)
    return len(changed)


def clear_backfilled_accounts(apps):
    Profile = apps.get_model("sales", "OrderOperationsProfile")
    max_length = Profile._meta.get_field("vehicle_control_account").max_length
    changed = []
    for profile in _electric_profiles(apps).exclude(vehicle_control_account="").iterator():
        local = email_local_part(profile.order.owner_email)
        if local and profile.vehicle_control_account == local[:max_length]:
            profile.vehicle_control_account = ""
            changed.append(profile)
    Profile.objects.bulk_update(changed, ["vehicle_control_account"], batch_size=500)
    return len(changed)


def forwards(apps, schema_editor):
    print(f"\n  T-144 車控帳號回填：補上 {backfill_accounts(apps)} 筆")


def backwards(apps, schema_editor):
    print(f"\n  T-144 車控帳號回填還原：清回空白 {clear_backfilled_accounts(apps)} 筆")


class Migration(migrations.Migration):

    dependencies = [
        ("sales", "0199_accessory_categories"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
