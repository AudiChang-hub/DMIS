"""建立訂單精靈：步驟定義、逐步驗證與進度判斷。

每一步都存進訂單草稿，伺服器記錄已完成的步驟；未完成前面的步驟不能進入後面的步驟，
送出前再整張驗證一次，任何一步不合格就回到該步驟。
"""
from django.forms.utils import ErrorDict
from django.http import QueryDict

STEPS = (
    ("vehicle", "車款與來源", "選擇車型、顏色與訂單來源"),
    ("extras", "配件與需求", "配件、選號、交車方式與汰舊"),
    ("owner", "車主與證件", "上傳證件正反面並核對車主資料"),
    ("payment", "付款與訂金", "付款方式、車價、分期與訂金"),
    ("confirm", "確認送出", "核對整張訂單後建立"),
)
STEP_KEYS = tuple(key for key, _label, _hint in STEPS)
STEP_LABELS = {key: label for key, label, _hint in STEPS}
DONE_KEY = "_wizard_done"
ID_CHECK_KEY = "_id_check"
ID_CHECK_ERROR_KEY = "_id_check_error"
ID_MANUAL_KEY = "_id_manual_confirmed"

STEP_FIELDS = {
    "vehicle": {
        "vehicle_energy_type", "vehicle_model", "color", "vehicle_category", "transaction_type", "catalog_selection",
        "source_type", "source", "commission_recipient", "assign_commission_to_other",
        "assisted_company_confirmed", "assisted_company_revision",
    },
    "extras": {
        "trade_in_intent", "is_trade_in_subsidy", "old_owner_same_as_owner", "plate_choice", "watched_numbers",
        "plate_preference_note", "delivery_method", "delivery_destination", "note",
    },
    "owner": {
        "owner_type", "owner_name", "owner_name_en", "owner_phone", "owner_email", "owner_birth_date",
        "owner_nationality", "owner_address", "owner_id_number", "residence_expiry", "id_front", "id_back",
        "id_verified", ID_MANUAL_KEY,
    },
    "payment": {
        "payment_type", "vehicle_price", "vehicle_price_adjustment_reason", "deposit_amount", "deposit_date",
        "deposit_method", "registration_manual", "registration_adjustment_reason", "registration_date",
        "compulsory_insurance_period", "registration_plate_fee", "registration_license_fee",
        "registration_inspection_fee", "road_maintenance_fee", "license_tax_fee", "compulsory_insurance_fee",
        "plate_selection_fee", "lien_registration_fee", "registration_calculated_total", "plate_insurance_fee",
        "installment_company", "installment_custom", "installment_periods", "installment_monthly",
        "installment_opening_fee",
    },
}
FORMSET_STEPS = {"accessories": "extras", "other_fees": "payment"}
SERVER_KEYS = (DONE_KEY,)


def field_step(name):
    for key, names in STEP_FIELDS.items():
        if name in names:
            return key
    return "confirm"


def step_index(key):
    return STEP_KEYS.index(key)


def done_steps(draft):
    done = (draft.data.get(DONE_KEY) if draft else None) or []
    return [key for key in STEP_KEYS if key in done]


def first_open_step(draft):
    done = set(done_steps(draft))
    return next((key for key in STEP_KEYS if key not in done), "confirm")


def allowed_step(draft, requested):
    """只能進入已完成步驟之後的第一個未完成步驟，或任何已完成的步驟。"""
    first_open = first_open_step(draft)
    if requested in STEP_KEYS and step_index(requested) <= step_index(first_open):
        return requested
    return first_open


def mark_done(draft, key):
    done = set(done_steps(draft)) | {key}
    draft.data[DONE_KEY] = [step for step in STEP_KEYS if step in done]


def step_neighbors(key):
    index = step_index(key)
    previous = STEP_KEYS[index - 1] if index else None
    following = STEP_KEYS[index + 1] if index + 1 < len(STEP_KEYS) else None
    return previous, following


def step_list(draft, current):
    done = set(done_steps(draft))
    first_open = first_open_step(draft)
    rows = []
    for number, (key, label, hint) in enumerate(STEPS, start=1):
        if key == current:
            state = "current"
        elif key in done:
            state = "done"
        else:
            state = "locked"
        reachable = key != current and (key in done or key == first_open)
        rows.append({"key": key, "label": label, "hint": hint, "number": number, "state": state, "reachable": reachable})
    return rows


def draft_query_dict(data):
    query = QueryDict(mutable=True)
    for key, value in data.items():
        if key in SERVER_KEYS:
            continue
        query.setlist(key, [str(item) for item in value] if isinstance(value, list) else [str(value)])
    return query


def identity_check_error(data):
    """自然人的證件須自動辨識通過；未通過或無法辨識時須人工確認，並回傳提示。"""
    if data.get("owner_type") not in {"local", "foreign"}:
        return ""
    if data.get(ID_CHECK_KEY) == "passed" or data.get(ID_MANUAL_KEY) in {"on", "1", "true", True}:
        return ""
    reason = (data.get(ID_CHECK_ERROR_KEY) or "").strip()
    if data.get(ID_CHECK_KEY) == "failed" and reason:
        return f"證件自動辨識未通過：{reason} 請重新拍攝，或親自核對證件後勾選「我已人工核對證件正反面」。"
    return "證件尚未完成自動辨識，請等待辨識完成；無法辨識時，請親自核對證件後勾選「我已人工核對證件正反面」。"


def collect_step_errors(form, formsets, extra=None):
    """把表單、明細與額外檢查的錯誤依步驟分組：{step: [(欄位, 訊息)]}。"""
    grouped = {key: [] for key in STEP_KEYS}
    for name, errors in form.errors.items():
        step = "confirm" if name == "__all__" else field_step(name)
        label = form.fields[name].label if name in form.fields else ""
        grouped[step].extend((label, message) for message in errors)
    for prefix, formset in formsets.items():
        step = FORMSET_STEPS[prefix]
        for message in formset.non_form_errors():
            grouped[step].append(("", message))
        for row in formset.forms:
            for name, errors in row.errors.items():
                label = row.fields[name].label if name in row.fields else ""
                grouped[step].extend((label, message) for message in errors)
    for step, messages in (extra or {}).items():
        grouped[step].extend(("", message) for message in messages)
    return grouped


def first_error_step(grouped, upto=None):
    limit = step_index(upto) if upto else len(STEP_KEYS) - 1
    return next((key for key in STEP_KEYS[: limit + 1] if grouped.get(key)), None)


def prune_later_errors(form, formsets, current):
    """重新顯示目前步驟時，隱藏後面步驟尚未填寫造成的錯誤，只保留目前與之前的步驟。"""
    limit = step_index(current)
    for name in list(form.errors):
        step = "confirm" if name == "__all__" else field_step(name)
        if step_index(step) > limit:
            del form._errors[name]
    for prefix, formset in formsets.items():
        if step_index(FORMSET_STEPS[prefix]) > limit:
            formset._non_form_errors = formset.error_class()
            for row in formset.forms:
                row._errors = ErrorDict()
