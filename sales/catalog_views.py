"""公開車款展示；對外資料只從明列欄位輸出，不序列化內部主檔。"""

import uuid
from django import forms
from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_safe, require_http_methods
from sales.access.views import root_required
from sales.models import VehicleCatalogEntry, VehicleModel, VehicleColor, UserAccountAuditLog
from sales.services.price_version import (
    resolve_vehicle_price_version,
    recommended_vehicle_price,
)
from sales.services.installment_plan import resolve_installment_plan_version


def listed_models():
    return VehicleModel.objects.filter(
        active=True, catalog_entry__published=True
    ).select_related("catalog_entry")


def model_card(model):
    version = resolve_vehicle_price_version(model.pk, timezone.localdate())
    price, label = recommended_vehicle_price(version, "cash")
    return {"model": model, "price": price, "price_label": label}


@require_safe
def catalog(request):
    models = listed_models()
    selected_model = request.GET.get("model", "")[:20]
    if selected_model:
        models = models.filter(pk=int(selected_model)) if selected_model.isascii() and selected_model.isdigit() and len(selected_model) < 19 else models.none()
    query = request.GET.get("q", "").strip()[:150]
    brand = request.GET.get("brand", "")[:80]
    energy = request.GET.get("energy", "")[:20]
    if query:
        models = models.filter(
            Q(name__icontains=query)
            | Q(brand__icontains=query)
            | Q(model_number__icontains=query)
        )
    if brand:
        models = models.filter(brand=brand)
    if energy:
        models = models.filter(energy_type=energy)
    model_options = listed_models()
    if brand:
        model_options = model_options.filter(brand=brand)
    if energy:
        model_options = model_options.filter(energy_type=energy)
    colors = VehicleColor.objects.filter(active=True, vehicle_model__in=models).select_related(
        "vehicle_model__catalog_entry"
    ).order_by("vehicle_model__catalog_entry__position", "vehicle_model__brand",
               "vehicle_model__name", "vehicle_model_id", "name", "pk")
    page = Paginator(colors, 12).get_page(request.GET.get("page"))
    cards, model_cards = [], {}
    for color in page:
        if color.vehicle_model_id not in model_cards:
            model_cards[color.vehicle_model_id] = model_card(color.vehicle_model)
        cards.append({**model_cards[color.vehicle_model_id], "color": color})
    return render(
        request,
        "sales/catalog.html",
        {
            "cards": cards,
            "model_count": models.count(),
            "page_obj": page,
            "query": query,
            "selected_model": selected_model,
            "model_options": model_options.order_by("brand", "name", "pk"),
            "selected_brand": brand,
            "selected_energy": energy,
            "brands": listed_models()
            .order_by("brand")
            .values_list("brand", flat=True)
            .distinct(),
            "energies": VehicleModel.EnergyType.choices,
        },
    )


@require_safe
def catalog_detail(request, pk):
    model = get_object_or_404(listed_models(), pk=pk)
    colors = list(model.colors.filter(active=True))
    selected_color = request.GET.get("color", "")[:20]
    version = resolve_vehicle_price_version(pk, timezone.localdate())
    plan = resolve_installment_plan_version(pk, timezone.localdate())
    # 不將 expected_disbursement、內部註記等資料送到模板或 JSON。
    options = (
        list(
            plan.options.filter(company__active=True)
            .order_by("periods")
            .values("periods", "monthly_amount", "opening_fee", "company__name")
        )
        if plan
        else []
    )
    return render(
        request,
        "sales/catalog_detail.html",
        {
            **model_card(model),
            "price_version": version,
            "options": options,
            "colors": colors,
            "selected_color_id": next((c.pk for c in colors if str(c.pk) == selected_color), None),
            "today": timezone.localdate(),
        },
    )


@require_safe
def catalog_image(request, pk, color_pk=None):
    entry = get_object_or_404(
        VehicleCatalogEntry,
        vehicle_model_id=pk,
        published=True,
        vehicle_model__active=True,
    )
    photo = entry.image
    if color_pk is not None:
        photo = get_object_or_404(VehicleColor, pk=color_pk, vehicle_model_id=pk, active=True).catalog_image
    if not photo:
        raise Http404
    try:
        response = FileResponse(photo.open("rb"))
    except FileNotFoundError:
        raise Http404 from None
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "no-store"
    return response


class CatalogForm(forms.ModelForm):
    expected_revision = forms.IntegerField(widget=forms.HiddenInput, min_value=0)
    main_image_color = forms.ModelChoiceField(
        queryset=VehicleColor.objects.none(), required=False,
        label="將既有主圖對應至車色", empty_label="不變更車色圖片",
        help_text="確認主圖的實際顏色後才選擇；其他顏色不會共用此圖。已有不同車色圖時不覆蓋。",
    )

    class Meta:
        model = VehicleCatalogEntry
        fields = ["image", "description", "published", "position"]
        widgets = {"description": forms.Textarea(attrs={"rows": 5})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["expected_revision"].initial = self.instance.revision
        self.catalog_colors = list(self.instance.vehicle_model.colors.all())
        self.fields["main_image_color"].queryset = self.instance.vehicle_model.colors.filter(active=True)
        for color in self.catalog_colors:
            self.fields[f"color_image_{color.pk}"] = forms.ImageField(label=f"{color.name} · 車色圖片", required=False,
                widget=forms.FileInput(attrs={"accept": "image/jpeg,image/png,image/webp"}))
            self.fields[f"color_remove_{color.pk}"] = forms.BooleanField(label=f"移除 {color.name} 的展示圖片（保留備份檔）", required=False)
        # 原始媒體 URL 不作為對外預覽；僅經 catalog_image 讀取。
        self.fields["image"].widget = forms.FileInput(
            attrs={"accept": "image/jpeg,image/png,image/webp"}
        )
        for field in self.fields.values():
            field.widget.attrs["class"] = (
                "form-check"
                if isinstance(field.widget, forms.CheckboxInput)
                else "form-control"
            )

    def clean_image(self):
        upload = self.cleaned_data.get("image")
        if upload and hasattr(upload, "content_type"):
            if upload.size > 8 * 1024 * 1024:
                raise forms.ValidationError("圖片最多 8 MB。")
            fmt = getattr(getattr(upload, "image", None), "format", "")
            if fmt not in {"JPEG", "PNG", "WEBP"}:
                raise forms.ValidationError("請使用 JPEG、PNG 或 WebP 圖片。")
            upload.name = (
                f"{uuid.uuid4().hex}.{ {'JPEG':'jpg', 'PNG':'png', 'WEBP':'webp'}[fmt]}"
            )
        return upload

    def clean(self):
        data = super().clean()
        target_color = data.get("main_image_color")
        if target_color:
            if not self.instance.image or hasattr(data.get("image"), "content_type"):
                self.add_error("main_image_color", "請先儲存主圖，再確認要對應的車色。")
            elif target_color.catalog_image and target_color.catalog_image.name != self.instance.image.name:
                self.add_error("main_image_color", "此車色已有不同圖片；若需更換，請使用該色的圖片上傳欄位。")
            if data.get(f"color_image_{target_color.pk}") or data.get(f"color_remove_{target_color.pk}"):
                self.add_error("main_image_color", "同一車色不可同時對應主圖、上傳或移除圖片。")
        for color in self.catalog_colors:
            key = f"color_image_{color.pk}"
            upload = data.get(key)
            if upload:
                fmt = getattr(getattr(upload, "image", None), "format", "")
                if upload.size > 8 * 1024 * 1024 or fmt not in {"JPEG", "PNG", "WEBP"}:
                    self.add_error(key, "請使用 8 MB 以內 JPEG、PNG 或 WebP 圖片。")
                else:
                    upload.name = f"{uuid.uuid4().hex}.{ {'JPEG':'jpg','PNG':'png','WEBP':'webp'}[fmt]}"
        if data.get("published") and not self.instance.vehicle_model.active:
            self.add_error("published", "停用車款不能上架，請先確認機種狀態。")
        return data


@root_required
@require_safe
def catalog_manage(request):
    query = request.GET.get("q", "").strip()[:150]
    models = VehicleModel.objects.select_related("catalog_entry").filter(
        Q(name__icontains=query)
        | Q(brand__icontains=query)
        | Q(model_number__icontains=query)
    )
    return render(
        request,
        "sales/catalog_manage.html",
        {
            "query": query,
            "page_obj": Paginator(models.order_by("brand", "name", "pk"), 20).get_page(
                request.GET.get("page")
            ),
        },
    )


@root_required
@require_http_methods(["GET", "POST"])
def catalog_edit(request, pk):
    model = get_object_or_404(VehicleModel, pk=pk)
    entry = VehicleCatalogEntry.objects.filter(
        vehicle_model=model
    ).first() or VehicleCatalogEntry(vehicle_model=model)
    form = CatalogForm(request.POST or None, request.FILES or None, instance=entry)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            target_color = form.cleaned_data.get("main_image_color")
            locked_model = VehicleModel.objects.select_for_update().get(pk=pk)
            current = (
                VehicleCatalogEntry.objects.select_for_update()
                .filter(vehicle_model=model)
                .first()
            )
            if form.cleaned_data["expected_revision"] != (
                current.revision if current else 0
            ):
                form.add_error(None, "車款展示已被其他視窗更新，請重新整理。")
            elif form.cleaned_data["published"] and not locked_model.active:
                form.add_error(None, "車款剛被停用，請重新整理。")
            elif target_color and not VehicleColor.objects.filter(
                pk=target_color.pk, vehicle_model=locked_model, active=True,
                catalog_image=target_color.catalog_image.name,
            ).exists():
                form.add_error(None, "車色或圖片已被修改，請重新整理後再確認。")
            else:
                changed = form.save(commit=False)
                changed.revision += 1
                changed.save()
                if target_color:
                    target_color.catalog_image = changed.image.name
                    target_color.save(update_fields=["catalog_image", "updated_at"])
                for color in form.catalog_colors:
                    upload = form.cleaned_data.get(f"color_image_{color.pk}")
                    if upload or form.cleaned_data.get(f"color_remove_{color.pk}"):
                        color.catalog_image = upload or ""
                        color.save(update_fields=["catalog_image", "updated_at"])
                UserAccountAuditLog.objects.create(
                    actor=request.user,
                    target=request.user,
                    target_username=request.user.username,
                    action="update",
                    description=f"更新車款展示：{model}",
                    metadata={
                        "model_id": pk,
                        "published": changed.published,
                        "revision": changed.revision,
                        "main_image_color_id": target_color.pk if target_color else None,
                    },
                )
                messages.success(request, "車款展示已儲存；上架且啟用的車款才會公開。")
                return redirect("catalog_manage")
    return render(
        request,
        "sales/catalog_edit.html",
        {"form": form, "model": model, "entry": entry},
    )
