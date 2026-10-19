"""車色圖片總覽：一頁看出哪些啟用車色缺圖，並就地上傳或貼連結補圖。"""

import io

from django import forms
from django.core.cache import cache
from django.db import transaction
from django.db.models import Prefetch, Q
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_POST, require_safe
from PIL import Image, ImageOps

from sales.access.views import root_required
from sales.catalog_views import checked_upload
from sales.models import UserAccountAuditLog, VehicleBrand, VehicleCatalogEntry, VehicleColor, VehicleModel
from sales.services.remote_image import RemoteImageError, fetch_image, validate_url

THUMB_SIZE = (480, 360)


def thumb_url(color):
    # 每次儲存都是新的隨機檔名，可當版本號讓瀏覽器長期快取縮圖。
    return f"{reverse('catalog_photo_thumb', args=[color.pk])}?v={color.catalog_image.name.rsplit('/', 1)[-1]}"


def cell(color):
    return {"color": color, "has_photo": bool(color.catalog_image),
            "thumb": thumb_url(color) if color.catalog_image else ""}


def board_groups(keyword=""):
    """依根品牌分組；只列啟用機種的啟用車色，排序同機種清單。"""
    models = VehicleModel.objects.filter(active=True, colors__active=True)
    if keyword:
        models = models.filter(Q(brand__icontains=keyword) | Q(name__icontains=keyword)
                               | Q(model_number__icontains=keyword) | Q(family__name__icontains=keyword)
                               | Q(colors__name__icontains=keyword))
    models = models.distinct().select_related("family").prefetch_related(Prefetch(
        "colors", queryset=VehicleColor.objects.filter(active=True).order_by("name", "pk"), to_attr="board_colors"))
    brands = {brand.name.casefold(): brand for brand in VehicleBrand.objects.select_related("parent")}
    groups = {}
    for model in models:
        record = brands.get(model.brand.casefold())
        root = record.parent if record and record.parent_id else record
        name = root.name if root else model.brand
        group = groups.setdefault(name.casefold(), {
            "name": name, "order": root.display_order if root else 999, "rows": [], "missing": 0, "total": 0})
        cells = [cell(color) for color in model.board_colors]
        missing = sum(not item["has_photo"] for item in cells)
        group["rows"].append({"model": model, "cells": cells, "missing": missing,
                              "family": model.family.name if model.family_id else model.name})
        group["missing"] += missing
        group["total"] += len(cells)
    result = sorted(groups.values(), key=lambda group: (group["order"], group["name"].casefold()))
    for group in result:
        group["rows"].sort(key=lambda row: (row["family"].casefold(), row["model"].name.casefold(),
                                            -(row["model"].model_year or 0), row["model"].model_number.casefold(),
                                            row["model"].pk))
    return result


@root_required
@require_safe
def catalog_photo_board(request):
    keyword = request.GET.get("q", "").strip()[:60]
    groups = board_groups(keyword)
    missing, total = sum(group["missing"] for group in groups), sum(group["total"] for group in groups)
    return render(request, "sales/catalog_photo_board.html", {
        "groups": groups, "keyword": keyword, "missing_only": request.GET.get("missing") == "1",
        "missing_count": missing, "total_count": total,
        "done_percent": round((total - missing) * 100 / total) if total else 100,
    })


@root_required
@require_safe
def catalog_photo_thumb(request, color_pk):
    """管理用縮圖（含未上架）；依檔名快取，換圖後網址也會跟著變。"""
    color = VehicleColor.objects.filter(pk=color_pk, active=True, vehicle_model__active=True).first()
    if not color or not color.catalog_image:
        raise Http404
    key = f"catalog-photo-thumb:{color.catalog_image.name}"
    data = cache.get(key)
    if data is None:
        try:
            with color.catalog_image.open("rb") as source, Image.open(source) as image:
                image = ImageOps.exif_transpose(image)
                image.thumbnail(THUMB_SIZE)
                if image.mode not in ("RGB", "RGBA"):
                    image = image.convert("RGBA")
                buffer = io.BytesIO()
                image.save(buffer, "WEBP", quality=82, method=4)
        except (FileNotFoundError, OSError, ValueError):
            raise Http404 from None
        data = buffer.getvalue()
        cache.set(key, data, 60 * 60 * 24 * 30)
    response = HttpResponse(data, content_type="image/webp")
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, max-age=31536000, immutable"
    return response


def failure(message, status=400):
    return JsonResponse({"ok": False, "error": message}, status=status)


@root_required
@require_POST
def catalog_photo_save(request, color_pk):
    """單一車色就地存圖；檢查與下載沿用選車圖片頁，失敗只影響這一格。"""
    upload, url = request.FILES.get("image"), request.POST.get("url", "").strip()[:2000]
    expected = request.POST.get("expected", "")
    if bool(upload) == bool(url):
        return failure("請擇一：上傳檔案或貼上圖片連結。")
    try:
        if upload:
            image = checked_upload(forms.ImageField().clean(upload))
        else:
            validate_url(url)
            image = fetch_image(url)  # 不在資料庫鎖內連外
    except forms.ValidationError:
        return failure("請使用 8 MB 以內 JPEG、PNG 或 WebP 圖片。")
    except RemoteImageError as error:
        return failure(str(error))
    with transaction.atomic():
        color = (VehicleColor.objects.select_for_update(of=("self",)).select_related("vehicle_model")
                 .filter(pk=color_pk).first())
        if not color or not color.active or not color.vehicle_model.active:
            return failure("這個車色或機種已停用，請重新整理。", 409)
        if color.catalog_image.name != expected:
            return failure("這格圖片剛被其他人更新，請重新整理後再確認。", 409)
        previous = color.catalog_image.name
        color.catalog_image = image
        color.save(update_fields=["catalog_image", "updated_at"])
        _entry, created = VehicleCatalogEntry.objects.get_or_create(
            vehicle_model=color.vehicle_model, defaults={"published": True})
        UserAccountAuditLog.objects.create(
            actor=request.user, target=request.user, target_username=request.user.username, action="update",
            description=f"更新車色圖片：{color.vehicle_model} · {color.name}",
            metadata={"model_id": color.vehicle_model_id, "color_id": color.pk, "page": "photo_board",
                      "source": "url" if url else "upload", "url": url, "previous_image": previous,
                      "image": color.catalog_image.name, "catalog_entry_created": created},
        )
    return JsonResponse({"ok": True, "thumb": thumb_url(color), "image": color.catalog_image.name,
                         "replaced": bool(previous)})
