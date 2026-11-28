"""T-308 B：庫存列表的「實際位置」直接下拉改，選了就存（使用者 2026-11-24 選 B）。

只改車放在哪裡（current_dealer／location_store），不改狀態、去向，也不產生調車簽收。
每次改動記一筆「調度車輛」歷程，原因寫「改位置」；已在目標位置就略過、不記。
權限同編輯庫存：車輛庫存與歷程的「操作」（sales/access/registry.py）。
不能改到已停用的車行；唯一例外是按「復原」放回這台車剛才的位置（見 _undo_dealer）。
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods

from sales.forms import VehicleInventoryForm
from sales.models import SalesSource, VehicleInventory, VehicleInventoryHistory
from sales.services.inventory_location import (
    current_location_option_label, current_location_value, home_location_map, resolve_location,
)
from sales.views import INVENTORY_HISTORY_FIELDS, _create_inventory_history, _editing_name

REASON = "改位置"
UNDO_REASON = "改位置（復原）"
UNDO_SALT = "inventory-location-undo"
UNDO_MAX_AGE = 30 * 60  # 復原按鈕只在剛改完時出現，憑證半小時內有效


def _undo_token(vehicle, before):
    """改位置成功時簽發：記下這台車改之前與改之後的位置，按「復原」時帶回來。"""
    return signing.dumps(
        {"car": vehicle.pk, "from": list(before), "to": [vehicle.current_dealer_id, vehicle.location_store_id]},
        salt=UNDO_SALT,
    )


def _undo_dealer(request, vehicle):
    """復原到這台車剛才的位置時，剛才的車行就算已停用也允許，回傳那個車行；其他情況回傳 None。

    只認這次改位置簽發的憑證，而且車在那之後沒被改過、要放回的正是剛才的車行。
    """
    if request.POST.get("undo") != "1":
        return None
    try:
        data = signing.loads(request.POST.get("undo_token", ""), salt=UNDO_SALT, max_age=UNDO_MAX_AGE)
    except signing.BadSignature:
        return None
    if not isinstance(data, dict) or data.get("car") != vehicle.pk:
        return None
    if data.get("to") != [vehicle.current_dealer_id, vehicle.location_store_id]:
        return None
    dealer_id = (data.get("from") or [None])[0]
    if not dealer_id or str(dealer_id) != str(request.POST.get("location", "")):
        return None
    return SalesSource.objects.filter(pk=dealer_id, source_type=SalesSource.SourceType.DEALER).first()


def _reply(request, status, payload):
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse(payload, status=status)
    (messages.success if payload.get("ok") else messages.error)(request, payload["message"])
    next_url = request.POST.get("next", "")
    if not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        next_url = reverse("inventory_list")
    return redirect(next_url)


@login_required
@require_http_methods(["POST"])
def inventory_location(request, pk):
    with transaction.atomic():
        # 車行可為空（LEFT JOIN），PostgreSQL 不允許鎖外部連接的一側，只鎖車輛本身。
        vehicle = get_object_or_404(
            VehicleInventory.objects.select_for_update(of=("self",)).select_related("location_store", "current_dealer"),
            pk=pk,
        )
        home_locations = home_location_map()
        before_value = current_location_value(vehicle, home_locations)
        before_option = current_location_option_label(vehicle, home_locations)
        before_label = vehicle.actual_location_label
        current = {"value": before_value, "label": before_option}
        if vehicle.status in VehicleInventoryForm.FINAL_STATUSES:
            return _reply(request, 409, {
                "ok": False, **current,
                "message": f"{vehicle.identifier} 目前是「{vehicle.get_status_display()}」，不能改位置。",
            })
        expected = request.POST.get("expected")
        if expected is not None and expected != before_value:
            return _reply(request, 409, {
                "ok": False, **current,
                "message": f"{vehicle.identifier} 的位置剛被別人改成「{before_option}」，請確認後再選一次。",
            })
        before_ids = (vehicle.current_dealer_id, vehicle.location_store_id)
        target = resolve_location(vehicle, request.POST.get("location"), home_locations)
        if target is None:
            undo_dealer = _undo_dealer(request, vehicle)
            if undo_dealer is not None:
                target = (undo_dealer, vehicle.location_store)
        if target is None:
            return _reply(request, 400, {"ok": False, **current, "message": "找不到這個位置，請重新整理後再選。"})
        dealer, store = target
        if (vehicle.current_dealer_id, vehicle.location_store_id) == (
            dealer.pk if dealer else None, store.pk if store else None
        ):
            return _reply(request, 200, {
                "ok": True, "changed": False, **current,
                "message": f"{vehicle.identifier} 本來就放在 {before_option}。",
            })
        vehicle.current_dealer = dealer
        vehicle.location_store = store
        vehicle.save(update_fields=["current_dealer", "location_store", "updated_at"])
        after_label = vehicle.actual_location_label
        _create_inventory_history(
            vehicle,
            actor_name=_editing_name(request.user),
            event_type=VehicleInventoryHistory.EventType.TRANSFERRED,
            reason=UNDO_REASON if request.POST.get("undo") == "1" else REASON,
            changes={"current_dealer": {
                "label": INVENTORY_HISTORY_FIELDS["current_dealer"], "before": before_label, "after": after_label,
            }},
            from_location_label=before_label,
            to_location_label=after_label,
        )
    after_option = current_location_option_label(vehicle, home_locations)
    return _reply(request, 200, {
        "ok": True, "changed": True,
        "value": current_location_value(vehicle, home_locations), "label": after_option,
        "previous_value": before_value, "previous_label": before_option,
        "undo_token": _undo_token(vehicle, before_ids),
        "message": f"{vehicle.identifier} 已改放到 {after_option}",
    })
