"""牌險手續費收入（欄位 agency_fee_income，原稱代辦費收入）：牌險溢收（使用者 2026-10-15、2026-10-19）。

牌險費不含選號；牌險手續費＝牌險費－領牌規費－強制險，少收時為負數。
選號另計：選號收入＝客人付的選號費、選號支出預設監理站 1,000，差額留在選號（使用者 2026-10-15 更正）。
油車沒有領牌日時規費依訂單日預估（`registration_fee_date`），領牌時依領牌日重算；電動類規費與強制險為固定口徑。
牌險費填 0（不向客人收，使用者 2026-10-19）：牌險手續費 0、不標少收；分期單視為分期公司吸收、不列規費與強制險支出，
現金單照列支出（店家吸收）。
"""
from decimal import Decimal

ZERO = Decimal("0")
# 監理站選號費；請其他代辦人員領牌時，選號支出由人工改成實際付出的金額。
PLATE_SELECTION_STATION_FEE = Decimal("1000")


def _money(value):
    return Decimal(str(value or 0))


def _profile(order):
    from sales.models import OrderOperationsProfile

    if not order.pk:
        return None
    try:
        return order.operations
    except OrderOperationsProfile.DoesNotExist:
        return None


# 收支成本固定口徑（使用者 2026-10-15）：電動類規費固定，強制險比照油車級距；微電車固定保三年。
ELECTRIC_REGISTRATION_FEE = Decimal("650")
MICRO_REGISTRATION_FEE = Decimal("450")
MICRO_COMPULSORY_INSURANCE_THREE_YEARS = Decimal("1358")
# 輕型電動車比照 50cc、重型電動車比照 125cc 燃油車的強制險級距。
ELECTRIC_INSURANCE_EQUIVALENT_CC = {"light": 50, "heavy": 125}


def _energy(order):
    model = getattr(order, "vehicle_model", None)
    return getattr(model, "energy_type", "") if model else ""


def _electric_class(order):
    from sales.models import VehicleModel

    if _energy(order) == VehicleModel.EnergyType.LIGHT_ELECTRIC:
        return "light"
    return order.vehicle_model.electric_registration_class or ""


def registration_fee_cost(order):
    """監理站規費：油車為號牌、行照、檢驗、公路養管、牌照稅（依領牌日試算，固定整包規則用整包）；
    重型／輕型電動車固定 650，微型電動二輪車固定 450。"""
    from sales.models import VehicleModel

    energy = _energy(order)
    if energy == VehicleModel.EnergyType.MICRO_ELECTRIC:
        return MICRO_REGISTRATION_FEE
    if energy in (VehicleModel.EnergyType.ELECTRIC, VehicleModel.EnergyType.LIGHT_ELECTRIC):
        return ELECTRIC_REGISTRATION_FEE
    return sum(
        (
            _money(order.registration_plate_fee),
            _money(order.registration_license_fee),
            _money(order.registration_inspection_fee),
            _money(order.road_maintenance_fee),
            _money(order.license_tax_fee),
            _money(order.registration_bundle_fee),
        ),
        ZERO,
    )


def compulsory_insurance_cost(order):
    """強制險支出：油車依排氣量與年期；電動車比照對應油車級距；微電車三年 1,358。"""
    from sales.models import VehicleModel
    from sales.services.registration_fee import UnsupportedRegistrationFee, compulsory_insurance

    energy = _energy(order)
    if energy == VehicleModel.EnergyType.MICRO_ELECTRIC:
        return MICRO_COMPULSORY_INSURANCE_THREE_YEARS
    if energy in (VehicleModel.EnergyType.ELECTRIC, VehicleModel.EnergyType.LIGHT_ELECTRIC):
        cc = ELECTRIC_INSURANCE_EQUIVALENT_CC.get(_electric_class(order))
        if cc:
            try:
                return Decimal(compulsory_insurance(cc, int(order.compulsory_insurance_period or 1)))
            except UnsupportedRegistrationFee:
                pass  # 電動車選了三年等油車表沒有的年期：沿用訂單強制險。
    return _money(order.compulsory_insurance_fee)


def registration_cost_known(order):
    """電動類規費固定，隨時可算；油車規費要等排領牌日試算出來。"""
    from sales.models import VehicleModel

    if _energy(order) == VehicleModel.EnergyType.GAS:
        return registration_fee_cost(order) > 0
    return bool(_energy(order))


def default_plate_selection_expense(order):
    return PLATE_SELECTION_STATION_FEE if _money(order.plate_selection_fee) > 0 else ZERO


def _is_legacy(order):
    return bool(order.pk and hasattr(order, "legacy_snapshot"))


def plate_fee_waived(order):
    """牌險費填 0＝不向客人收；空白（照系統試算）的 0 不算。Excel 匯入單的牌險含在收款價裡，不適用。"""
    return not order.plate_insurance_auto and not _money(order.plate_insurance_fee) and not _is_legacy(order)


def plate_cost_absorbed_by_lender(order):
    """分期單牌險填 0：視為分期公司吸收，收支不列規費與強制險（使用者 2026-10-19 選 b）。"""
    from sales.models import SalesOrder

    return plate_fee_waived(order) and order.payment_type == SalesOrder.PaymentType.INSTALLMENT


def plate_fee_surplus(order, profile=None):
    """牌險溢收；油車規費尚未試算時回傳 None，牌險填 0 時為 0。收支頁人工改過的規費／強制險支出優先。

    Excel 匯入單的牌險含在收款價裡、財務以 Excel 為準，不判斷溢收或少收。
    """
    if _is_legacy(order):
        return None
    if plate_fee_waived(order):
        return ZERO
    if not registration_cost_known(order):
        return None
    profile = profile or _profile(order)
    if profile is not None:
        cost = _money(profile.registration_tax_expense) + _money(profile.compulsory_insurance_expense)
    else:
        cost = registration_fee_cost(order) + compulsory_insurance_cost(order)
    return _money(order.plate_insurance_fee) - cost


def default_agency_fee(order, profile):
    return plate_fee_surplus(order, profile) or ZERO
