"""建立訂單精靈：步驟定義、逐步驗證與進度判斷。

每一步都存進訂單草稿，伺服器記錄已完成的步驟；未完成前面的步驟不能進入後面的步驟，
送出前再整張驗證一次，任何一步不合格就回到該步驟。
"""
from django.forms.utils import ErrorDict
from django.http import QueryDict

# 一步只處理一件事，一次只問一件事（使用者 2026-10-10 拆步驟）。
# 使用者 2026-10-15：順序改為車款→付款與車價→車主→汰舊與補助→選號與交車→訂金（2026-10-16 前兩步合併）；
# 使用者 2026-10-16：車款與來源、付款與車價合併為同一步——跟客人確認車款就接著寫價格。
# 使用者 2026-10-17：配件加回接單流程，可略過，不選配件也能直接下一步；
# 同日改為配件在前、訂金與費用在後（確認前一步），訂金頁列出車價、牌險費、配件與三項合計；
# 同日訂單備註從選號與交車移到訂金與費用，談完金額再補充說明。
STEPS = (
    ("vehicle", "車款與車價", "車型、顏色、來源，接著付款方式、車價與領牌規費"),
    ("owner", "車主與證件", "上傳證件正反面並核對車主資料"),
    ("tradein", "汰舊與補助", "是否汰舊、申請補助與舊車主"),
    ("delivery", "選號與交車", "選號方式與交車方式"),
    ("accessories", "配件（可略過）", "加購配件、數量與安裝工資；沒有配件直接下一步"),
    ("deposit", "訂金與費用", "目前金額、訂金、其他費用、備註與附件"),
    ("confirm", "確認送出", "核對整張訂單後建立"),
)
# 舊版草稿的步驟代號（拆步驟前）：完成「extras」等於完成配件、汰舊與補助、選號與交車；舊的「payment」含訂金。
# 1.83 的「payment」已併入「vehicle」；只完成 vehicle 的舊草稿在送出前整張驗證時會回到這一步補齊。
LEGACY_DONE = {"extras": ("accessories", "tradein", "delivery"), "payment": ("deposit",)}
STEP_KEYS = tuple(key for key, _label, _hint in STEPS)
STEP_LABELS = {key: label for key, label, _hint in STEPS}
DONE_KEY = "_wizard_done"
ID_CHECK_KEY = "_id_check"
ID_CHECK_ERROR_KEY = "_id_check_error"

STEP_FIELDS = {
    "vehicle": {
        "vehicle_energy_type", "vehicle_model", "color", "vehicle_category", "transaction_type", "catalog_selection",
        "source_type", "source", "commission_recipient", "assign_commission_to_other",
        "payment_type", "payment_splits", "vehicle_price", "vehicle_price_adjustment_reason", "registration_manual", "registration_adjustment_reason", "registration_date",
        "compulsory_insurance_period", "registration_plate_fee", "registration_license_fee",
        "registration_inspection_fee", "road_maintenance_fee", "license_tax_fee", "compulsory_insurance_fee",
        "lien_registration_fee", "registration_calculated_total", "plate_insurance_fee",
        "installment_company", "installment_custom", "installment_periods", "installment_monthly",
        "installment_opening_fee",
    },
    "tradein": {"trade_in_intent", "subsidy_programs", "subsidy_other", "is_trade_in_subsidy", "old_owner_same_as_owner"},
    "delivery": {
        "plate_choice", "plate_selection_fee", "watched_numbers", "plate_preference_note",
        "delivery_method", "delivery_destination",
    },
    "owner": {
        "owner_type", "owner_name", "owner_name_en", "owner_phone", "owner_email", "owner_birth_date",
        "owner_nationality", "owner_address", "owner_id_number", "residence_expiry", "id_front", "id_back",
        "id_verified",
    },
    "deposit": {
        "deposit_amount", "deposit_date", "deposit_method", "deposit_received", "intake_discount_mode", "intake_discount_amount",
        "intake_discount_rate", "intake_discount_reason", "note",
    },
}
FORMSET_STEPS = {"accessories": "accessories", "other_fees": "deposit"}
SERVER_KEYS = (DONE_KEY,)


def field_step(name):
    for key, names in STEP_FIELDS.items():
        if name in names:
            return key
    return "confirm"


def step_index(key):
    return STEP_KEYS.index(key)


def done_steps(draft):
    done = set((draft.data.get(DONE_KEY) if draft else None) or [])
    if "extras" in done:  # 拆步驟前的草稿
        for legacy, keys in LEGACY_DONE.items():
            if legacy in done:
                done.update(keys)
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
        elif key == first_open:
            state = "todo"
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
