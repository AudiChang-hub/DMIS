"""原廠車型比對：admin 檢查官網、確認對應、補上空白車色圖片。"""

import logging
import uuid

import django_rq
from django.contrib import messages
from django.db import IntegrityError, transaction
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST, require_safe

from sales.access.views import root_required
from sales.models import (
    OfficialCatalogBrand,
    OfficialCatalogCheck,
    OfficialCatalogModel,
    UserAccountAuditLog,
    VehicleColor,
)
from sales.services import official_catalog as service
from sales.services.price_version import resolve_vehicle_price_version

logger = logging.getLogger(__name__)

TABS = (
    ("pending", "待對應"),
    ("changes", "有變動"),
    ("images", "可補圖"),
    ("linked", "已對應"),
    ("ignored", "已忽略"),
)


def _brand(value):
    return value if value in OfficialCatalogBrand.values else OfficialCatalogBrand.SYM


def _page_url(brand, tab):
    return f"{reverse('official_catalog')}?brand={brand}&tab={tab}"


def _redirect_back(request, link):
    tab = request.POST.get("tab", "")
    return redirect(_page_url(link.brand, tab if tab in dict(TABS) else "pending"))


def _audit(request, description, metadata):
    UserAccountAuditLog.objects.create(
        actor=request.user, target=request.user, target_username=request.user.username,
        action="update", description=description, metadata=metadata,
    )


def _tab_of(link):
    if not link.vehicle_model_id:
        if link.is_ignored:
            return "ignored"
        return None if link.missing else "pending"
    return "linked"


def _price_note(link, today):
    model = link.vehicle_model
    version = resolve_vehicle_price_version(model.pk, today) if model else None
    system_price = version.suggested_price if version else None
    official = link.data.get("price")
    return {
        "official": official,
        "official_note": link.data.get("price_note", ""),
        "system": system_price,
        "system_includes_registration": version.suggested_price_includes_registration if version else None,
        "differs": bool(official and system_price and int(system_price) != int(official)),
    }


@root_required
@require_safe
def official_catalog(request):
    brand = _brand(request.GET.get("brand"))
    tab = request.GET.get("tab") if request.GET.get("tab") in dict(TABS) else "pending"
    today = timezone.localdate()
    links = list(
        OfficialCatalogModel.objects.filter(brand=brand).select_related("vehicle_model").prefetch_related(
            Prefetch("vehicle_model__colors", queryset=VehicleColor.objects.order_by("name", "pk"))
        )
    )
    candidates = list(service.brand_models(brand).filter(active=True))
    linked_ids = {link.vehicle_model_id for link in links if link.vehicle_model_id}
    buckets = {key: [] for key, _ in TABS}
    for link in links:
        fillable = service.fillable_colors(link)
        row = {"link": link, "fillable": fillable}
        base = _tab_of(link)
        if base:
            buckets[base].append(row)
        if link.vehicle_model_id:
            if link.has_changes:
                buckets["changes"].append(row)
            if fillable:
                buckets["images"].append(row)
    rows = buckets[tab]
    for row in rows:
        link = row["link"]
        if link.vehicle_model_id:
            row["price"] = _price_note(link, today)
            row["changes"] = service.describe_changes(link.acknowledged_data, link.data)
        else:
            suggested = service.suggest_vehicle_models(link.data, [m for m in candidates if m.pk not in linked_ids])
            row["suggested"] = suggested[0].pk if suggested else None
    latest = OfficialCatalogCheck.objects.filter(brand=brand).first()
    running = service.active_check(brand)
    brand_status = [
        {"value": value, "label": label,
         "latest": latest if value == brand else OfficialCatalogCheck.objects.filter(brand=value).first(),
         "running": running if value == brand else service.active_check(value)}
        for value, label in OfficialCatalogBrand.choices
    ]
    return render(request, "sales/official_catalog.html", {
        "brand": brand,
        "tab": tab,
        "tabs": [(key, label, len(buckets[key])) for key, label in TABS],
        "rows": rows,
        "candidates": candidates,
        "linked_ids": linked_ids,
        "latest": latest,
        "running": running,
        "brand_status": brand_status,
        "any_running": any(item["running"] for item in brand_status),
        "has_entries": bool(links),
    })


@root_required
@require_POST
def official_catalog_check_start(request):
    """brand=all 時兩家各排一個檢查；已在進行中的那家略過。"""
    requested = request.POST.get("brand")
    brands = list(OfficialCatalogBrand.values) if requested == "all" else [_brand(requested)]
    for brand in brands:
        _start_check(request, brand)
    return_brand = _brand(request.POST.get("return_brand") or brands[0])
    return redirect(_page_url(return_brand, "pending"))


def _start_check(request, brand):
    label = service.SOURCES[brand]["label"]
    with transaction.atomic():
        if service.active_check(brand):
            messages.info(request, f"{label} 官網檢查正在進行中，完成後頁面會顯示結果。")
            return
        OfficialCatalogCheck.objects.filter(brand=brand, status__in=("queued", "running")).update(
            status=OfficialCatalogCheck.Status.FAILED, finished_at=timezone.now(),
            errors=["上次檢查逾時未完成，已停止。"], error_count=1, updated_at=timezone.now(),
        )
        check = OfficialCatalogCheck.objects.create(brand=brand, requested_by=request.user)
    job_id = f"official-catalog-{check.pk}-{uuid.uuid4().hex[:12]}"
    try:
        queue = django_rq.get_queue("imports")
        queue.enqueue(service.run_official_catalog_check, check.pk, job_timeout=1800, job_id=job_id)
    except Exception:
        logger.exception("無法排入原廠官網檢查", extra={"check_id": check.pk})
        OfficialCatalogCheck.objects.filter(pk=check.pk).update(
            status=OfficialCatalogCheck.Status.FAILED, finished_at=timezone.now(),
            errors=["無法啟動背景檢查，請稍後再試。"], error_count=1, updated_at=timezone.now(),
        )
        messages.error(request, f"無法啟動 {label} 背景檢查，請稍後再試。")
    else:
        OfficialCatalogCheck.objects.filter(pk=check.pk).update(job_id=job_id, updated_at=timezone.now())
        messages.success(request, f"已開始檢查 {label} 官網，約需 2～3 分鐘。")


@root_required
@require_POST
def official_catalog_link(request, pk):
    link = get_object_or_404(OfficialCatalogModel, pk=pk)
    raw = request.POST.get("vehicle_model", "")
    if request.POST.get("action") == "unlink":
        with transaction.atomic():
            locked = OfficialCatalogModel.objects.select_for_update().get(pk=pk)
            previous = locked.vehicle_model_id
            locked.vehicle_model, locked.linked_by, locked.linked_at = None, None, None
            locked.acknowledged_data, locked.acknowledged_hash = {}, ""
            locked.save(update_fields=["vehicle_model", "linked_by", "linked_at", "acknowledged_data",
                                       "acknowledged_hash", "updated_at"])
            _audit(request, f"取消原廠車型對應：{locked.name}", {"official_id": pk, "vehicle_model_id": previous})
        messages.success(request, f"已取消「{link.name}」的對應，車型資料未變更。")
        return _redirect_back(request, link)
    model = service.brand_models(link.brand).filter(active=True, pk=int(raw)).first() if raw.isdigit() else None
    if not model:
        messages.error(request, "請選擇同品牌、啟用中的系統車型。")
        return _redirect_back(request, link)
    try:
        with transaction.atomic():
            locked = OfficialCatalogModel.objects.select_for_update().get(pk=pk)
            locked.vehicle_model, locked.linked_by, locked.linked_at = model, request.user, timezone.now()
            locked.acknowledged_data, locked.acknowledged_hash = locked.data, locked.content_hash
            locked.ignored_hash = ""
            locked.save(update_fields=["vehicle_model", "linked_by", "linked_at", "acknowledged_data",
                                       "acknowledged_hash", "ignored_hash", "updated_at"])
            _audit(request, f"確認原廠車型對應：{locked.name} → {model}", {"official_id": pk, "vehicle_model_id": model.pk})
    except IntegrityError:
        messages.error(request, f"「{model}」已對應其他官網車型，請先取消原本的對應。")
        return _redirect_back(request, link)
    messages.success(request, f"已將「{link.name}」對應到「{model}」，之後檢查會自動比對。")
    return _redirect_back(request, link)


@root_required
@require_POST
def official_catalog_acknowledge(request, pk):
    with transaction.atomic():
        link = get_object_or_404(OfficialCatalogModel.objects.select_for_update(), pk=pk, vehicle_model__isnull=False)
        if request.POST.get("content_hash") != link.content_hash:
            messages.error(request, "官網內容剛更新，請重新確認差異。")
            return _redirect_back(request, link)
        link.acknowledged_data, link.acknowledged_hash = link.data, link.content_hash
        link.save(update_fields=["acknowledged_data", "acknowledged_hash", "updated_at"])
        _audit(request, f"確認原廠官網變動：{link.name}", {"official_id": pk, "content_hash": link.content_hash})
    messages.success(request, f"已確認「{link.name}」的官網變動；車型資料未變更。")
    return _redirect_back(request, link)


@root_required
@require_POST
def official_catalog_ignore(request, pk):
    with transaction.atomic():
        link = get_object_or_404(OfficialCatalogModel.objects.select_for_update(), pk=pk, vehicle_model__isnull=True)
        restore = request.POST.get("action") == "restore"
        link.ignored_hash = "" if restore else link.content_hash
        link.save(update_fields=["ignored_hash", "updated_at"])
    messages.success(request, f"已恢復「{link.name}」到待對應。" if restore
                     else f"已忽略「{link.name}」；官網內容變動時會重新列出。")
    return _redirect_back(request, link)


@root_required
@require_POST
def official_catalog_fill_images(request, pk):
    link = get_object_or_404(OfficialCatalogModel.objects.select_related("vehicle_model"), pk=pk, vehicle_model__isnull=False)
    requested = {int(value) for value in request.POST.getlist("color") if value.isdigit()}
    fillable = {color.pk: official for color, official in service.fillable_colors(link)}
    targets = [(color_pk, fillable[color_pk]) for color_pk in requested if color_pk in fillable]
    if not targets:
        messages.error(request, "沒有可補的車色，可能已有圖片或官網車色已變更，請重新整理。")
        return _redirect_back(request, link)
    hosts = service.SOURCES[link.brand]["hosts"]
    filled, failed = [], []
    for color_pk, official in targets:
        try:
            upload = service.fetch_image(official["image_url"], hosts)
        except service.OfficialCatalogError as exc:
            failed.append(f"{official['name']}：{exc}")
            continue
        with transaction.atomic():
            color = VehicleColor.objects.select_for_update().filter(
                pk=color_pk, vehicle_model_id=link.vehicle_model_id, active=True,
            ).first()
            if not color or color.catalog_image:
                failed.append(f"{official['name']}：車色已有圖片或已停用，未覆蓋。")
                continue
            color.catalog_image.save(upload.name, upload, save=False)
            color.save(update_fields=["catalog_image", "updated_at"])
            filled.append({"color_id": color.pk, "color": color.name, "source": official["image_url"]})
    if filled:
        _audit(request, f"從原廠官網補上車色圖片：{link.vehicle_model}", {
            "official_id": link.pk, "vehicle_model_id": link.vehicle_model_id, "filled": filled,
        })
        messages.success(request, f"已補上 {len(filled)} 張車色圖片：" + "、".join(item["color"] for item in filled))
    for message in failed:
        messages.error(request, message)
    return _redirect_back(request, link)
