"""車行傭金／獎金給付（T-150 方案 A；T-259 從報表中心移到資料維護區「車行傭金與獎勵」的〈給付〉頁籤）。

GET 只讀；勾選、取消、備註、確認差額走 POST，寫歷程後導回原篩選，由 inplace-regions.js 原地換入。
權限由 `sales.access` 中介層依 `dealer_payouts` 畫面把關（查看／操作／匯出）。
"""
import csv
from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from . import payouts
from .payout_models import DealerPayoutEntry
from .views import csv_safe


def _require(request, action):
    """中介層對舊制未設定帳號一律放行；給付追蹤要明確授權，這裡再檢查一次。"""
    from sales.access.services import policy_for

    if not policy_for(request).screen("dealer_payouts", action):
        raise PermissionDenied("沒有車行傭金／獎金給付的權限。")


def legacy_redirect(name):
    """T-259：報表中心的舊網址導到資料維護區的新頁籤，篩選與匯出條件照帶（權限由中介層照 dealer_payouts 檢查）。"""
    from django.urls import reverse

    @login_required
    @require_GET
    def view(request):
        _require(request, "export" if name == "dealer_payout_export" else "view")
        query = request.GET.urlencode()
        return redirect(f"{reverse(name)}?{query}" if query else reverse(name))
    return view


def _actor(user):
    return user.get_full_name() or user.get_username()


def _date(value):
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def _filters(params):
    dealer = params.get("dealer", "")
    selected = {
        "dealer": dealer if dealer.isdigit() else "",
        "start": params.get("start", ""),
        "end": params.get("end", ""),
        "status": params.get("status", "") if params.get("status", "") in payouts.STATUS_LABELS else "",
        "kind": params.get("kind", "") if params.get("kind", "") in payouts.KIND_LABELS else "",
        "method": params.get("method", "") if params.get("method", "") in payouts.METHOD_LABELS else "",
        "estimate": params.get("estimate") == "1",
    }
    start, end = _date(selected["start"]), _date(selected["end"])
    selected["start"] = start.isoformat() if start else ""
    selected["end"] = end.isoformat() if end else ""
    criteria = {
        "dealer_id": int(selected["dealer"]) if selected["dealer"] else None,
        "start": start, "end": end,
        "status": selected["status"], "kind": selected["kind"], "method": selected["method"],
    }
    return selected, criteria


def _context(request):
    selected, criteria = _filters(request.GET)
    every = payouts.collect_items(include_estimate=selected["estimate"])
    items = payouts.filter_items(every, **criteria)
    dealers = sorted({item.dealer.pk: item.dealer for item in every}.values(), key=lambda dealer: dealer.name)
    return selected, items, every, dealers


@login_required
@never_cache
@require_GET
def dealer_payout_list(request):
    from sales.access.services import policy_for

    _require(request, "view")
    selected, items, every, dealers = _context(request)
    policy = policy_for(request)
    active = any(selected[key] for key in ("dealer", "start", "end", "status", "kind", "method")) or selected["estimate"]
    totals = payouts.totals(items)
    orphans = [entry for entry in payouts.orphan_entries(every)
               if not selected["dealer"] or str(entry.dealer_id) == selected["dealer"]]
    return render(request, "sales/reporting/dealer_payouts.html", {
        "selected": selected,
        "groups": payouts.summarize(items),
        "totals": totals,
        "orphans": orphans,
        "attention_count": totals["changed_count"] + totals["settle_changed_count"] + len(orphans),
        "can_open_orders": policy.route("order_list"),
        "dealers": dealers,
        "status_labels": payouts.STATUS_LABELS,
        "kind_labels": payouts.KIND_LABELS,
        "method_labels": payouts.METHOD_LABELS,
        "start_date": payouts.PAYOUT_START_DATE,
        "filters_active": active,
        "can_operate": policy.screen("dealer_payouts", "operate"),
        "can_export": policy.screen("dealer_payouts", "export"),
        "queried_at": timezone.now(),
        "next_url": request.get_full_path(),
        "payout_update_url": reverse("dealer_payout_update"),
    })


def _back(request):
    next_url = request.POST.get("next", "")
    if url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return redirect(next_url)
    return redirect("dealer_payout_list")


def _settlement_action(request, action, actor):
    """台數獎金結算／取消結算（T-203，使用者 2026-11-17 選 C）：規則×期間×車行一組。"""
    from sales.services.audit_note import money
    from sales.services.volume_bonus import cancel_settlement, settle_group

    scope = [request.POST.get(name, "") for name in ("rule", "period", "dealer")]
    if not all(value.isdigit() for value in scope):
        raise ValidationError("找不到要結算的台數獎金，請重新整理。")
    rule_id, period_id, dealer_id = (int(value) for value in scope)
    if action == "settle":
        total = request.POST.get("total", "")
        settlement = settle_group(rule_id, period_id, dealer_id, actor,
                                  expected_total=int(total) if total.isdigit() else None)
        messages.success(request, f"已結算 {settlement.dealer.name}「{settlement.rule}」{settlement.period.label}："
                                  f"{settlement.quantity} 台、{money(settlement.total_amount)}，已加進各單傭金支出，待發放給車行。")
    else:
        settlement = cancel_settlement(rule_id, period_id, dealer_id, actor)
        messages.success(request, f"已取消 {settlement.dealer.name}「{settlement.rule}」{settlement.period.label} 的結算，"
                                  "獎金已從各單傭金支出移除、回到試算。")


@login_required
@require_POST
def dealer_payout_update(request):
    _require(request, "operate")
    action = request.POST.get("action", "")
    keys = [key for key in request.POST.getlist("key") if key]
    actor = _actor(request.user)
    try:
        if action in {"paid", "unpaid"}:
            count = payouts.set_paid(keys, action == "paid", actor)
            if action == "paid":
                messages.success(request, f"已登記 {count} 筆已給付。" if count else "勾選的項目都已經是已給付。")
            else:
                messages.success(request, f"已取消 {count} 筆的已給付，歷程已保留。" if count else "勾選的項目原本就是未給付。")
        elif action == "note" and len(keys) == 1:
            changed = payouts.save_note(keys[0], request.POST.get("note", ""), actor)
            messages.success(request, "備註已儲存。" if changed else "備註沒有變動。")
        elif action == "confirm" and len(keys) == 1:
            payouts.confirm_difference(keys[0], actor)
            messages.success(request, "已確認差額，改以目前金額記為已給付。")
        elif action in {"settle", "cancel_settlement"}:
            _settlement_action(request, action, actor)
        elif action == "resolve" and request.POST.get("entry", "").isdigit():
            outcome = request.POST.get("outcome", "")
            payouts.resolve_orphan(int(request.POST["entry"]), actor, outcome)
            label = payouts.RESOLVE_OUTCOMES.get(outcome)
            messages.success(request, f"已記為「{label}」並結案。" if label else "已確認處理，這筆不再列在「來源已不存在」。")
        else:
            messages.error(request, "無法辨識要執行的動作，請重新整理後再試。")
    except ValidationError as exc:
        messages.error(request, "；".join(exc.messages))
    return _back(request)


@login_required
@never_cache
@require_GET
def dealer_payout_export(request):
    _require(request, "export")
    selected, items, _every, _dealers = _context(request)
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="dealer-payouts-{timezone.localdate():%Y%m%d}.csv"'
    response.write("﻿")
    writer = csv.writer(response)
    writer.writerow(["車行", "項目類型", "訂單編號", "車主", "領牌日／期間", "項目", "金額", "數量", "單位",
                     "給付方式", "狀態", "給付時金額", "給付時數量", "給付時間", "給付登記人", "備註"])
    for group in payouts.summarize(items):
        rows = [item for row in group["orders"] for item in row["items"]] + group["bonuses"]
        for item in rows:
            entry = item.entry or DealerPayoutEntry()
            writer.writerow([csv_safe(value) for value in (
                item.dealer.name, item.kind_label,
                item.order.number if item.order else "", item.order.owner_name if item.order else "",
                item.period_label or (item.day.isoformat() if item.day else ""),
                item.label, "" if item.is_quantity else item.amount,
                payouts._quantity_text(item.quantity), item.unit, item.method_label, item.status_label,
                "" if entry.paid_amount is None else entry.paid_amount, payouts._quantity_text(entry.paid_quantity),
                timezone.localtime(entry.paid_at).strftime("%Y-%m-%d %H:%M") if entry.paid_at else "",
                entry.paid_by, entry.note,
            )])
    return response
