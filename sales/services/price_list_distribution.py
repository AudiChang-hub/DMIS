from calendar import monthrange
from datetime import date, timedelta
from urllib.parse import urlencode

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from sales.models import (
    PriceListDistributionItem,
    PriceListDistributionMonth,
    SalesSource,
    SalesSourceBrandPolicy,
    SalesSourceCooperationProfile,
)
from sales.services.phone_numbers import format_taiwan_phone


def full_distribution_address(*, city="", district="", address=""):
    city = (city or "").strip()
    district = (district or "").strip()
    address = (address or "").strip()
    if not address:
        return f"{city}{district}"
    missing_region = "".join(
        region for region in (city, district) if region and region not in address
    )
    return f"{missing_region}{address}"


def google_maps_directions_url(*, dealer_name="", city="", district="", address=""):
    if not (address or "").strip():
        return ""
    destination = " ".join(
        part
        for part in (
            (dealer_name or "").strip(),
            full_distribution_address(city=city, district=district, address=address),
        )
        if part
    )
    return "https://www.google.com/maps/dir/?" + urlencode(
        {
            "api": "1",
            "destination": destination,
            "travelmode": "driving",
        }
    )


def normalize_month(value):
    if isinstance(value, str):
        year, month = (int(part) for part in value.split("-", 1))
        return date(year, month, 1)
    return value.replace(day=1)


def next_month(value):
    value = normalize_month(value)
    return (value.replace(day=28) + timedelta(days=4)).replace(day=1)


def is_last_day(value):
    return value.day == monthrange(value.year, value.month)[1]


def dealer_snapshot_rows(source_ids=None):
    profiles = SalesSourceCooperationProfile.objects.filter(
        source__source_type=SalesSource.SourceType.DEALER,
        source__active=True,
        cooperates=True,
    ).select_related("source")
    if source_ids is not None:
        profiles = profiles.filter(source_id__in=source_ids)
    profiles = list(profiles)
    rows = {}
    for profile in profiles:
        source = profile.source
        row = rows.setdefault(
            source.pk,
            {
                "dealer": source,
                "dealer_name": source.name,
                "city": source.city,
                "district": source.district,
                "address": source.address,
                "contact_phone": format_taiwan_phone(
                    source.phone or source.phone_secondary or source.mobile,
                    source.city,
                ),
                "requires_sym": False,
                "requires_suzuki": False,
                "sym_exclusive": False,
                "has_suzuki_gas": False,
            },
        )
        if profile.cooperation_scope == SalesSourceBrandPolicy.CooperationScope.SYM:
            row["requires_sym"] = True
            row["sym_exclusive"] = (
                profile.relationship_type
                == SalesSourceCooperationProfile.RelationshipType.EXCLUSIVE
            )
        elif profile.cooperation_scope == SalesSourceBrandPolicy.CooperationScope.SUZUKI_GAS:
            row["requires_suzuki"] = True
            row["has_suzuki_gas"] = True
        elif profile.cooperation_scope == SalesSourceBrandPolicy.CooperationScope.SUZUKI_ELECTRIC:
            row["requires_suzuki"] = True
    return [
        {key: value for key, value in row.items() if key != "has_suzuki_gas"}
        for row in rows.values()
        if row["requires_sym"] or row["has_suzuki_gas"]
    ]


def assignment_user_label(user):
    if not user:
        return ""
    return user.get_full_name().strip() or user.get_username()


def previous_assignment_rows(month):
    previous = (
        PriceListDistributionMonth.objects.filter(month__lt=normalize_month(month))
        .order_by("-month")
        .first()
    )
    if not previous:
        return None, {}
    rows = {}
    for item in previous.items.select_related("assigned_to").exclude(dealer_id=None):
        assigned_to = item.assigned_to if item.assigned_to and item.assigned_to.is_active else None
        rows[item.dealer_id] = {
            "assigned_to": assigned_to,
            "assigned_to_name": assignment_user_label(assigned_to),
            "visit_order": item.visit_order if assigned_to else 0,
        }
    return previous, rows


@transaction.atomic
def ensure_distribution_month(month, *, generated_by="system", sync=False):
    month = normalize_month(month)
    distribution, created = PriceListDistributionMonth.objects.get_or_create(
        month=month,
        defaults={"generated_by": generated_by},
    )
    if not created and not sync:
        return distribution, False

    rows = dealer_snapshot_rows()
    _, previous_assignments = previous_assignment_rows(month) if created else (None, {})
    current_dealer_ids = set()
    for values in rows:
        dealer = values["dealer"]
        current_dealer_ids.add(dealer.pk)
        defaults = {key: value for key, value in values.items() if key != "dealer"}
        if created:
            defaults.update(previous_assignments.get(dealer.pk, {}))
        PriceListDistributionItem.objects.update_or_create(
            distribution=distribution,
            dealer=dealer,
            defaults=defaults,
        )

    if sync:
        distribution.items.filter(
            completed=False,
            note="",
        ).exclude(dealer_id__in=current_dealer_ids).delete()
    return distribution, created


@transaction.atomic
def copy_previous_assignments(distribution):
    previous, assignments = previous_assignment_rows(distribution.month)
    if not previous:
        return None, 0
    updated = 0
    for item in distribution.items.select_related("dealer"):
        values = assignments.get(
            item.dealer_id,
            {"assigned_to": None, "assigned_to_name": "", "visit_order": 0},
        )
        changed = (
            item.assigned_to_id != getattr(values["assigned_to"], "pk", None)
            or item.assigned_to_name != values["assigned_to_name"]
            or item.visit_order != values["visit_order"]
        )
        if not changed:
            continue
        item.assigned_to = values["assigned_to"]
        item.assigned_to_name = values["assigned_to_name"]
        item.visit_order = values["visit_order"]
        item.save(
            update_fields=["assigned_to", "assigned_to_name", "visit_order", "updated_at"]
        )
        updated += 1
    if updated and distribution.assignment_confirmed_at:
        distribution.assignment_confirmed_at = None
        distribution.assignment_confirmed_by = ""
        distribution.save(
            update_fields=["assignment_confirmed_at", "assignment_confirmed_by", "updated_at"]
        )
    return previous, updated


def ensure_scheduled_distribution(*, today=None):
    today = today or timezone.localdate()
    current_month = normalize_month(today)
    ensured = []
    current, current_created = ensure_distribution_month(
        current_month,
        generated_by="漏建自動補建",
    )
    ensured.append((current, current_created))
    if is_last_day(today):
        following, following_created = ensure_distribution_month(
            next_month(today),
            generated_by="月底排程",
        )
        ensured.append((following, following_created))
    return ensured


SNAPSHOT_FIELDS = (
    "dealer_name", "city", "district", "address", "contact_phone",
    "requires_sym", "requires_suzuki", "sym_exclusive",
)


@transaction.atomic
def sync_dealer_distribution(dealer_id, *, today=None):
    """車行異動後自動同步（T-236，使用者 2026-11-18）：只處理這一家車行，更新當月名單，下月已建立也一起更新；歷史月份不動。

    - 變成符合：新增項目，沿用上月對這家的負責人（排在該負責人本月清單最後）。
    - 仍然符合：只更新快照欄位（名稱、地址、電話、提供三陽／台鈴、三陽專銷）。
    - 變成不符合：比照手動同步，只移除未完成且沒有備註的項目；已完成或有備註的保留。
    - 「本月分工確認」只在這家的項目真的被新增或移除時清除；只更新快照不清。
    其他車行的指派、順序、完成狀態都不動。回傳 [(月份, 動作)]，動作為 added／updated／removed。
    """
    today = today or timezone.localdate()
    months = (normalize_month(today), next_month(today))
    rows = {row["dealer"].pk: row for row in dealer_snapshot_rows(source_ids=[dealer_id])}
    results = []
    for distribution in PriceListDistributionMonth.objects.select_for_update().filter(month__in=months).order_by("month"):
        action = _sync_dealer_item(distribution, dealer_id, rows.get(dealer_id))
        if action:
            results.append((distribution.month, action))
        if action in {"added", "removed"} and distribution.assignment_confirmed_at:
            distribution.assignment_confirmed_at = None
            distribution.assignment_confirmed_by = ""
            distribution.save(update_fields=["assignment_confirmed_at", "assignment_confirmed_by", "updated_at"])
    return results


def _sync_dealer_item(distribution, dealer_id, row):
    item = distribution.items.select_for_update().filter(dealer_id=dealer_id).first()
    if row is None:
        if item is not None and not item.completed and not item.note:
            item.delete()
            return "removed"
        return ""
    values = {key: row[key] for key in SNAPSHOT_FIELDS}
    if item is None:
        _, previous = previous_assignment_rows(distribution.month)
        assigned_to = previous.get(dealer_id, {}).get("assigned_to")
        visit_order = 0
        if assigned_to:
            last = distribution.items.filter(assigned_to=assigned_to).aggregate(last=Max("visit_order"))["last"]
            visit_order = (last or 0) + 1
        PriceListDistributionItem.objects.create(
            distribution=distribution, dealer_id=dealer_id, **values,
            assigned_to=assigned_to, assigned_to_name=assignment_user_label(assigned_to), visit_order=visit_order,
        )
        return "added"
    changed = [key for key, value in values.items() if getattr(item, key) != value]
    if not changed:
        return ""
    for key in changed:
        setattr(item, key, values[key])
    item.save(update_fields=[*changed, "updated_at"])
    return "updated"


def schedule_dealer_distribution_sync(dealer_id):
    """在交易提交後同步這家車行（同步可重複執行，結果相同；交易回滾就不同步）。"""
    if dealer_id:
        transaction.on_commit(lambda: sync_dealer_distribution(dealer_id))
