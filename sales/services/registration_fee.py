import calendar
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP

from django.db.models import Case, IntegerField, Q, Value, When

from sales.models import BrandRegistrationFeeRule, VehicleModel


class UnsupportedRegistrationFee(ValueError):
    pass


class ManualRegistrationFeeRequired(UnsupportedRegistrationFee):
    """此車型刻意不套用預設金額，應保留人員輸入的實際牌險。"""


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


MICRO_ELECTRIC_RATE_CLASS = "EV-MICRO"

RATE_CLASSES = (
    {"code": "M2", "min_cc": 51, "max_cc": 125, "road_annual": 450},
    {"code": "M3", "min_cc": 126, "max_cc": 250, "road_annual": 600},
    {"code": "M4", "min_cc": 251, "max_cc": 500, "road_annual": 900},
    {"code": "M5", "min_cc": 501, "max_cc": 600, "road_annual": 1200},
)


def registration_rate_label(rate_class, displacement_cc=None):
    """將內部費率代碼轉為使用者可理解的排氣量級距。"""
    rate = None
    if displacement_cc not in (None, ""):
        try:
            rate = rate_class_for(int(displacement_cc))
        except (TypeError, ValueError, UnsupportedRegistrationFee):
            rate = None
    if rate is None:
        normalized_code = str(rate_class or "").strip().upper()
        rate = next(
            (item for item in RATE_CLASSES if item["code"] == normalized_code),
            None,
        )
    if not rate:
        return ""
    return f'{rate["min_cc"]}～{rate["max_cc"]} c.c.'


def rate_class_for(displacement_cc):
    for rate in RATE_CLASSES:
        if rate["min_cc"] <= displacement_cc <= rate["max_cc"]:
            return rate
    raise UnsupportedRegistrationFee("第一階段僅支援 51～600 c.c. 的油車。")


def annual_license_tax(displacement_cc):
    if displacement_cc <= 150:
        return 0
    if displacement_cc <= 250:
        return 800
    if displacement_cc <= 500:
        return 1620
    if displacement_cc <= 600:
        return 2160
    raise UnsupportedRegistrationFee("第一階段僅支援 51～600 c.c. 的油車。")


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
        raise UnsupportedRegistrationFee("請先在資料維護區的「機種與售價」設定排氣量。")
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


def brand_registration_rule_candidates(vehicle_model):
    """品牌、能源別、排氣量／領牌級別符合此車型的規則；不限日期、年期與啟用。"""
    energy_types = [vehicle_model.energy_type]
    if vehicle_model.energy_type == VehicleModel.EnergyType.LIGHT_ELECTRIC:
        # 相容既有以「電動車＋輕型級別」建立的規則；若另有輕型電動車
        # 專屬規則，仍優先採用專屬版本。
        energy_types.append(VehicleModel.EnergyType.ELECTRIC)
    rules = BrandRegistrationFeeRule.objects.filter(
        brand__iexact=vehicle_model.brand,
        energy_type__in=energy_types,
    )
    if vehicle_model.energy_type == VehicleModel.EnergyType.GAS:
        rules = rules.filter(
            Q(min_cc__isnull=True) | Q(min_cc__lte=vehicle_model.displacement_cc)
        ).filter(
            Q(max_cc__isnull=True) | Q(max_cc__gte=vehicle_model.displacement_cc)
        )
    elif vehicle_model.energy_type in {
        VehicleModel.EnergyType.ELECTRIC,
        VehicleModel.EnergyType.LIGHT_ELECTRIC,
    }:
        rules = rules.filter(
            electric_registration_class=vehicle_model.electric_registration_class
        )
    return rules


def resolve_brand_registration_rule(vehicle_model, registration_date, period_years):
    rules = (
        brand_registration_rule_candidates(vehicle_model)
        .filter(active=True, effective_from__lte=registration_date)
        .filter(Q(effective_to__isnull=True) | Q(effective_to__gte=registration_date))
        .filter(
            Q(
                calculation_type__in=(
                    BrandRegistrationFeeRule.CalculationType.FORMULA,
                    BrandRegistrationFeeRule.CalculationType.MANUAL,
                )
            )
            | Q(insurance_period_years=period_years)
        )
    )
    if vehicle_model.energy_type == VehicleModel.EnergyType.LIGHT_ELECTRIC:
        rules = rules.annotate(
            energy_priority=Case(
                When(
                    energy_type=VehicleModel.EnergyType.LIGHT_ELECTRIC,
                    then=Value(0),
                ),
                default=Value(1),
                output_field=IntegerField(),
            )
        )
        return rules.order_by(
            "energy_priority", "-effective_from", "-min_cc", "-id"
        ).first()
    return rules.order_by("-effective_from", "-min_cc", "-id").first()


ELECTRIC_ENERGY_TYPES = {
    VehicleModel.EnergyType.ELECTRIC,
    VehicleModel.EnergyType.LIGHT_ELECTRIC,
    VehicleModel.EnergyType.MICRO_ELECTRIC,
}
FIXED_CALCULATION_TYPES = (
    BrandRegistrationFeeRule.CalculationType.FIXED_BUNDLE,
    BrandRegistrationFeeRule.CalculationType.FIXED_COMPONENTS,
)


def registration_period_for(vehicle_model, on_date, period_years):
    """電動類訂單選的強制險年期沒有對應固定規則、而該品牌當日只有一種年期時，改用規則年期（使用者 2026-10-15）。

    微型電動二輪車一定保三年（使用者 2026-10-15）。
    """
    if vehicle_model.energy_type == VehicleModel.EnergyType.MICRO_ELECTRIC:
        return 3
    if vehicle_model.energy_type not in ELECTRIC_ENERGY_TYPES or not on_date:
        return period_years
    if resolve_brand_registration_rule(vehicle_model, on_date, period_years):
        return period_years
    periods = set(
        brand_registration_rule_candidates(vehicle_model)
        .filter(
            active=True,
            calculation_type__in=FIXED_CALCULATION_TYPES,
            effective_from__lte=on_date,
        )
        .filter(Q(effective_to__isnull=True) | Q(effective_to__gte=on_date))
        .values_list("insurance_period_years", flat=True)
    )
    return periods.pop() if len(periods) == 1 else period_years


def registration_fee_date(vehicle_model, registration_date, reference_date, period_years):
    """試算用日期；None 表示先不試算。電動類固定牌險不隨日期變動，有規則就先依訂單日帶入（使用者 2026-10-15）；
    油車沒有領牌日時先依訂單日預估，領牌時依領牌日重算（使用者 2026-10-19）。"""
    if registration_date:
        return registration_date
    if not reference_date:
        return None
    if vehicle_model.energy_type == VehicleModel.EnergyType.GAS:
        return reference_date
    if vehicle_model.energy_type not in ELECTRIC_ENERGY_TYPES:
        return None
    rule = resolve_brand_registration_rule(vehicle_model, reference_date, period_years)
    if rule and rule.calculation_type in FIXED_CALCULATION_TYPES:
        return reference_date
    return None


def has_registration_rate_basis(vehicle_model, registration_date, period_years):
    """油車看排氣量、電動車看領牌級別；微型電動二輪車要有符合領牌日的品牌規則才自動試算，沒有規則照舊依單據人工填寫（使用者 2026-10-14）。"""
    energy_type = vehicle_model.energy_type
    if energy_type == VehicleModel.EnergyType.GAS:
        return bool(vehicle_model.displacement_cc)
    if energy_type in {
        VehicleModel.EnergyType.ELECTRIC,
        VehicleModel.EnergyType.LIGHT_ELECTRIC,
    }:
        return bool(vehicle_model.electric_registration_class)
    if energy_type == VehicleModel.EnergyType.MICRO_ELECTRIC and registration_date:
        return resolve_brand_registration_rule(
            vehicle_model, registration_date, period_years
        ) is not None
    return False


def calculate_vehicle_registration_fee(vehicle_model, registration_date, period_years):
    rule = resolve_brand_registration_rule(
        vehicle_model, registration_date, period_years
    )
    if rule and rule.calculation_type == BrandRegistrationFeeRule.CalculationType.MANUAL:
        raise ManualRegistrationFeeRequired(
            f"{vehicle_model.brand} 此期間設定為人工牌險，請依單據輸入實際金額。"
        )
    if (
        rule
        and rule.calculation_type
        == BrandRegistrationFeeRule.CalculationType.FIXED_COMPONENTS
    ):
        # 訂單費率級距欄位只有 10 字元，固定規則用短代碼。
        rate_class = f"FC-{rule.pk}"
        if vehicle_model.energy_type in {
            VehicleModel.EnergyType.ELECTRIC,
            VehicleModel.EnergyType.LIGHT_ELECTRIC,
        }:
            rate_class = f"EV-{vehicle_model.electric_registration_class.upper()}"
        elif vehicle_model.energy_type == VehicleModel.EnergyType.MICRO_ELECTRIC:
            # 訂單費率級距欄位只有 10 字元。
            rate_class = MICRO_ELECTRIC_RATE_CLASS
        return RegistrationFeeResult(
            rate_class=rate_class,
            standard_remaining_days=standard_remaining_days(registration_date),
            calendar_remaining_days=calendar_remaining_days(registration_date),
            plate_fee=int(rule.fixed_registration_fee),
            license_fee=0,
            inspection_fee=0,
            road_maintenance_fee=0,
            license_tax_fee=0,
            compulsory_insurance_fee=int(rule.fixed_compulsory_insurance_fee),
            pricing_method="fixed_components",
        )
    if (
        rule
        and rule.calculation_type
        == BrandRegistrationFeeRule.CalculationType.FIXED_BUNDLE
    ):
        return RegistrationFeeResult(
            rate_class=(
                MICRO_ELECTRIC_RATE_CLASS
                if vehicle_model.energy_type == VehicleModel.EnergyType.MICRO_ELECTRIC
                else f"FB-{rule.pk}"
            ),
            standard_remaining_days=standard_remaining_days(registration_date),
            calendar_remaining_days=calendar_remaining_days(registration_date),
            plate_fee=0,
            license_fee=0,
            inspection_fee=0,
            road_maintenance_fee=0,
            license_tax_fee=0,
            compulsory_insurance_fee=0,
            pricing_method="fixed_bundle",
            fixed_total_override=int(rule.fixed_total),
        )
    if vehicle_model.energy_type != VehicleModel.EnergyType.GAS:
        raise UnsupportedRegistrationFee(
            f"{vehicle_model.brand} 此電動車級別尚未建立有效牌險規則，請先至資料維護區設定。"
        )
    return calculate_registration_fee(
        vehicle_model.displacement_cc, registration_date, period_years
    )
