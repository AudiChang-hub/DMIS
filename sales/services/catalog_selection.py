"""公開選車條件的簽署與驗證；不包含內部撥款或成本欄位。"""
from django.core import signing
from django.core.exceptions import ValidationError
from django.utils import timezone

from sales.models import VehicleModel
from sales.services.price_version import resolve_vehicle_price_version, recommended_vehicle_price
from sales.services.installment_plan import resolve_installment_plan_version

SALT = "catalog-public-selection-v1"
CHANGE_MESSAGE = "車色、售價或分期方案已變更／失效，請按「更換車款／付款方案」重新確認；已填資料會保留。"


def selection_data(model, color, payment_type, option=None):
    version = resolve_vehicle_price_version(model.pk, timezone.localdate())
    price, label = recommended_vehicle_price(version, payment_type)
    return {
        "model": model.pk, "color": color.pk, "model_label": str(model), "color_label": color.name,
        "payment_type": payment_type, "price": str(price) if price is not None else None,
        "price_label": label, "price_version": version.pk if version else None,
        "option": option.pk if option else None,
        "plan_version": option.version_id if option else None,
        "company": option.company.name if option else "",
        "company_id": option.company_id if option else None,
        "periods": option.periods if option else 0,
        "monthly": str(option.monthly_amount) if option else "0",
        "opening_fee": str(option.opening_fee) if option else "0",
    }


def sign_selection(data):
    return signing.dumps(data, salt=SALT, compress=True)


def read_selection(token):
    try:
        if not isinstance(token, str) or len(token) > 4096:
            raise ValueError
        data = signing.loads(token, salt=SALT, max_age=7 * 24 * 3600)
        if not isinstance(data, dict) or data.get("payment_type") not in {"cash", "installment"}:
            raise ValueError
        return data
    except (signing.BadSignature, ValueError, TypeError) as exc:
        raise ValidationError("選車確認已失效，請重新選擇車款與付款方案。") from exc


def validate_selection(token):
    data = read_selection(token)
    model = VehicleModel.objects.filter(pk=data.get("model"), active=True, catalog_entry__published=True).first()
    color = model.colors.filter(pk=data.get("color"), active=True).first() if model else None
    if not color:
        raise ValidationError(CHANGE_MESSAGE)
    option = None
    if data["payment_type"] == "installment":
        plan = resolve_installment_plan_version(model.pk, timezone.localdate())
        option = plan.options.select_related("company").filter(pk=data.get("option"), company__active=True).first() if plan else None
        if not option:
            raise ValidationError(CHANGE_MESSAGE)
    if selection_data(model, color, data["payment_type"], option) != data:
        raise ValidationError(CHANGE_MESSAGE)
    return data


def selection_initial(token):
    data = validate_selection(token)
    return {"vehicle_model": data["model"], "color": data["color"],
            "payment_type": data["payment_type"], "installment_company": data["company"],
            "installment_periods": data["periods"], "catalog_selection": token}
