from calendar import monthrange
from datetime import date, timedelta

from django.db import transaction
from django.utils import timezone

from sales.models import (
    PriceListDistributionItem,
    PriceListDistributionMonth,
    SalesSource,
    SalesSourceBrandPolicy,
    SalesSourceCooperationProfile,
)
from sales.services.phone_numbers import format_taiwan_phone


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


def dealer_snapshot_rows():
    profiles = list(
        SalesSourceCooperationProfile.objects.filter(
            source__source_type=SalesSource.SourceType.DEALER,
            source__active=True,
            cooperates=True,
        ).select_related("source")
    )
    rows = {}
    for profile in profiles:
        source = profile.source
        row = rows.setdefault(
            source.pk,
            {
                "dealer": source,
                "dealer_code": source.code,
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
