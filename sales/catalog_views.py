"""公開車款展示；對外資料只從明列欄位輸出，不序列化內部主檔。"""

import uuid
from django import forms
from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q, Case, When, Value, IntegerField
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
from sales.services.catalog_selection import selection_data, sign_selection


def listed_models():
    return VehicleModel.objects.filter(
        active=True, catalog_entry__published=True
    ).select_related("catalog_entry")


def model_card(model):
    version = resolve_vehicle_price_version(model.pk, timezone.localdate())
    price, label = recommended_vehicle_price(version, "cash")
    return {"model": model, "price": price, "price_label": label}


def catalog_filters(models, request):
    """共用篩選，但由呼叫端限定公開／管理的資料範圍。"""
    selected = {key: request.GET.get(key, "").strip()[:150]
                for key in ("brand", "model_name", "model_number", "energy", "q")}
    rows = list(models.order_by("brand", "name", "model_number", "energy_type")
                .values("brand", "name", "model_number", "energy_type").distinct())
    mapping = {"brand": "brand", "model_name": "name", "model_number": "model_number", "energy": "energy_type"}
    filtered = models
    for key, field in mapping.items():
        if selected[key]:
            filtered = filtered.filter(**{field: selected[key]})
    if selected["q"]:
        filtered = filtered.filter(Q(name__icontains=selected["q"]) | Q(brand__icontains=selected["q"]) | Q(model_number__icontains=selected["q"]))
    def choices(field, *parents):
        return sorted({row[field] for row in rows if row[field] and all(
            not selected[key] or row[mapping[key]] == selected[key] for key in parents)})
    return filtered, {
        "filter_options": rows, "brands": choices("brand"),
        "model_names": choices("name", "brand", "energy"),
        "model_numbers": choices("model_number", "brand", "model_name", "energy"),
        "selected_brand": selected["brand"], "selected_name": selected["model_name"],
        "selected_number": selected["model_number"], "selected_energy": selected["energy"],
        "query": selected["q"], "energies": VehicleModel.EnergyType.choices,
    }


@require_safe
def catalog(request):
    models, filters = catalog_filters(listed_models(), request)
    selected_model = request.GET.get("model", "")[:20]
    if selected_model:
        models = models.filter(pk=int(selected_model)) if selected_model.isascii() and selected_model.isdigit() and len(selected_model) < 19 else models.none()
    colors = VehicleColor.objects.filter(active=True, vehicle_model__in=models).select_related(
        "vehicle_model__catalog_entry"
    ).annotate(energy_rank=Case(
        When(vehicle_model__energy_type="gas", then=Value(0)),
        When(vehicle_model__energy_type="micro_electric", then=Value(1)),
        When(vehicle_model__energy_type="light_electric", then=Value(2)),
        default=Value(3), output_field=IntegerField(),
    )).order_by("vehicle_model__brand", "energy_rank", "vehicle_model__displacement_cc",
               "vehicle_model__name", "vehicle_model__model_number", "vehicle_model_id", "name", "pk")
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
            "selected_model": selected_model,
            **filters,
        },
    )


@require_safe
def catalog_detail(request, pk):
    model = get_object_or_404(listed_models(), pk=pk)
    colors = list(model.colors.filter(active=True))
    selected_color = request.GET.get("color", "")[:20]
    chosen_color = next((c for c in colors if str(c.pk) == selected_color), None)
    version = resolve_vehicle_price_version(pk, timezone.localdate())
    plan = resolve_installment_plan_version(pk, timezone.localdate())
    # 不將 expected_disbursement、內部註記等資料送到模板或 JSON。
    options = (
        list(
            plan.options.select_related("company").filter(company__active=True)
            .order_by("periods")
        )
        if plan
        else []
    )
    payment_choices = []
    if chosen_color:
        for option in [None, *options]:
            data = selection_data(model, chosen_color, "installment" if option else "cash", option)
            payment_choices.append({**data, "token": sign_selection(data)})
    return render(
        request,
        "sales/catalog_detail.html",
        {
            **model_card(model),
            "price_version": version,
            "options": [{"company": {"name": option.company.name}, "periods": option.periods,
                         "monthly_amount": option.monthly_amount, "opening_fee": option.opening_fee} for option in options],
            "colors": colors,
            "selected_color": chosen_color,
            "selected_color_id": chosen_color.pk if chosen_color else None,
            "payment_choices": payment_choices,
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
    return image_response(photo)


def image_response(photo):
    if not photo:
        raise Http404
    try:
        response = FileResponse(photo.open("rb"))
    except FileNotFoundError:
        raise Http404 from None
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "no-store"
    return response


@root_required
@require_safe
def catalog_preview_image(request, pk, color_pk=None):
    """未上架圖片僅限管理者預覽，不放寬公開圖片入口。"""
    model = get_object_or_404(VehicleModel, pk=pk, active=True)
    if color_pk is not None:
        photo = get_object_or_404(model.colors, pk=color_pk, active=True).catalog_image
    else:
        photo = get_object_or_404(VehicleCatalogEntry, vehicle_model=model).image
    response = image_response(photo)
    response["Cache-Control"] = "private, no-store"
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
        self.catalog_colors = list(self.instance.vehicle_model.colors.filter(active=True).order_by("name", "pk"))
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

        self.color_sections = [
            {"color": color, "upload": self[f"color_image_{color.pk}"],
             "remove": self[f"color_remove_{color.pk}"]}
            for color in self.catalog_colors
        ]

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
        if any(key.startswith(("color_image_", "color_remove_")) and key not in self.fields
               for key in set(self.data) | set(self.files)):
            self.add_error(None, "車色已停用或不屬於此車款，請重新整理後再編輯。")
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
            if upload and data.get(f"color_remove_{color.pk}"):
                self.add_error(key, "同一車色不可同時上傳與移除圖片。")
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
    active_models = VehicleModel.objects.filter(active=True)
    models, filters = catalog_filters(active_models.select_related("catalog_entry"), request)
    return render(
        request,
        "sales/catalog_manage.html",
        {
            **filters,
            "page_obj": Paginator(models.order_by("brand", "name", "pk"), 20).get_page(
                request.GET.get("page")
            ),
        },
    )


@root_required
@require_http_methods(["GET", "POST"])
def catalog_edit(request, pk):
    model = get_object_or_404(VehicleModel, pk=pk, active=True)
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
            locked_colors = {color.pk: color for color in VehicleColor.objects.select_for_update()
                             .filter(vehicle_model=locked_model).order_by("pk")}
            colors_changed = any(
                color.pk not in locked_colors or not locked_colors[color.pk].active
                or locked_colors[color.pk].catalog_image.name != color.catalog_image.name
                for color in form.catalog_colors
            )
            if form.cleaned_data["expected_revision"] != (
                current.revision if current else 0
            ):
                form.add_error(None, "車款展示已被其他視窗更新，請重新整理。")
            elif not locked_model.active:
                form.add_error(None, "車款剛被停用，請重新整理。")
            elif colors_changed:
                form.add_error(None, "車色或圖片已被修改，請重新整理後再確認。")
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
