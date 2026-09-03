import re

from django.db.models import Q

from sales.models import VehicleBrand


def split_brand_aliases(value):
    return [
        item.strip()
        for item in re.split(r"[、,，\n\r]+", value or "")
        if item.strip()
    ]


def canonical_vehicle_brand_name(value, *, create_missing=False):
    """將外部品牌寫法轉成主檔名稱；交易資料仍保存當時的名稱快照。"""
    raw = (value or "").strip()
    if not raw:
        return ""
    direct = VehicleBrand.objects.filter(name__iexact=raw).first()
    if direct:
        return direct.name
    key = raw.casefold()
    for brand in VehicleBrand.objects.exclude(aliases=""):
        if key in {alias.casefold() for alias in split_brand_aliases(brand.aliases)}:
            return brand.name
    if not create_missing:
        return raw
    brand, _created = VehicleBrand.objects.get_or_create(
        name=raw,
        defaults={
            "active": True,
            "display_order": 900,
            "note": "由匯入資料自動建立",
        },
    )
    return brand.name


def vehicle_brand_search_names(value):
    """主品牌搜尋會涵蓋子品牌；子品牌搜尋仍只找該子品牌。"""
    raw = (value or "").strip()
    if not raw:
        return []
    canonical = canonical_vehicle_brand_name(raw)
    brand = VehicleBrand.objects.filter(name__iexact=canonical).first()
    if not brand:
        return []
    names = [brand.name]
    if not brand.parent_id:
        names.extend(brand.sub_brands.values_list("name", flat=True))
    return names


def vehicle_brand_search_q(value, field_name="brand"):
    """建立一般資料查詢條件；不應用於傭金或費率規則解析。"""
    query = Q(**{f"{field_name}__icontains": value})
    names = vehicle_brand_search_names(value)
    if names:
        query |= Q(**{f"{field_name}__in": names})
    return query


def vehicle_brand_is_used(name):
    from sales.models import (
        BrandRegistrationFeeRule,
        DealerVolumeBonusBrand,
        DealerVolumeBonusRule,
        SalesSourceBrandPolicy,
        VehicleModel,
    )

    return any(
        model.objects.filter(brand__iexact=name).exists()
        for model in (
            VehicleModel,
            SalesSourceBrandPolicy,
            DealerVolumeBonusRule,
            DealerVolumeBonusBrand,
            BrandRegistrationFeeRule,
        )
    )


def rename_vehicle_brand_references(old_name, new_name):
    from sales.models import (
        BrandRegistrationFeeRule,
        DealerVolumeBonusBrand,
        DealerVolumeBonusRule,
        SalesSourceBrandPolicy,
        VehicleModel,
    )

    if old_name == new_name:
        return
    for model in (
        VehicleModel,
        SalesSourceBrandPolicy,
        DealerVolumeBonusRule,
        BrandRegistrationFeeRule,
    ):
        model.objects.filter(brand__iexact=old_name).update(brand=new_name)
    DealerVolumeBonusBrand.objects.filter(brand__iexact=old_name).update(brand=new_name)
