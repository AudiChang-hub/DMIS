from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from django.db import transaction

from sales.models import (
    BusinessHoliday,
    DealerVolumeBonusRule,
    DealerVolumeBonusTier,
    SalesSource,
    SalesSourceCategory,
    SalesSourceBrandPolicy,
    VehicleColor,
    VehicleModel,
    VehiclePriceVersion,
)
from sales.services.vehicle_brands import canonical_vehicle_brand_name


BRAND_NAMES = {
    "台鈴 Suzuki": "SUZUKI",
    "三陽 SYM": "SYM",
    "山葉 Yamaha": "YAMAHA",
    "光陽 Kymco": "KYMCO",
    "比雅久 PGO": "PGO",
    "宏佳騰 Aeon": "AEON",
    "睿能 Gogoro": "GOGORO",
    "爍魔 THEMO": "THEMO",
    "中華 eMoving": "eMOVING",
}

ENERGY_TYPES = {
    "oil": VehicleModel.EnergyType.GAS,
    "gas": VehicleModel.EnergyType.GAS,
    "electric": VehicleModel.EnergyType.ELECTRIC,
    "light_electric": VehicleModel.EnergyType.LIGHT_ELECTRIC,
    "micro_electric": VehicleModel.EnergyType.MICRO_ELECTRIC,
}

MODEL_TYPES = {
    label: value for value, label in VehicleModel.ModelType.choices
} | {value: value for value, _label in VehicleModel.ModelType.choices}


def _date(value):
    if not value:
        return None
    return date.fromisoformat(str(value)[:10])


def _decimal(value, default=None):
    if value in (None, ""):
        return default
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return default


def _integer(value):
    number = _decimal(value)
    return int(number) if number is not None else None


def _brand(value):
    value = (value or "").strip()
    return canonical_vehicle_brand_name(
        BRAND_NAMES.get(value, value), create_missing=True
    )


def _model_name(value):
    value = (value or "未命名車型").strip()
    return re.sub(r"\s+[一二三四五六七八九十]+期$", "", value).strip()


LEGACY_ODOO_NOTE_MARKER = re.compile(
    r"\[Odoo(?: [^\]\r\n]+)? 遷移 ID:[^\]\r\n]+\](?:\r?\n)?",
    flags=re.IGNORECASE,
)


def _legacy_note(note, max_length=None):
    """Keep useful imported notes without exposing obsolete Odoo identifiers."""
    cleaned = LEGACY_ODOO_NOTE_MARKER.sub("", note or "").strip()
    return cleaned[:max_length] if max_length else cleaned


def _merge_note_lines(base_note, lines):
    """Merge useful legacy details into the single source note, idempotently."""
    paragraphs = [part.strip() for part in (base_note or "").split("\n") if part.strip()]
    for line in lines:
        cleaned = (line or "").strip()
        if cleaned and cleaned not in paragraphs:
            paragraphs.append(cleaned)
    return "\n".join(paragraphs)


def _legacy_contact_note_lines(dealer):
    people = []
    owner = (dealer.get("owner_name") or "").strip()
    manager = (dealer.get("store_manager") or "").strip()
    if owner and owner != "未知":
        people.append((owner, "負責人", dealer.get("phone_1") or ""))
    if manager and manager != "未知" and manager != owner:
        people.append((manager, "聯絡人", dealer.get("phone_2") or ""))
    lines = []
    for person, relationship, phone in people:
        details = [f"電話：{phone.strip()}"] if phone and phone.strip() else []
        mobile = (dealer.get("mobile") or "").strip()
        email = (dealer.get("email") or "").strip()
        if mobile:
            details.append(f"手機：{mobile}")
        if email:
            details.append(f"Email：{email}")
        line = f"歷史聯絡資料：{person}（{relationship}）"
        lines.append(f"{line}｜{'／'.join(details)}" if details else line)
    return lines


def _legacy_price_source_note(note):
    """Keep useful pricing context without exposing obsolete system metadata."""
    note = (note or "").strip()
    if not note or note == "Odoo 現行價格":
        return "歷史價格資料匯入"
    return note[:250]


def _source_for_legacy(dealer, summary, apply):
    store_type = (dealer.get("store_type_name") or "").strip()
    source_type = (
        SalesSource.SourceType.PLATFORM
        if store_type == "網路平台"
        else SalesSource.SourceType.STORE
        if store_type == "店內員工"
        else SalesSource.SourceType.DEALER
    )
    code = (dealer.get("code") or "").strip()
    name = (dealer.get("name") or "").strip()
    if not name:
        summary["skipped_invalid_sources"] += 1
        return None
    existing = None
    if code:
        existing = SalesSource.objects.filter(code=code).first()
    if not existing:
        existing = SalesSource.objects.filter(
            source_type=source_type, name=name
        ).first()
    if not apply:
        summary["sources_update" if existing else "sources_create"] += 1
        return existing

    capacity = max(
        dealer.get("sym_dispatch_capacity") or 0,
        dealer.get("suzuki_dispatch_capacity") or 0,
    ) or None
    has_line_group = bool(dealer.get("line_group"))
    category_name = store_type or (
        "網路平台"
        if source_type == SalesSource.SourceType.PLATFORM
        else "合作車行"
    )
    category, _ = SalesSourceCategory.objects.get_or_create(
        name=category_name,
        defaults={"system_behavior": source_type, "active": True},
    )
    imported_note = _merge_note_lines(
        _legacy_note(dealer.get("note")), _legacy_contact_note_lines(dealer)
    )
    defaults = {
        "source_type": source_type,
        "category": category,
        "name": name,
        "code": code,
        "phone": (dealer.get("phone_1") or dealer.get("phone") or "").strip(),
        "fax": (dealer.get("mobile_fax") or "").strip(),
        "address": (dealer.get("address") or "").strip(),
        "vehicle_capacity": capacity,
        "holiday_gift": bool(dealer.get("holiday_gift")),
        "has_line_group": has_line_group,
        "note": imported_note,
        "active": bool(dealer.get("active", True)),
    }
    if existing:
        for field, value in defaults.items():
            current = getattr(existing, field)
            if field == "note":
                cleaned_current = _legacy_note(current)
                setattr(existing, field, _merge_note_lines(cleaned_current, value.split("\n")))
            elif field == "has_line_group":
                if value:
                    setattr(existing, field, True)
            elif current in (None, ""):
                setattr(existing, field, value)
        existing.save()
        source = existing
        summary["sources_update"] += 1
    else:
        source = SalesSource.objects.create(**defaults)
        summary["sources_create"] += 1

    summary["source_notes_merged"] += len(_legacy_contact_note_lines(dealer))
    return source


def _model_key(product):
    model_number = (product.get("model") or product.get("internal_code") or "").strip()
    year = _integer(product.get("production_year") or product.get("year"))
    model_code = MODEL_TYPES.get((product.get("brake_type") or "").strip(), "")
    return {
        "brand": _brand(product.get("brand_name")),
        "name": _model_name(product.get("name") or product.get("template_family_name")),
        "model_number": model_number,
        "model_year": year,
        "model_code": model_code,
    }


@transaction.atomic
def import_odoo_master_data(payload, *, apply=False):
    if payload.get("schema_version") != 1:
        raise ValueError("不支援的 Odoo 匯出格式版本。")
    summary = defaultdict(int)
    source_by_legacy_id = {}
    for dealer in payload.get("dealers", []):
        source = _source_for_legacy(dealer, summary, apply)
        if source:
            source_by_legacy_id[dealer["id"]] = source

    if apply:
        brand_rows = list(payload.get("dealer_brand_auth", []))
        authenticated_pairs = {
            (row["dealer_id"], row.get("brand_id")) for row in brand_rows
        }
        brand_rows.extend(
            {
                **row,
                "id": f"legacy-rel-{row['dealer_id']}-{row['brand_id']}",
                "auth_type": "legacy_relation",
            }
            for row in payload.get("legacy_dealer_brands", [])
            if (row["dealer_id"], row.get("brand_id")) not in authenticated_pairs
        )
        for auth in brand_rows:
            source = source_by_legacy_id.get(auth["dealer_id"])
            if not source:
                summary["brand_policies_skipped"] += 1
                continue
            effective_from = _date(auth.get("create_date")) or date(2026, 1, 1)
            SalesSourceBrandPolicy.objects.update_or_create(
                source=source,
                brand=_brand(auth.get("brand_name")),
                effective_from=effective_from,
                defaults={
                    "cooperates": auth.get("auth_type") != "none",
                    "commission_adjustment": 0,
                    "note": _legacy_note(
                        f"原品牌授權：{auth.get('auth_type') or '未記錄'}",
                        max_length=250,
                    ),
                },
            )
            summary["brand_policies_upsert"] += 1
    else:
        summary["brand_policies_upsert"] = len(payload.get("dealer_brand_auth", [])) + len(
            payload.get("legacy_dealer_brands", [])
        )

    model_by_legacy_id = {}
    created_model_ids = set()
    product_commissions = {}
    for rule in payload.get("product_commissions", []):
        amount = _decimal(rule.get("base_amount"), Decimal("0"))
        for product_id in rule.get("product_ids") or []:
            product_commissions[product_id] = amount
    for product in payload.get("products", []):
        key = _model_key(product)
        existing = VehicleModel.objects.filter(**key).first()
        if not apply:
            summary["models_update" if existing else "models_create"] += 1
            continue
        defaults = {
            "energy_type": ENERGY_TYPES.get(
                (product.get("energy_type") or "").strip(),
                VehicleModel.EnergyType.GAS,
            ),
            "displacement_cc": _integer(
                product.get("resolved_engine_displacement")
                or product.get("engine_displacement")
            ),
            "horsepower_hp": _decimal(product.get("ev_max_hp") or product.get("max_hp")),
            "base_dealer_commission": product_commissions.get(
                product["id"], Decimal("0")
            ),
            "active": bool(product.get("active", True)),
        }
        if existing:
            for field, value in defaults.items():
                if value not in (None, ""):
                    setattr(existing, field, value)
            existing.save()
            model = existing
            summary["models_update"] += 1
        else:
            model = VehicleModel.objects.create(**key, **defaults)
            created_model_ids.add(model.id)
            summary["models_create"] += 1
        model_by_legacy_id[product["id"]] = model
        if (
            defaults["energy_type"] == VehicleModel.EnergyType.GAS
            and not defaults["displacement_cc"]
        ):
            summary["gas_models_missing_displacement_review_required"] += 1

    if apply:
        for color in payload.get("product_colors", []):
            model = model_by_legacy_id.get(color["product_id"])
            name = (color.get("name") or "").strip()
            if not model or not name:
                summary["colors_skipped"] += 1
                continue
            VehicleColor.objects.update_or_create(
                vehicle_model=model,
                name=name,
                defaults={"active": bool(color.get("active", True))},
            )
            summary["colors_upsert"] += 1
    else:
        summary["colors_upsert"] = len(payload.get("product_colors", []))

    prices_by_product = defaultdict(list)
    for row in payload.get("price_versions", []):
        prices_by_product[row["product_id"]].append(row)
    if apply:
        for product in payload.get("products", []):
            model = model_by_legacy_id.get(product["id"])
            if not model:
                continue
            rows = prices_by_product.get(product["id"], [])
            if not rows:
                rows = [
                    {
                        "version_id": f"flat-{product['id']}",
                        "version_name": "Odoo 現行價格",
                        "effective_date": product.get("create_date"),
                        "cash_price": product.get("cash_price"),
                        "list_price": product.get("suggested_price")
                        or product.get("list_price"),
                        "line_note": product.get("promo_note") or product.get("price_change_note"),
                    }
                ]
            if model.id not in created_model_ids and model.price_versions.exists():
                summary["price_versions_preserved"] += len(rows)
                continue
            rows.sort(key=lambda row: (_date(row.get("effective_date")) or date.min, str(row.get("version_id"))))
            for index, row in enumerate(rows):
                effective_from = _date(row.get("effective_date")) or date(2026, 1, 1)
                next_date = (
                    _date(rows[index + 1].get("effective_date"))
                    if index + 1 < len(rows)
                    else None
                )
                cash_price = _decimal(row.get("cash_price"))
                list_price = _decimal(row.get("list_price"))
                VehiclePriceVersion.objects.update_or_create(
                    vehicle_model=model,
                    effective_from=effective_from,
                    defaults={
                        "suggested_price": list_price,
                        "suggested_price_includes_registration": True,
                        "cash_price": cash_price,
                        "announced_on": effective_from,
                        "effective_to": next_date - timedelta(days=1) if next_date else None,
                        "source_note": _legacy_price_source_note(
                            row.get("line_note") or row.get("version_name")
                        ),
                        "active": True,
                    },
                )
                summary["price_versions_upsert"] += 1
    else:
        summary["price_versions_candidate"] = sum(
            max(1, len(prices_by_product.get(product["id"], [])))
            for product in payload.get("products", [])
        )

    if apply:
        for rule in payload.get("dealer_commission_rules", []):
            brand = _brand(rule.get("brand_name"))
            effective_from = _date(rule.get("create_date")) or date(2026, 1, 1)
            for legacy_dealer_id in rule.get("dealer_ids") or []:
                source = source_by_legacy_id.get(legacy_dealer_id)
                if not source or not brand:
                    summary["dealer_adjustments_skipped"] += 1
                    continue
                SalesSourceBrandPolicy.objects.update_or_create(
                    source=source,
                    brand=brand,
                    effective_from=effective_from,
                    defaults={
                        "cooperates": True,
                        "commission_adjustment": _decimal(
                            rule.get("addon_amount"), Decimal("0")
                        ),
                        "note": _legacy_note(
                            rule.get("note") or rule.get("name"),
                            max_length=250,
                        ),
                    },
                )
                summary["dealer_adjustments_upsert"] += 1
    else:
        summary["dealer_adjustments_upsert"] = sum(
            len(rule.get("dealer_ids") or [])
            for rule in payload.get("dealer_commission_rules", [])
        )

    if apply:
        brand_sources = defaultdict(set)
        for auth in payload.get("dealer_brand_auth", []):
            if auth.get("auth_type") != "none" and auth["dealer_id"] in source_by_legacy_id:
                brand_sources[_brand(auth.get("brand_name"))].add(auth["dealer_id"])
        for rule in payload.get("volume_rules", []):
            brand = _brand(rule.get("brand_name"))
            dealer_ids = set(rule.get("dealer_ids") or [])
            if rule.get("rule_type") == "general" and not dealer_ids:
                dealer_ids = brand_sources.get(brand, set())
            for legacy_dealer_id in dealer_ids:
                source = source_by_legacy_id.get(legacy_dealer_id)
                starts_on = _date(rule.get("date_from"))
                ends_on = _date(rule.get("date_to"))
                if not source or not brand or not starts_on or not ends_on:
                    summary["volume_rules_skipped"] += 1
                    continue
                imported, _ = DealerVolumeBonusRule.objects.update_or_create(
                    dealer=source,
                    brand=brand,
                    starts_on=starts_on,
                    ends_on=ends_on,
                    defaults={
                        "active": bool(rule.get("active", True)),
                        "note": _legacy_note(rule.get("note") or rule.get("name")),
                    },
                )
                DealerVolumeBonusTier.objects.update_or_create(
                    rule=imported,
                    minimum_quantity=max(_integer(rule.get("min_qty")) or 1, 1),
                    defaults={
                        "bonus_per_vehicle": _decimal(
                            rule.get("bonus_per_unit"), Decimal("0")
                        )
                    },
                )
                summary["volume_rules_upsert"] += 1
    else:
        summary["volume_rules_candidate"] = len(payload.get("volume_rules", []))

    if apply:
        for holiday in payload.get("holidays", []):
            holiday_date = _date(holiday.get("date"))
            if not holiday_date:
                summary["holidays_skipped"] += 1
                continue
            name = (holiday.get("name") or "國定假日").strip()
            note = (holiday.get("note") or "").strip()
            BusinessHoliday.objects.update_or_create(
                date=holiday_date,
                defaults={
                    "name": f"{name}（{note}）" if note else name,
                    "active": True,
                },
            )
            summary["holidays_upsert"] += 1
    else:
        summary["holidays_upsert"] = len(payload.get("holidays", []))

    summary["installment_lines_review_required"] = len(
        payload.get("installment_lines", [])
    )
    summary["legacy_transactions_not_imported"] = payload.get(
        "legacy_only_counts", {}
    ).get("dms_sale_order", 0)
    summary["physical_incentive_rules_not_imported"] = (
        payload.get("legacy_only_counts", {}).get("dms_incentive_rule", 0)
        + payload.get("legacy_only_counts", {}).get("dms_commission_volume_gift", 0)
    )
    if not apply:
        transaction.set_rollback(True)
    return dict(summary)
