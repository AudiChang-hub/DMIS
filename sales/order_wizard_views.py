"""建立訂單精靈的頁面流程：每一步存進草稿、由伺服器檢查並決定能否前往下一步。"""
from datetime import date
from decimal import Decimal

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import models
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.datastructures import MultiValueDict

from sales.models import OrderEvent
from sales.services import order_wizard as wizard


def _step_url(reception, draft, step):
    base = reverse("order_start" if reception else "order_create")
    return f"{base}?draft={draft.pk}&step={step}" if draft else base


def _validate_draft(request, draft, reception):
    from sales.views import _bound_intake_forms
    data = wizard.draft_query_dict(draft.data)
    form, formset, fee_formset = _bound_intake_forms(request, data, MultiValueDict(), draft, reception)
    form.is_valid()
    formset.is_valid()
    fee_formset.is_valid()
    from sales.services.order_discount import validate_intake_discount
    validate_intake_discount(form, formset, fee_formset)
    identity_error = wizard.identity_check_error(draft.data)
    grouped = wizard.collect_step_errors(
        form, {"accessories": formset, "other_fees": fee_formset}, {"owner": [identity_error]} if identity_error else None
    )
    return form, formset, fee_formset, grouped


def _render_step(request, draft, reception, step, forms, *, errors=(), submission_key=None, summary=None):
    from sales.views import _intake_form_context
    form, formset, fee_formset = forms
    previous, following = wizard.step_neighbors(step)
    context = _intake_form_context(request, form, formset, fee_formset, draft, reception, submission_key)
    data = draft.data if draft else {}
    context["wizard"] = {
        "current": step,
        "label": wizard.STEP_LABELS[step],
        "number": wizard.step_index(step) + 1,
        "total": len(wizard.STEP_KEYS),
        "steps": wizard.step_list(draft, step),
        "previous": previous,
        "next": following,
        "errors": [f"{label}：{message}" if label else message for label, message in errors],
        "summary": summary,
        "id_check": data.get(wizard.ID_CHECK_KEY, ""),
        "id_check_error": data.get(wizard.ID_CHECK_ERROR_KEY, ""),
        "id_manual_confirmed": data.get(wizard.ID_MANUAL_KEY) in {"on", "1", "true", True},
        "deposit_auto": "1" if data.get("_deposit_auto") == "1" else "",
    }
    return render(request, "sales/order_form.html", context)


def wizard_get(request, draft, reception):
    from sales.views import _initial_intake_forms
    requested = request.GET.get("step")
    step = wizard.allowed_step(draft, requested)
    if draft and requested and requested != step:
        messages.info(request, f"請先完成「{wizard.STEP_LABELS[wizard.first_open_step(draft)]}」再往下。")
        return redirect(_step_url(reception, draft, step))
    summary = None
    if step == "confirm":
        form, formset, fee_formset, grouped = _validate_draft(request, draft, reception)
        bad = wizard.first_error_step(grouped)
        if bad:
            messages.error(request, f"「{wizard.STEP_LABELS[bad]}」有資料需要修正，請修正後再送出。")
            wizard.prune_later_errors(form, {"accessories": formset, "other_fees": fee_formset}, bad)
            return _render_step(request, draft, reception, bad, (form, formset, fee_formset), errors=grouped[bad])
        summary = build_summary(form, formset, fee_formset, draft)
    forms = _initial_intake_forms(request, draft, reception)
    if forms is None:
        return redirect("catalog")
    return _render_step(request, draft, reception, step, forms, summary=summary)


def wizard_post(request, draft, reception, action, submission_key):
    from sales.intake_forms import validated_intake_uploads
    from sales.views import _bound_intake_forms, _create_intake_order, _new_order_draft, _store_order_draft
    step = request.POST.get("_wizard_step")
    if step not in wizard.STEP_KEYS:
        step = "vehicle"
    is_new = draft is None
    target = draft or _new_order_draft(request)
    try:
        uploads = validated_intake_uploads(request.FILES)
        reception = _store_order_draft(request, target, reception, uploads, is_new=is_new)
    except ValidationError as exc:
        forms = _bound_intake_forms(request, request.POST, request.FILES, None if is_new else draft, reception)
        forms[0].is_valid()
        wizard.prune_later_errors(forms[0], {"accessories": forms[1], "other_fees": forms[2]}, step)
        return _render_step(request, None if is_new else draft, reception, step, forms,
                            errors=[("", message) for message in exc.messages], submission_key=submission_key)
    draft = target
    previous, following = wizard.step_neighbors(step)
    if action == "back":
        return redirect(_step_url(reception, draft, previous or step))
    if action == "goto":
        return redirect(_step_url(reception, draft, wizard.allowed_step(draft, request.POST.get("_wizard_goto"))))

    form, formset, fee_formset, grouped = _validate_draft(request, draft, reception)
    formsets = {"accessories": formset, "other_fees": fee_formset}
    if action == "next":
        bad = wizard.first_error_step(grouped, upto=step)
        if bad:
            wizard.prune_later_errors(form, formsets, bad)
            return _render_step(request, draft, reception, bad, (form, formset, fee_formset),
                                errors=grouped[bad], submission_key=submission_key)
        wizard.mark_done(draft, step)
        draft.save(update_fields=["data", "updated_at"])
        return redirect(_step_url(reception, draft, following or step))

    # 送出：前面每一步都要完成，且整張再驗證一次。
    first_open = wizard.first_open_step(draft)
    if first_open != "confirm":
        messages.error(request, f"請先完成「{wizard.STEP_LABELS[first_open]}」。")
        return redirect(_step_url(reception, draft, first_open))
    bad = wizard.first_error_step(grouped)
    if bad:
        wizard.prune_later_errors(form, formsets, bad)
        return _render_step(request, draft, reception, bad, (form, formset, fee_formset),
                            errors=grouped[bad], submission_key=submission_key)
    snapshot = dict(draft.data)
    response, form, formset, fee_formset = _create_intake_order(
        request, wizard.draft_query_dict(draft.data), MultiValueDict(), draft, reception, submission_key
    )
    if response is None:
        grouped = wizard.collect_step_errors(form, formsets)
        bad = wizard.first_error_step(grouped) or "confirm"
        wizard.prune_later_errors(form, formsets, bad)
        return _render_step(request, draft, reception, bad, (form, formset, fee_formset),
                            errors=grouped[bad], submission_key=submission_key)
    _record_identity_override(request, submission_key, snapshot)
    return response


def _record_identity_override(request, submission_key, data):
    if data.get("owner_type") not in {"local", "foreign"} or data.get(wizard.ID_CHECK_KEY) == "passed":
        return
    from sales.models import SalesOrder
    order = SalesOrder.objects.filter(submission_key=submission_key).first()
    if not order:
        return
    reason = (data.get(wizard.ID_CHECK_ERROR_KEY) or "未完成自動辨識").strip()
    OrderEvent.objects.create(
        order=order,
        event_type="identity_manual_check",
        description=f"證件自動辨識未通過（{reason}），由建立人員人工核對證件正反面後送出。",
        actor_name=request.user.get_username(),
    )


def _display(form, name):
    if name not in form.fields:
        return ""
    value = form.cleaned_data.get(name)
    if value in (None, "", [], False):
        return ""
    field = form.fields[name]
    choices = getattr(field, "choices", None)
    if choices and not isinstance(value, models.Model):
        labels = {str(key): label for key, label in choices}
        if str(value) in labels:
            return str(labels[str(value)])
    if value is True:
        return "是"
    if isinstance(value, Decimal):
        return f"{value:,.0f} 元"
    if isinstance(value, date):
        return value.strftime("%Y/%m/%d")
    return str(value)


def _rows(form, names):
    rows = []
    for name in names:
        text = _display(form, name)
        if text:
            rows.append((form.fields[name].label, text))
    return rows


def _discount_rows(form, formset, fee_formset):
    from sales.services.order_discount import intake_discount_preview
    preview = intake_discount_preview(form, formset, fee_formset)
    if not preview:
        return []  # 沒有優惠就不列，確認頁會給客人看
    rate = f"（{preview['rate'].normalize():f} 折）" if preview["mode"] == "rate" else ""
    return [
        ("優惠前總價", f"{preview['before']:,.0f} 元"),
        ("總價優惠", f"−{preview['amount']:,.0f} 元{rate}，送出即生效"),
        ("優惠後總價", f"{preview['after']:,.0f} 元"),
        (form.fields["intake_discount_reason"].label, form.cleaned_data.get("intake_discount_reason", "")),
    ]


def build_summary(form, formset, fee_formset, draft):
    accessories = []
    for row in formset.forms:
        data = getattr(row, "cleaned_data", None) or {}
        if data.get("DELETE") or not (data.get("accessory_product") or data.get("custom_name")):
            continue
        name = data.get("custom_name") or str(data.get("accessory_product"))
        quantity = data.get("quantity") or 1
        amount = (data.get("amount") or Decimal("0")) + (data.get("labor_fee") or Decimal("0"))
        line_type = dict(row.fields["line_type"].choices).get(data.get("line_type"), "") if "line_type" in row.fields else ""
        accessories.append(f"{name} × {quantity}（{line_type}）{amount * quantity:,.0f} 元" if line_type else f"{name} × {quantity}　{amount * quantity:,.0f} 元")
    fees = []
    for row in fee_formset.forms:
        data = getattr(row, "cleaned_data", None) or {}
        if data.get("DELETE") or not data.get("name"):
            continue
        fees.append(f"{data['name']}　{(data.get('amount') or Decimal('0')):,.0f} 元")
    owner_rows = _rows(form, ("owner_type", "owner_name", "owner_name_en", "owner_id_number", "owner_birth_date",
                              "owner_phone", "owner_email", "owner_address", "owner_nationality", "residence_expiry"))
    if (draft.data or {}).get("owner_type") in {"local", "foreign"}:
        passed = draft.data.get(wizard.ID_CHECK_KEY) == "passed"
        owner_rows.append(("證件檢查", "自動辨識通過，已人工核對" if passed else "自動辨識未通過，已人工核對證件正反面"))
    payment_rows = _rows(form, ("payment_type", "vehicle_price", "vehicle_price_adjustment_reason", "installment_company",
                                "installment_periods", "installment_monthly", "installment_opening_fee"))
    if form.finance_editable:
        payment_rows += _rows(form, ("plate_insurance_fee",))
    deposit = form.cleaned_data.get("deposit_amount") or Decimal("0")
    deposit_rows = [(form.fields["deposit_amount"].label, f"{deposit:,.0f} 元" if deposit else "無")]
    deposit_rows += _rows(form, ("deposit_date", "deposit_method") if deposit else ())
    deposit_rows += _discount_rows(form, formset, fee_formset)
    tradein_rows = _rows(form, ("trade_in_intent",))
    if "subsidy_programs" in form.fields:
        programs = form.cleaned_data.get("subsidy_programs") or []
        from sales.services.subsidy_programs import other_subsidy_names
        names = [str(item) for item in programs] + other_subsidy_names(form.cleaned_data.get("subsidy_other"))
        tradein_rows.append((form.fields["subsidy_programs"].label, "、".join(names) or "無"))
    vehicle_rows = []
    model = form.cleaned_data.get("vehicle_model")
    if model:
        # 摘要只列品牌、車種名稱、型號、年份；車色只列顏色名稱。
        parts = (model.brand, model.name, model.model_number, str(model.model_year) if model.model_year else "")
        vehicle_rows.append((form.fields["vehicle_model"].label, "／".join(part for part in parts if part)))
    color = form.cleaned_data.get("color")
    if color:
        vehicle_rows.append((form.fields["color"].label, color.name))
    return [
        {"step": "vehicle", "label": wizard.STEP_LABELS["vehicle"],
         "rows": vehicle_rows + _rows(form, ("vehicle_category", "transaction_type", "source_type", "source"))},
        {"step": "accessories", "label": wizard.STEP_LABELS["accessories"], "rows": [("配件", "、".join(accessories) or "無")]},
        {"step": "tradein", "label": wizard.STEP_LABELS["tradein"], "rows": tradein_rows},
        {"step": "delivery", "label": wizard.STEP_LABELS["delivery"], "rows": _rows(form, (
            "plate_choice", "plate_selection_fee", "watched_numbers", "plate_preference_note", "delivery_method",
            "delivery_destination", "note"))},
        {"step": "owner", "label": wizard.STEP_LABELS["owner"], "rows": owner_rows},
        {"step": "payment", "label": wizard.STEP_LABELS["payment"], "rows": payment_rows},
        {"step": "deposit", "label": wizard.STEP_LABELS["deposit"],
         "rows": deposit_rows + ([("其他費用", "、".join(fees))] if fees else [])},
    ]
