"""訂單回匯批次修改（T-232 第 3a 版：不牽涉金額的欄位）。

流程：上傳本系統匯出、改好的 xlsx → `read_workbook` 讀出每列的值 → `build_plan` 依「匯出時／系統現值／檔案值」
三方比對並用訂單頁同一份表單驗證 → 使用者在預覽勾選衝突、清除、完成後修正與不匯入的列 → `apply_plan`
在同一個交易裡逐張呼叫訂單頁自動儲存的同一段存檔流程（`services/order_save.py`），任何一張失敗整批退回。

這一版只寫入第一批欄位（車主、交車與選號、備註、汰舊舊車主、舊車與報廢、車控電池帳號）。其他標成可回匯的
金額欄位（3b）改了只列「下一版開放，已忽略」；車主證件號碼列「不可修改，已忽略」；只能看的欄位列「已忽略」。
"""
import hashlib
import json
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django.core import signing
from django.db import transaction
from django.http import QueryDict

from sales.models import OrderEvent, OrderExportRecord, OrderOperationsProfile, SalesOrder

from . import columns as cols
from .retention import is_expired
from .workbook import ID_KEY, META_SHEET, SHEET_TITLE, unsign_token

MAX_ROWS = 200
MAX_BYTES = 5 * 1024 * 1024
EVENT = "bulk_update"

CONTENT, SUBSIDY, OLD_VEHICLE, FULFILLMENT = "content", "subsidy", "old_vehicle", "fulfillment"
SECTION_LABELS = {CONTENT: "訂車與配件", SUBSIDY: "汰舊補助資料", OLD_VEHICLE: "舊車與報廢", FULFILLMENT: "車控與電池"}
# 每個區段在訂單頁的自動儲存端點；寫入前用同一條路由檢查權限（與訂單頁相同）。
SECTION_ROUTES = {CONTENT: "order_edit", SUBSIDY: "subsidy_data_update",
                  OLD_VEHICLE: "order_operations", FULFILLMENT: "order_operations"}
# 訂單頁的中介層對這兩個端點的 POST 另外要求「訂單內部財務」修改權限（access/middleware.py），回匯照做。
FINANCE_GUARDED_ROUTES = frozenset({"order_edit", "order_operations"})
FIELD_SECTION = {
    **{key: CONTENT for key in (
        "owner_type", "owner_name", "owner_name_en", "owner_phone", "owner_email", "owner_birth_date", "owner_address",
        "owner_nationality", "residence_expiry", "delivery_method", "delivery_destination", "plate_choice",
        "watched_numbers", "plate_preference_note", "note", "trade_in_intent")},
    **{key: SUBSIDY for key in (
        "trade_in_plate", "old_owner_name", "old_owner_id_number", "old_owner_phone", "old_owner_same_as_owner")},
    **{key: OLD_VEHICLE for key in (
        "old_vehicle_engine_number", "old_vehicle_brand", "old_vehicle_displacement_cc",
        "old_vehicle_manufactured_on", "scrapped_on", "recycled_on")},
    **{key: FULFILLMENT for key in (
        "vehicle_control_account", "battery_plan", "battery_activated_on", "battery_account", "battery_rate_plan")},
}
SECTION_ORDER = (CONTENT, SUBSIDY, OLD_VEHICLE, FULFILLMENT)
# 與「用 Excel 更新既有訂單」相同：系統必填或有佔位值的欄位不能用 Excel 清空。
NOT_CLEARABLE = frozenset({"owner_name", "owner_phone", "owner_address"})
FORMULA_PREFIXES = ("=", "+", "-", "@")
DATE_FORMATS = ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d")

IGNORED_READONLY = "只能看，已忽略"
IGNORED_ORDER_PAGE = "不可修改，已忽略（請到訂單頁修改）"
IGNORED_NEXT_VERSION = "金額類欄位下一版開放，已忽略"


class ReimportError(Exception):
    """整份檔案不能回匯（不是本系統匯出、簽章不符、紀錄過期、超過上限等）。"""


class PlanChanged(Exception):
    """預覽之後系統資料或檔案比對結果有變，整批不寫入。"""


class ApplyFailed(Exception):
    def __init__(self, messages):
        super().__init__("；".join(messages))
        self.messages = messages


# ---------------------------------------------------------------- 讀檔

def _unsanitize(text):
    # 匯出時防公式注入加的單引號（excel_export.sanitize_excel_value），讀回時拿掉，才能跟原值比對。
    if text.startswith("'") and text[1:].lstrip("\t\r\n").startswith(FORMULA_PREFIXES):
        return text[1:]
    return text


def _number_text(value):
    try:
        number = Decimal(str(value).replace(",", "").strip())
    except InvalidOperation:
        return None
    return format(number.normalize(), "f") if number == number.to_integral_value() else format(number, "f")


def normalize_cell(value, column, *, formula=False):
    """把儲存格整理成與匯出基準值（`columns.baseline_text`）相同的格式；回傳 (文字, 錯誤訊息)。"""
    if formula:
        return "", "不能用公式，請改成直接輸入值"
    if value is None or (isinstance(value, str) and not value.strip()):
        return "", ""
    if column.kind == cols.DATE:
        if isinstance(value, datetime):
            return value.date().isoformat(), ""
        if isinstance(value, date):
            return value.isoformat(), ""
        text = str(value).strip()
        for pattern in DATE_FORMATS:
            try:
                return datetime.strptime(text, pattern).date().isoformat(), ""
            except ValueError:
                continue
        return text, "日期格式不正確，請用 2026-08-01"
    if column.kind in (cols.NUMBER, cols.MONEY):
        text = _number_text(value)
        return (text, "") if text is not None else (str(value).strip(), "請輸入數字")
    if column.kind == cols.BOOL:
        if value in (True, "是"):
            return "是", ""
        if value in (False, "否"):
            return "否", ""
        return str(value).strip(), "請填「是」或「否」"
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = _unsanitize(str(value)).strip()
    if column.choices and text not in column.choices:
        return text, "請從下拉清單選擇：" + "、".join(column.choices)
    return text, ""


def _current(order, column):
    return cols.baseline_text(column.getter(order), column.kind).strip()


def read_workbook(upload):
    """讀上傳的 xlsx；回傳 (匯出紀錄, 欄位代碼, 各列, 略過的列)。整份不能用時丟 ReimportError。"""
    from openpyxl import load_workbook

    try:
        book = load_workbook(upload, data_only=False)
    except Exception as error:  # 壞檔、加密檔等
        raise ReimportError("讀不到這個 Excel 檔，請確認是本系統匯出的 .xlsx。") from error
    if META_SHEET not in book.sheetnames or SHEET_TITLE not in book.sheetnames:
        raise ReimportError("這不是本系統「匯出訂單」產生的檔案，請先匯出、改好後再匯回。")
    try:
        token = unsign_token(book[META_SHEET]["A2"].value or "")
        record = OrderExportRecord.objects.get(token=token)
    except (signing.BadSignature, OrderExportRecord.DoesNotExist, ValueError) as error:
        raise ReimportError("檔案的匯出代碼對不上，可能被改過或不是本系統匯出的檔案，請重新匯出。") from error
    if is_expired(record):
        raise ReimportError(f"這份檔案匯出超過 {cols.BASELINE_DAYS} 天，比對用的原值已清除，請重新匯出後再改。")
    sheet = book[SHEET_TITLE]
    codes = [cell.value for cell in sheet[1]]
    if not codes or codes[0] != ID_KEY:
        raise ReimportError("檔案第 1 列的欄位代碼被改動或刪除了，請重新匯出。")
    columns = [(index, cols.COLUMN_BY_KEY[code]) for index, code in enumerate(codes) if code in cols.COLUMN_BY_KEY]
    rows, skipped = [], []
    for row_number, cells in enumerate(sheet.iter_rows(min_row=3), start=3):
        if all(cell.value in (None, "") for cell in cells):
            continue
        raw_id = cells[0].value if cells else None
        if raw_id in (None, ""):
            skipped.append(row_number)
            continue
        values, errors = {}, {}
        for index, column in columns:
            cell = cells[index] if index < len(cells) else None
            text, error = normalize_cell(cell.value if cell is not None else None, column,
                                         formula=cell is not None and cell.data_type == "f")
            values[column.key] = text
            if error:
                errors[column.key] = error
        rows.append({"row": row_number, "id": str(raw_id).strip(), "values": values, "errors": errors})
    if len(rows) > MAX_ROWS:
        raise ReimportError(f"一次最多回匯 {MAX_ROWS} 張訂單，這份檔案有 {len(rows)} 張，請分成幾個檔案匯回。")
    if not rows:
        raise ReimportError("檔案裡沒有任何訂單列（A 欄系統編號都是空的）。")
    return record, [column.key for _index, column in columns], rows, skipped


# ---------------------------------------------------------------- 比對

def _order_id(raw):
    try:
        value = Decimal(raw)
    except InvalidOperation:
        return None
    return int(value) if value == value.to_integral_value() and value > 0 else None


def _policy(user):
    from sales.access.services import AccessPolicy
    return AccessPolicy(user)


def section_allowed(policy, user, section, order):
    """與訂單頁同一套權限：路由授權，加上中介層對訂車與配件、營運資料寫入要求的訂單內部財務修改權限。"""
    from sales.services.order_intake import can_edit_finance

    route = SECTION_ROUTES[section]
    if not policy.route(route, "POST", {"pk": order.pk}):
        return False
    return route not in FINANCE_GUARDED_ROUTES or can_edit_finance(user)


def build_plan(batch, user, decisions=None):
    """逐列比對；回傳 {"rows": [...], "blocking": [...], "summary": {...}, "fingerprint": str}。

    每一列：row、id、order（SalesOrder 或 None）、errors（整列錯誤）、fields（要寫入的候選欄位）、
    ignored（只列出、不寫入）、sections、needs_correction（已交車且改到訂車與配件，需勾完成後修正）。
    `decisions` 有傳時，依勾選再用訂單頁同一份表單驗證，驗證錯誤加進該列。
    """
    from sales.services.order_intake import scoped_orders

    record = batch.export_record
    blocking = []
    if record is None or is_expired(record):
        blocking.append(f"對應的匯出紀錄已超過 {cols.BASELINE_DAYS} 天或已刪除，比對用的原值不在了，請重新匯出。")
    baseline = (record.baseline if record else {}) or {}
    policy = _policy(user)
    ids = [_order_id(row["id"]) for row in batch.rows]
    seen = {}
    for number, order_id in zip((row["row"] for row in batch.rows), ids):
        if order_id:
            seen.setdefault(order_id, []).append(number)
    orders = scoped_orders(user).select_related("operations", "vehicle_model", "color", "allocated_vehicle",
                                                "source", "commission_recipient").in_bulk([i for i in ids if i])
    plan_rows = []
    for row, order_id in zip(batch.rows, ids):
        item = {"row": row["row"], "id": row["id"], "order": None, "errors": [], "fields": [], "ignored": [],
                "sections": [], "needs_correction": False}
        plan_rows.append(item)
        order = orders.get(order_id) if order_id else None
        if not order_id:
            item["errors"].append("A 欄系統編號不是有效的數字，請不要修改這一欄。")
            continue
        if len(seen.get(order_id, [])) > 1:
            item["errors"].append("同一張訂單在檔案裡出現多次（第 " + "、".join(map(str, seen[order_id])) + " 列），請只留一列。")
            continue
        if order is None:
            item["errors"].append("找不到這張訂單（可能已刪除，或你沒有權限查看）。")
            continue
        item["order"] = order
        if str(order_id) not in baseline:
            item["errors"].append("這張訂單不在這份匯出裡，請不要從別的檔案貼上整列。")
            continue
        base_values = baseline[str(order_id)].get("values", {})
        for key, text in row["values"].items():
            column = cols.COLUMN_BY_KEY[key]
            current = _current(order, column)
            label = column.label
            if key in row["errors"]:
                if key in FIELD_SECTION:
                    item["errors"].append(f"「{label}」{row['errors'][key]}")
                continue
            if column.order_page_only:
                if text != current:
                    item["ignored"].append({"label": label, "reason": IGNORED_ORDER_PAGE})
                continue
            if not column.editable:
                if text != current:
                    item["ignored"].append({"label": label, "reason": IGNORED_READONLY})
                continue
            base = base_values.get(key)
            if key not in FIELD_SECTION:
                if base is not None and text != base:
                    item["ignored"].append({"label": label, "reason": IGNORED_NEXT_VERSION})
                continue
            if text == current or (base is not None and text == base):
                continue  # 沒改，或系統已經是這個值
            clear = text == ""
            if clear and key in NOT_CLEARABLE:
                item["errors"].append(f"「{label}」不能清空；要改請填新的值。")
                continue
            item["fields"].append({
                "key": key, "label": label, "section": FIELD_SECTION[key], "current": current, "new": text,
                "base": base, "conflict": base is not None and current != base, "clear": clear,
            })
        sections = [section for section in SECTION_ORDER if any(f["section"] == section for f in item["fields"])]
        item["sections"] = sections
        for section in sections:
            if not section_allowed(policy, user, section, order):
                item["errors"].append(f"你沒有「{SECTION_LABELS[section]}」的操作權限，這一區的欄位不能修改。")
        if CONTENT in sections and not order.can_edit_content:
            item["errors"].append("訂單已取消或在取消流程中，訂單內容已鎖定。")
        if SUBSIDY in sections and not order.can_manage_subsidy:
            item["errors"].append("已取消或例外結案的訂單不能修改汰舊補助資料。")
        if SUBSIDY in sections and any(f["key"] == "old_owner_same_as_owner" for f in item["fields"]) \
                and not order.is_trade_in_subsidy:
            item["errors"].append("這張訂單沒有汰舊，「舊車主同新車主」不能修改。")
        item["needs_correction"] = CONTENT in sections and order.is_delivered
    if decisions is not None:
        for item in plan_rows:
            if item["order"] is not None and not item["errors"] and not _row_decision(decisions, item)["exclude"]:
                item["errors"].extend(validate_row(item, _row_decision(decisions, item), user))
    return {"rows": plan_rows, "blocking": blocking, "summary": summarize(plan_rows, batch.skipped_rows),
            "fingerprint": fingerprint(plan_rows)}


def summarize(plan_rows, skipped_rows):
    """預覽摘要；預覽頁另做的表單驗證錯誤（item["validation"]）也算成有錯誤的列。"""
    def failed(item):
        return bool(item["errors"] or item.get("validation"))
    return {
        "rows": len(plan_rows),
        "changed": sum(1 for item in plan_rows if item["fields"] and not failed(item)),
        "fields": sum(len(item["fields"]) for item in plan_rows if not failed(item)),
        "conflicts": sum(1 for item in plan_rows for f in item["fields"] if f["conflict"]),
        "clears": sum(1 for item in plan_rows for f in item["fields"] if f["clear"]),
        "errors": sum(1 for item in plan_rows if failed(item)),
        "ignored": sum(len(item["ignored"]) for item in plan_rows),
        "unchanged": sum(1 for item in plan_rows if not item["fields"] and not failed(item)),
        "skipped": len(skipped_rows),
    }


def fingerprint(plan_rows):
    """預覽的比對結果指紋（不含使用者勾選）；確認時重新比對，不同就整批不寫。"""
    payload = [[item["row"], item["id"], sorted(item["errors"]),
                [[f["key"], f["current"], f["new"], f["conflict"], f["clear"]] for f in item["fields"]]]
               for item in plan_rows]
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- 勾選

def read_decisions(post):
    """從確認表單讀勾選：exclude-<列>、correction-<列>、take-<列>-<欄位代碼>（衝突以檔案為準／確認清除）。"""
    decisions = {}
    for name in post:
        parts = name.split("-", 2)
        if len(parts) < 2 or parts[0] not in {"exclude", "correction", "take"} or not parts[1].isdigit():
            continue
        row = decisions.setdefault(parts[1], {"exclude": False, "correction": False, "take": []})
        if parts[0] == "take" and len(parts) == 3:
            row["take"].append(parts[2])
        elif parts[0] != "take":
            row[parts[0]] = True
    return decisions


def _row_decision(decisions, item):
    return decisions.get(str(item["row"]), {"exclude": False, "correction": False, "take": []})


def included_fields(item, decision):
    """要寫入的欄位：一般修改照寫；衝突或清空要勾「以檔案為準／確認清除」才寫。"""
    return [f for f in item["fields"] if not (f["conflict"] or f["clear"]) or f["key"] in decision["take"]]


def default_decisions(plan):
    """預覽頁的預設勾選（用來先驗證一次）：衝突與清空不勾，已交車視為已勾完成後修正。"""
    return {str(item["row"]): {"exclude": False, "correction": True, "take": []} for item in plan["rows"]}


# ---------------------------------------------------------------- 表單（與訂單頁同一份）

def _payload(form):
    """跟訂單頁送出的內容一樣：由表單現值組出整張表單（不含檔案與停用欄位）。"""
    from django import forms as django_forms

    data = QueryDict(mutable=True)
    for bound in form:
        if isinstance(bound.field, django_forms.FileField) or bound.field.disabled:
            continue
        value = bound.value()
        if isinstance(bound.field, django_forms.BooleanField):
            if value:
                data[bound.html_name] = "on"
        elif isinstance(value, (list, tuple)):
            data.setlist(bound.html_name, [str(item) for item in value])
        else:
            data[bound.html_name] = "" if value is None else str(value)
    return data


def _formset_payload(formset):
    data = _payload(formset.management_form)
    for form in formset:
        data.update(_payload(form))
    return data


def _form_value(field):
    """檔案值換成表單要的值：下拉選項的中文換回代碼。"""
    column = cols.COLUMN_BY_KEY[field["key"]]
    if column.choices and column.kind != cols.BOOL:
        model_field = SalesOrder._meta.get_field(field["key"])
        return {label: value for value, label in model_field.choices}.get(field["new"], field["new"])
    return field["new"]


def _content_forms(order, fields, decision, user, data=None):
    from sales.forms import OrderEditForm, OrderPageAccessoryFormSet, OrderPageOtherFeeFormSet

    purchase_only = not _policy(user).screen("order_gift", "operate")
    if data is None:
        data = _payload(OrderEditForm(instance=order))
        data.update(_formset_payload(OrderPageAccessoryFormSet(
            instance=order, form_kwargs={"allow_manual": True, "purchase_only": purchase_only})))
        data.update(_formset_payload(OrderPageOtherFeeFormSet(instance=order, prefix="other_fees")))
        data["_order_revision"] = str(order.revision)
        data["_workspace"] = "1"
        for field in fields:
            data[field["key"]] = _form_value(field)
        if decision["correction"]:
            data["confirm_completed_correction"] = "on"
    form = OrderEditForm(data, {}, instance=order)
    # 與訂單頁自動儲存相同：這兩個欄位不在自動儲存的表單裡。
    for name in ("is_trade_in_subsidy", "old_owner_different"):
        form.fields.pop(name, None)
    formset = OrderPageAccessoryFormSet(data, instance=order, form_kwargs={"allow_manual": True, "purchase_only": purchase_only})
    fee_formset = OrderPageOtherFeeFormSet(data, instance=order, prefix="other_fees")
    return data, form, formset, fee_formset


def _subsidy_form(order, fields):
    from sales.forms import SubsidyDataForm

    data = _payload(SubsidyDataForm(instance=order))
    data["_order_revision"] = str(order.revision)
    for field in fields:
        if field["key"] == "old_owner_same_as_owner":
            # 畫面是反向勾選「新舊車主不同人」（forms.old_owner_different_field）。
            data.pop("old_owner_different", None)
            if field["new"] == "否":
                data["old_owner_different"] = "on"
        else:
            data[field["key"]] = field["new"]
    return SubsidyDataForm(data, instance=order)


def _operations_form(order, section, fields, profile=None):
    from sales.forms import OrderOperationsForm

    profile = profile or OrderOperationsProfile.objects.get(order=order)
    data = _payload(OrderOperationsForm(instance=profile, prefix="operations", section=section))
    data["_section"] = section
    for field in fields:
        data[f"operations-{field['key']}"] = field["new"]
    return profile, OrderOperationsForm(data, instance=profile, prefix="operations", section=section)


def _form_errors(form, label):
    messages = []
    for name, errors in form.errors.items():
        field = form.fields.get(name)
        prefix = f"「{field.label}」" if field is not None and name != "__all__" else ""
        messages.extend(f"{label}：{prefix}{error}" for error in errors)
    return messages


def validate_row(item, decision, user):
    """依勾選用訂單頁同一份表單驗證（不存檔），回傳錯誤訊息。"""
    fields = included_fields(item, decision)
    errors = []
    if item["needs_correction"] and not decision["correction"] and any(f["section"] == CONTENT for f in fields):
        errors.append("已交車的訂單改「訂車與配件」要勾「完成後修正」，或不匯入這一列。")
    for section in SECTION_ORDER:
        section_fields = [f for f in fields if f["section"] == section]
        if not section_fields:
            continue
        order = SalesOrder.objects.get(pk=item["order"].pk)  # 新的 instance：驗證會改動 instance
        if section == CONTENT:
            _data, form, formset, fee_formset = _content_forms(order, section_fields, decision, user)
            for current in (form, formset, fee_formset):
                if not current.is_valid():
                    if current is form:
                        errors.extend(_form_errors(form, SECTION_LABELS[section]))
                    else:
                        errors.append(f"{SECTION_LABELS[section]}：配件或其他費用明細有誤，請到訂單頁確認。")
        elif section == SUBSIDY:
            form = _subsidy_form(order, section_fields)
            if not form.is_valid():
                errors.extend(_form_errors(form, SECTION_LABELS[section]))
        else:
            _profile, form = _operations_form(order, section, section_fields)
            if not form.is_valid():
                errors.extend(_form_errors(form, SECTION_LABELS[section]))
    return errors


# ---------------------------------------------------------------- 寫入

def apply_plan(batch, user, submitted_fingerprint, decisions):
    """整批寫入：重新比對，指紋不同丟 PlanChanged；任何一列驗證或存檔失敗丟 ApplyFailed，整批退回。"""
    from sales.forms import SubsidyItemFormSet
    from sales.services import order_save

    actor = user.get_full_name() or user.get_username()
    with transaction.atomic():
        plan = build_plan(batch, user)
        if plan["blocking"]:
            raise ApplyFailed(plan["blocking"])
        if plan["fingerprint"] != submitted_fingerprint:
            raise PlanChanged("預覽之後訂單資料有變動，請重新看過預覽再確認。")
        pending = [item for item in plan["rows"] if not _row_decision(decisions, item)["exclude"]]
        unresolved = [item for item in pending if item["errors"]]
        if unresolved:
            raise ApplyFailed([f"第 {item['row']} 列有錯誤，請修正檔案重新上傳，或勾「不匯入這列」。" for item in unresolved])
        # 依訂單編號順序鎖列，避免與畫面自動儲存互相等待。
        locked = {order.pk: order for order in SalesOrder.objects.select_for_update(of=("self",))
                  .filter(pk__in=[item["order"].pk for item in pending]).order_by("pk")}
        written = []
        for item in pending:
            decision = _row_decision(decisions, item)
            fields = included_fields(item, decision)
            if not fields:
                continue
            if item["needs_correction"] and not decision["correction"] and any(f["section"] == CONTENT for f in fields):
                raise ApplyFailed([f"第 {item['row']} 列：已交車的訂單改「訂車與配件」要勾「完成後修正」，或不匯入這一列。"])
            reason = f"批次修改（{batch.file_name} 第 {item['row']} 列）"
            for section in SECTION_ORDER:
                section_fields = [f for f in fields if f["section"] == section]
                if not section_fields:
                    continue
                order = SalesOrder.objects.get(pk=locked[item["order"].pk].pk)
                if section == CONTENT:
                    baseline = order_save.content_baseline(order)
                    data, form, formset, fee_formset = _content_forms(order, section_fields, decision, user)
                    if not (form.is_valid() and formset.is_valid() and fee_formset.is_valid()):
                        raise ApplyFailed([f"第 {item['row']} 列：" + "；".join(_form_errors(form, SECTION_LABELS[section]))])
                    order_save.save_order_content(order, form, formset, fee_formset, baseline, user=user,
                                                  posted=data, reason=reason)
                elif section == SUBSIDY:
                    baseline = order_save.subsidy_baseline(order)
                    form = _subsidy_form(order, section_fields)
                    if not form.is_valid():
                        raise ApplyFailed([f"第 {item['row']} 列：" + "；".join(_form_errors(form, SECTION_LABELS[section]))])
                    order_save.save_subsidy_data(order, form, SubsidyItemFormSet(None, instance=order, prefix="subsidy_items"),
                                                 baseline, items_submitted=False, user=user, reason=reason)
                else:
                    profile = OrderOperationsProfile.objects.get(order=order)
                    baseline = order_save.operations_baseline(order, profile)
                    profile, form = _operations_form(order, section, section_fields, profile)
                    if not form.is_valid():
                        raise ApplyFailed([f"第 {item['row']} 列：" + "；".join(_form_errors(form, SECTION_LABELS[section]))])
                    order_save.save_operations(order, profile, form, None, baseline, user=user, reason=reason)
            labels = "、".join(f["label"] for f in fields)
            OrderEvent.objects.create(order_id=item["order"].pk, event_type=EVENT, actor_name=actor,
                                      description=f"{reason}：{labels}")
            written.append({"row": item["row"], "order": item["order"].pk, "number": item["order"].number,
                            "fields": [[f["label"], f["current"], f["new"]] for f in fields]})
        from django.utils import timezone
        batch.status = batch.Status.APPLIED
        batch.decisions = decisions
        batch.result = {"orders": len(written), "fields": sum(len(row["fields"]) for row in written), "rows": written}
        batch.applied_at = timezone.now()
        batch.last_error = ""
        batch.save(update_fields=["status", "decisions", "result", "applied_at", "last_error", "updated_at"])
    return batch.result
