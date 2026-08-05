import calendar
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP

from django.db.models import Q

from sales.models import BrandRegistrationFeeRule


class UnsupportedRegistrationFee(ValueError):
    pass


@dataclass(frozen=True)
class RegistrationFeeResult:
    rate_class: str
    standard_remaining_days: int
    calendar_remaining_days: int
    plate_fee: int
    license_fee: int
    inspection_fee: int
    road_maintenance_fee: int
    license_tax_fee: int
    compulsory_insurance_fee: int
    pricing_method: str = "formula"
    fixed_total_override: int = 0

    @property
    def fixed_and_variable_total(self):
        if self.fixed_total_override:
            return self.fixed_total_override
        return (
            self.plate_fee
            + self.license_fee
            + self.inspection_fee
            + self.road_maintenance_fee
            + self.license_tax_fee
            + self.compulsory_insurance_fee
        )


RATE_CLASSES = (
    {"code": "M2", "min_cc": 51, "max_cc": 125, "road_annual": 450},
    {"code": "M3", "min_cc": 126, "max_cc": 250, "road_annual": 600},
    {"code": "M4", "min_cc": 251, "max_cc": 500, "road_annual": 900},
    {"code": "M5", "min_cc": 501, "max_cc": 600, "road_annual": 1200},
)


def rate_class_for(displacement_cc):
    for rate in RATE_CLASSES:
        if rate["min_cc"] <= displacement_cc <= rate["max_cc"]:
            return rate
    raise UnsupportedRegistrationFee("第一階段僅支援 51～600 c.c. 的 M2～M5 油車。")


def annual_license_tax(displacement_cc):
    if displacement_cc <= 150:
        return 0
    if displacement_cc <= 250:
        return 800
    if displacement_cc <= 500:
        return 1620
    if displacement_cc <= 600:
        return 2160
    raise UnsupportedRegistrationFee("第一階段僅支援 51～600 c.c. 的 M2～M5 油車。")


def compulsory_insurance(displacement_cc, period_years):
    if period_years not in (1, 2):
        raise UnsupportedRegistrationFee("油車強制險僅支援一年或兩年。")
    if displacement_cc <= 250:
        return 658 if period_years == 1 else 1200
    return 711 if period_years == 1 else 1306


def standard_remaining_days(registration_date):
    standard_day = min(registration_date.day, 30)
    return (
        (12 - registration_date.month) * 30
        + (30 - standard_day)
        + 1
    )


def calendar_remaining_days(registration_date):
    return (date(registration_date.year, 12, 31) - registration_date).days + 1


def calculate_registration_fee(displacement_cc, registration_date, period_years):
    if not displacement_cc:
        raise UnsupportedRegistrationFee("請先在資料維護區的車型資料設定排氣量。")
    rate = rate_class_for(displacement_cc)
    standard_days = standard_remaining_days(registration_date)
    actual_days = calendar_remaining_days(registration_date)
    days_in_year = 366 if calendar.isleap(registration_date.year) else 365

    road_fee = (
        Decimal(rate["road_annual"])
        * Decimal(standard_days)
        / Decimal(360)
    ).quantize(Decimal("1"), rounding=ROUND_DOWN)
    tax_fee = (
        Decimal(annual_license_tax(displacement_cc))
        * Decimal(actual_days)
        / Decimal(days_in_year)
    ).quantize(Decimal("1"), rounding=ROUND_HALF_UP)

    return RegistrationFeeResult(
        rate_class=rate["code"],
        standard_remaining_days=standard_days,
        calendar_remaining_days=actual_days,
        plate_fee=400 if displacement_cc >= 550 else 300,
        license_fee=150,
        inspection_fee=200,
        road_maintenance_fee=int(road_fee),
        license_tax_fee=int(tax_fee),
        compulsory_insurance_fee=compulsory_insurance(
            displacement_cc, period_years
        ),
    )


def resolve_brand_registration_rule(brand, displacement_cc, registration_date):
    return (
        BrandRegistrationFeeRule.objects.filter(
            brand__iexact=brand,
            active=True,
            effective_from__lte=registration_date,
        )
        .filter(Q(effective_to__isnull=True) | Q(effective_to__gte=registration_date))
        .filter(Q(min_cc__isnull=True) | Q(min_cc__lte=displacement_cc))
        .filter(Q(max_cc__isnull=True) | Q(max_cc__gte=displacement_cc))
        .order_by("-effective_from", "-min_cc", "-id")
        .first()
    )


def calculate_vehicle_registration_fee(vehicle_model, registration_date, period_years):
    rule = resolve_brand_registration_rule(
        vehicle_model.brand, vehicle_model.displacement_cc, registration_date
    )
    if rule and rule.calculation_type == BrandRegistrationFeeRule.CalculationType.MANUAL:
        raise UnsupportedRegistrationFee(
            f"{vehicle_model.brand} 此期間設定為人工牌險，請依單據輸入實際金額。"
        )
    if rule and rule.calculation_type == BrandRegistrationFeeRule.CalculationType.FIXED:
        return RegistrationFeeResult(
            rate_class=f"FIXED-{rule.pk}",
            standard_remaining_days=standard_remaining_days(registration_date),
            calendar_remaining_days=calendar_remaining_days(registration_date),
            plate_fee=0,
            license_fee=0,
            inspection_fee=0,
            road_maintenance_fee=0,
            license_tax_fee=0,
            compulsory_insurance_fee=0,
            pricing_method="fixed",
            fixed_total_override=int(rule.fixed_total),
        )
    return calculate_registration_fee(
        vehicle_model.displacement_cc, registration_date, period_years
    )
