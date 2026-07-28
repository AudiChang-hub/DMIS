from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from .forms import (
    AccessoryFormSet,
    AllocationForm,
    SalesOrderForm,
    SignedContractForm,
    VehicleInventoryForm,
)
from .models import (
    OrderEvent,
    SalesOrder,
    SalesSource,
    VehicleColor,
    VehicleInventory,
)


@login_required
def dashboard(request):
    query = request.GET.get("q", "").strip()
    orders = SalesOrder.objects.select_related(
        "source", "vehicle_model", "color", "allocated_vehicle"
    )
    if query:
        normalized = query.replace("-", "").replace(" ", "")
        orders = orders.filter(
            Q(number__icontains=query)
            | Q(owner_name__icontains=query)
            | Q(owner_phone__icontains=query)
            | Q(owner_id_number__icontains=normalized)
            | Q(source__name__icontains=query)
            | Q(vehicle_model__brand__icontains=query)
            | Q(vehicle_model__name__icontains=query)
            | Q(color__name__icontains=query)
            | Q(final_plate_number__icontains=normalized)
            | Q(allocated_vehicle__engine_number__icontains=normalized)
            | Q(allocated_vehicle__frame_number__icontains=normalized)
            | Q(note__icontains=query)
        ).distinct()

    active = orders.exclude(
        status__in=[SalesOrder.Status.COMPLETED, SalesOrder.Status.CANCELLED]
    )
    context = {
        "query": query,
        "search_results": orders[:50] if query else None,
        "urgent_orders": active.filter(
            status__in=[
                SalesOrder.Status.CANCEL_REFUND_PENDING,
                SalesOrder.Status.DELIVERED_DOCS_PENDING,
            ]
        )[:12],
        "contract_pending": active.filter(
            status=SalesOrder.Status.CONTRACT_PENDING
        )[:12],
        "allocation_pending": active.filter(
            status=SalesOrder.Status.ALLOCATION_PENDING
        )[:12],
        "in_progress": active.exclude(
            status__in=[
                SalesOrder.Status.CONTRACT_PENDING,
                SalesOrder.Status.ALLOCATION_PENDING,
                SalesOrder.Status.CANCEL_REFUND_PENDING,
                SalesOrder.Status.DELIVERED_DOCS_PENDING,
            ]
        )[:12],
        "counts": {
            "urgent": active.filter(
                status__in=[
                    SalesOrder.Status.CANCEL_REFUND_PENDING,
                    SalesOrder.Status.DELIVERED_DOCS_PENDING,
                ]
            ).count(),
            "contract": active.filter(
                status=SalesOrder.Status.CONTRACT_PENDING
            ).count(),
            "allocation": active.filter(
                status=SalesOrder.Status.ALLOCATION_PENDING
            ).count(),
            "inventory": VehicleInventory.objects.filter(
                status=VehicleInventory.Status.AVAILABLE
            ).count(),
        },
    }
    return render(request, "sales/dashboard.html", context)


@login_required
def order_list(request):
    orders = SalesOrder.objects.select_related("source", "vehicle_model", "color")
    status = request.GET.get("status")
    if status:
        orders = orders.filter(status=status)
    return render(
        request,
        "sales/order_list.html",
        {"orders": orders[:200], "statuses": SalesOrder.Status.choices},
    )


@login_required
def order_create(request):
    if request.method == "POST":
        form = SalesOrderForm(request.POST, request.FILES)
        formset = AccessoryFormSet(request.POST)
        if form.is_valid() and formset.is_valid():
            order = form.save(commit=False)
            order.status = SalesOrder.Status.CONTRACT_PENDING
            order.save()
            formset.instance = order
            formset.save()
            order.calculated_balance = order.calculate_balance()
            order.actual_balance = order.calculated_balance
            order.save(
                update_fields=["calculated_balance", "actual_balance", "updated_at"]
            )
            OrderEvent.objects.create(
                order=order,
                event_type="created",
                description="建立訂單，等待列印並上傳已簽署合約。",
                actor_name=request.user.get_username(),
            )
            messages.success(request, "訂單已建立。請列印一式兩份並上傳簽署合約。")
            return redirect("order_detail", pk=order.pk)
    else:
        form = SalesOrderForm()
        formset = AccessoryFormSet()
    return render(
        request,
        "sales/order_form.html",
        {"form": form, "formset": formset},
    )


@login_required
def order_detail(request, pk):
    order = get_object_or_404(
        SalesOrder.objects.select_related(
            "source",
            "vehicle_model",
            "color",
            "allocated_vehicle",
            "allocated_vehicle__location_store",
        ).prefetch_related("accessories", "events"),
        pk=pk,
    )
    return render(
        request,
        "sales/order_detail.html",
        {
            "order": order,
            "contract_form": SignedContractForm(instance=order),
            "allocation_form": AllocationForm(order),
        },
    )


@login_required
def contract_print(request, pk):
    order = get_object_or_404(
        SalesOrder.objects.select_related(
            "source", "vehicle_model", "color"
        ).prefetch_related("accessories"),
        pk=pk,
    )
    return render(request, "sales/contract_print.html", {"order": order})


@login_required
def contract_upload(request, pk):
    order = get_object_or_404(SalesOrder, pk=pk)
    if request.method != "POST":
        return redirect("order_detail", pk=pk)
    form = SignedContractForm(request.POST, request.FILES, instance=order)
    if form.is_valid():
        order = form.save(commit=False)
        order.status = SalesOrder.Status.ALLOCATION_PENDING
        order.save()
        OrderEvent.objects.create(
            order=order,
            event_type="contract_uploaded",
            description="已上傳簽署合約，訂單進入待配車。",
            actor_name=request.user.get_username(),
        )
        messages.success(request, "已上傳簽署合約，現在可以進行配車。")
    else:
        messages.error(request, "合約上傳失敗，請確認檔案格式。")
    return redirect("order_detail", pk=pk)


@login_required
def allocate_vehicle(request, pk):
    order = get_object_or_404(SalesOrder, pk=pk)
    if request.method != "POST":
        return redirect("order_detail", pk=pk)
    form = AllocationForm(order, request.POST)
    if form.is_valid():
        try:
            order.allocate(form.cleaned_data["vehicle"])
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
        else:
            OrderEvent.objects.create(
                order=order,
                event_type="allocated",
                description=f"已配車：{order.allocated_vehicle}",
                actor_name=request.user.get_username(),
            )
            messages.success(request, "配車完成，實體車輛已鎖定。")
    else:
        messages.error(request, "請選擇可用的實體車輛。")
    return redirect("order_detail", pk=pk)


@login_required
def inventory_list(request):
    vehicles = VehicleInventory.objects.select_related(
        "vehicle_model", "color", "ownership_store", "location_store"
    )
    return render(
        request,
        "sales/inventory_list.html",
        {"vehicles": vehicles[:300], "statuses": VehicleInventory.Status.choices},
    )


@login_required
def inventory_create(request):
    if request.method == "POST":
        form = VehicleInventoryForm(request.POST, request.FILES)
        if form.is_valid():
            vehicle = form.save()
            messages.success(request, f"已建立庫存車輛：{vehicle.identifier}")
            return redirect("inventory_list")
    else:
        form = VehicleInventoryForm()
    return render(request, "sales/inventory_form.html", {"form": form})


@login_required
def vehicle_colors(request):
    model_id = request.GET.get("model")
    colors = VehicleColor.objects.filter(
        vehicle_model_id=model_id, active=True
    ).values("id", "name")
    return JsonResponse({"results": list(colors)})


@login_required
def sales_sources(request):
    source_type = request.GET.get("type")
    sources = SalesSource.objects.filter(
        source_type=source_type, active=True
    ).values("id", "name")
    return JsonResponse({"results": list(sources)})


@login_required
def protected_media(request, model_name, pk, field_name):
    allowed = {
        "order": (SalesOrder, {"id_front", "id_back", "signed_contract"}),
        "vehicle": (VehicleInventory, {"condition_photo"}),
    }
    if model_name not in allowed or field_name not in allowed[model_name][1]:
        raise Http404
    model = allowed[model_name][0]
    instance = get_object_or_404(model, pk=pk)
    file_field = getattr(instance, field_name)
    if not file_field:
        raise Http404
    response = FileResponse(file_field.open("rb"))
    response["Content-Disposition"] = f'inline; filename="{file_field.name.split("/")[-1]}"'
    response["Cache-Control"] = "private, no-store"
    return response
