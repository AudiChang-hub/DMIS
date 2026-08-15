from __future__ import annotations

from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max, Q
from django.utils import timezone

from sales.models import (
    DealerPriceList,
    DealerPriceListItem,
    InstallmentCompany,
    InstallmentPlanOption,
    InstallmentPlanVersion,
    VehicleModel,
    VehiclePriceVersion,
)


DEFAULT_INSTALLMENT_PERIODS = [18, 24, 36, 48, 60]


def vehicle_models_for_brand(brand):
    brand_names = [brand.name]
    if brand.parent_id is None:
        brand_names.extend(brand.sub_brands.values_list("name", flat=True))
    return (
        VehicleModel.objects.filter(brand__in=brand_names, active=True)
        .prefetch_related("colors")
        .order_by("brand", "name", "-model_year", "model_number", "id")
    )


def _effective_price(vehicle_model, effective_on):
    return (
        vehicle_model.price_versions.filter(
            active=True,
            effective_from__lte=effective_on,
        )
        .filter(Q(effective_to__isnull=True) | Q(effective_to__gte=effective_on))
        .order_by("-effective_from", "-id")
        .first()
    )


def _effective_installment_plan(vehicle_model, effective_on):
    return (
        vehicle_model.installment_plan_versions.filter(
            active=True,
            effective_from__lte=effective_on,
        )
        .filter(Q(effective_to__isnull=True) | Q(effective_to__gte=effective_on))
        .prefetch_related("options__company")
        .order_by("-effective_from", "-id")
        .first()
    )


def _installment_snapshot(plan):
    if not plan:
        return {}
    return {
        str(option.periods): {
            "monthly_amount": str(option.monthly_amount),
            "company_id": option.company_id,
            "company_name": option.company.name,
            "opening_fee": str(option.opening_fee),
            "expected_disbursement_rate": (
                str(option.expected_disbursement_rate)
                if option.expected_disbursement_rate is not None
                else ""
            ),
        }
        for option in plan.options.all()
    }


def populate_price_list(price_list, source=None):
    """補齊該品牌車型；既有列不覆蓋，複製來源則沿用對外內容。"""
    existing_model_ids = set(price_list.items.values_list("vehicle_model_id", flat=True))
    source_items = {
        item.vehicle_model_id: item
        for item in (source.items.all() if source else [])
    }
    rows = []
    for index, vehicle_model in enumerate(
        vehicle_models_for_brand(price_list.brand), start=1
    ):
        if vehicle_model.pk in existing_model_ids:
            continue
        copied = source_items.get(vehicle_model.pk)
        if copied:
            rows.append(
                DealerPriceListItem(
                    price_list=price_list,
                    vehicle_model=vehicle_model,
                    visible=copied.visible,
                    section=copied.section,
                    display_order=copied.display_order,
                    model_label=copied.model_label,
                    year_label=copied.year_label,
                    colors_label=copied.colors_label,
                    suggested_price=copied.suggested_price,
                    cash_discount=copied.cash_discount,
                    cash_price=copied.cash_price,
                    installments=copied.installments,
                    customer_gift=copied.customer_gift,
                    channel_label=copied.channel_label,
                    note=copied.note,
                )
            )
            continue

        price = _effective_price(vehicle_model, price_list.effective_from)
        plan = _effective_installment_plan(vehicle_model, price_list.effective_from)
        suggested_price = (
            price.suggested_price_including_registration if price else None
        )
        cash_price = price.cash_price if price else None
        discount = None
        if suggested_price is not None and cash_price is not None:
            discount = suggested_price - cash_price
        active_colors = [
            color.name for color in vehicle_model.colors.all() if color.active
        ]
        rows.append(
            DealerPriceListItem(
                price_list=price_list,
                vehicle_model=vehicle_model,
                display_order=index * 10,
                model_label=vehicle_model.name,
                year_label=str(vehicle_model.model_year or ""),
                colors_label="／".join(active_colors),
                suggested_price=suggested_price,
                cash_discount=discount,
                cash_price=cash_price,
                installments=_installment_snapshot(plan),
            )
        )
    if rows:
        DealerPriceListItem.objects.bulk_create(rows)
    return len(rows)


def previous_price_list(brand, period_month):
    return (
        DealerPriceList.objects.filter(brand=brand, period_month__lt=period_month)
        .exclude(status=DealerPriceList.Status.ARCHIVED)
        .prefetch_related("items")
        .order_by("-period_month", "-revision")
        .first()
    )


def next_revision(brand, period_month):
    latest = (
        DealerPriceList.objects.filter(brand=brand, period_month=period_month)
        .aggregate(value=Max("revision"))["value"]
        or 0
    )
    return latest + 1


def clone_price_list(source, *, period_month=None, user=None):
    target_month = (period_month or source.period_month).replace(day=1)
    target = DealerPriceList.objects.create(
        brand=source.brand,
        period_month=target_month,
        revision=next_revision(source.brand, target_month),
        title=(
            f"{target_month.year} 年 {target_month.month} 月價格表"
            if target_month != source.period_month
            else source.title
        ),
        effective_from=(
            target_month if target_month != source.period_month else source.effective_from
        ),
        header_note=source.header_note,
        footer_note=source.footer_note,
        installment_periods=source.installment_periods,
        logo_override=source.logo_override,
        created_by=user,
    )
    populate_price_list(target, source=source)
    return target


def parse_optional_money(raw_value, label, errors):
    text = str(raw_value or "").replace(",", "").replace("$", "").strip()
    if not text:
        return None
    try:
        value = Decimal(text)
    except (InvalidOperation, ValueError):
        errors.append(f"{label}必須是有效金額。")
        return None
    if value < 0 or value != value.quantize(Decimal("1")):
        errors.append(f"{label}必須是零以上的整數金額。")
        return None
    return value


def update_items_from_post(price_list, post):
    items = list(price_list.items.select_related("vehicle_model").all())
    valid_sections = {value for value, _label in DealerPriceListItem.Section.choices}
    valid_company_ids = set(
        InstallmentCompany.objects.filter(active=True).values_list("pk", flat=True)
    )
    valid_company_ids.update(
        term.get("company_id")
        for item in items
        for term in (item.installments or {}).values()
        if term.get("company_id")
    )
    errors = []
    changed_at = timezone.now()
    for item in items:
        prefix = f"item-{item.pk}"
        item.visible = f"{prefix}-visible" in post
        section = post.get(f"{prefix}-section", item.section)
        item.section = section if section in valid_sections else item.section
        try:
            item.display_order = max(0, int(post.get(f"{prefix}-order", item.display_order)))
        except (TypeError, ValueError):
            errors.append(f"{item.model_label}：排序必須是整數。")
        item.model_label = post.get(f"{prefix}-model-label", "").strip()
        item.year_label = post.get(f"{prefix}-year-label", "").strip()
        item.colors_label = post.get(f"{prefix}-colors-label", "").strip()
        item.suggested_price = parse_optional_money(
            post.get(f"{prefix}-suggested-price"),
            f"{item.model_label or item.vehicle_model.name}的建議售價",
            errors,
        )
        item.cash_discount = parse_optional_money(
            post.get(f"{prefix}-cash-discount"),
            f"{item.model_label or item.vehicle_model.name}的現金優惠",
            errors,
        )
        item.cash_price = parse_optional_money(
            post.get(f"{prefix}-cash-price"),
            f"{item.model_label or item.vehicle_model.name}的現金價",
            errors,
        )
        item.customer_gift = post.get(f"{prefix}-customer-gift", "").strip()
        item.channel_label = post.get(f"{prefix}-channel", "").strip()
        item.note = post.get(f"{prefix}-note", "").strip()
        if not item.model_label:
            errors.append(f"{item.vehicle_model}：機種顯示名稱不可空白。")

        existing_terms = item.installments or {}
        terms = {}
        for periods in price_list.installment_periods:
            term_prefix = f"{prefix}-installment-{periods}"
            amount = parse_optional_money(
                post.get(f"{term_prefix}-amount"),
                f"{item.model_label or item.vehicle_model.name} {periods}期月付",
                errors,
            )
            if amount is None:
                continue
            company_raw = post.get(f"{term_prefix}-company", "").strip()
            try:
                company_id = int(company_raw)
            except (TypeError, ValueError):
                company_id = None
            if company_id not in valid_company_ids:
                errors.append(f"{item.model_label} {periods}期：請選擇啟用中的分期公司。")
                continue
            opening_fee = parse_optional_money(
                post.get(f"{term_prefix}-opening-fee"),
                f"{item.model_label} {periods}期開辦費",
                errors,
            )
            company = InstallmentCompany.objects.get(pk=company_id)
            old_term = existing_terms.get(str(periods), {})
            terms[str(periods)] = {
                "monthly_amount": str(amount),
                "company_id": company_id,
                "company_name": company.name,
                "opening_fee": str(opening_fee or 0),
                "expected_disbursement_rate": old_term.get(
                    "expected_disbursement_rate", ""
                ),
            }
        item.installments = terms
        item.updated_at = changed_at

    if errors:
        return items, errors
    DealerPriceListItem.objects.bulk_update(
        items,
        [
            "visible", "section", "display_order", "model_label", "year_label",
            "colors_label", "suggested_price", "cash_discount", "cash_price",
            "installments", "customer_gift", "channel_label", "note", "updated_at",
        ],
    )
    return items, []


def editor_rows(price_list, items=None):
    rows = list(
        price_list.items.select_related("vehicle_model").all()
        if items is None
        else items
    )
    referenced_company_ids = {
        term.get("company_id")
        for item in rows
        for term in (item.installments or {}).values()
        if term.get("company_id")
    }
    company_choices = list(
        InstallmentCompany.objects.filter(
            Q(active=True) | Q(pk__in=referenced_company_ids)
        )
        .order_by("name")
        .values("id", "name", "active")
    )
    for item in rows:
        terms = item.installments or {}
        item.editor_installments = []
        for periods in price_list.installment_periods:
            term = terms.get(str(periods), {})
            item.editor_installments.append(
                {
                    "periods": periods,
                    "monthly_amount": term.get("monthly_amount", ""),
                    "company_id": term.get("company_id"),
                    "company_name": term.get("company_name", ""),
                    "opening_fee": term.get("opening_fee", ""),
                    "company_choices": company_choices,
                }
            )
    return rows


def validate_for_publish(price_list):
    errors = []
    visible_items = list(price_list.items.filter(visible=True))
    if not visible_items:
        errors.append("價目表至少要有一個顯示中的車型。")
    valid_company_ids = set(InstallmentCompany.objects.values_list("pk", flat=True))
    for item in visible_items:
        if item.suggested_price is None and item.cash_price is None:
            errors.append(f"{item.model_label}：建議售價與現金價不可同時空白。")
        for period, term in (item.installments or {}).items():
            if term.get("monthly_amount") not in (None, "") and term.get("company_id") not in valid_company_ids:
                errors.append(f"{item.model_label} {period}期：分期公司不存在。")
    return errors


def _close_previous_versions(queryset, effective_from):
    queryset.filter(effective_from__lt=effective_from).filter(
        Q(effective_to__isnull=True) | Q(effective_to__gte=effective_from)
    ).update(effective_to=effective_from - timedelta(days=1))


@transaction.atomic
def publish_price_list(price_list, user):
    price_list = DealerPriceList.objects.select_for_update().select_related("brand").get(
        pk=price_list.pk
    )
    if price_list.status != DealerPriceList.Status.DRAFT:
        raise ValidationError("只有草稿可以發布；已發布內容請建立修訂版。")
    errors = validate_for_publish(price_list)
    if errors:
        raise ValidationError(errors)

    for item in price_list.items.filter(visible=True).select_related("vehicle_model"):
        if item.suggested_price is not None or item.cash_price is not None:
            _close_previous_versions(
                item.vehicle_model.price_versions.exclude(
                    effective_from=price_list.effective_from
                ),
                price_list.effective_from,
            )
            VehiclePriceVersion.objects.update_or_create(
                vehicle_model=item.vehicle_model,
                effective_from=price_list.effective_from,
                defaults={
                    "suggested_price_including_registration": item.suggested_price,
                    "cash_price": item.cash_price,
                    "announced_on": timezone.localdate(),
                    "effective_to": None,
                    "source_note": f"車行價目表：{price_list.title} v{price_list.revision}",
                    "active": True,
                },
            )

        if item.installments:
            _close_previous_versions(
                item.vehicle_model.installment_plan_versions.exclude(
                    effective_from=price_list.effective_from
                ),
                price_list.effective_from,
            )
            plan, _created = InstallmentPlanVersion.objects.update_or_create(
                vehicle_model=item.vehicle_model,
                effective_from=price_list.effective_from,
                defaults={
                    "announced_on": timezone.localdate(),
                    "effective_to": None,
                    "note": f"車行價目表：{price_list.title} v{price_list.revision}",
                    "active": True,
                },
            )
            plan.options.all().delete()
            options = []
            for period_text, term in item.installments.items():
                rate_text = term.get("expected_disbursement_rate", "")
                options.append(
                    InstallmentPlanOption(
                        version=plan,
                        periods=int(period_text),
                        monthly_amount=Decimal(term["monthly_amount"]),
                        company_id=term["company_id"],
                        opening_fee=Decimal(term.get("opening_fee") or 0),
                        expected_disbursement_rate=(
                            Decimal(rate_text) if rate_text not in (None, "") else None
                        ),
                    )
                )
            InstallmentPlanOption.objects.bulk_create(options)

    DealerPriceList.objects.filter(
        brand=price_list.brand,
        period_month=price_list.period_month,
        status=DealerPriceList.Status.PUBLISHED,
    ).exclude(pk=price_list.pk).update(status=DealerPriceList.Status.ARCHIVED)
    price_list.status = DealerPriceList.Status.PUBLISHED
    price_list.brand_name_snapshot = price_list.brand.name
    source_logo = price_list.logo_override or price_list.brand.logo
    if source_logo:
        price_list.published_logo.name = source_logo.name
    price_list.published_at = timezone.now()
    price_list.published_by = user
    price_list.save()
    return price_list
