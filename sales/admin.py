from django.contrib import admin

from .models import (
    AccessoryLine,
    OrderDraft,
    OtherFeeLine,
    OrderEvent,
    SalesOrder,
    SalesSource,
    Store,
    VehicleColor,
    VehicleInventory,
    VehicleModel,
)


@admin.register(OrderDraft)
class OrderDraftAdmin(admin.ModelAdmin):
    list_display = ("display_name", "updated_by", "revision", "updated_at")
    readonly_fields = ("created_at", "updated_at", "revision")


@admin.register(Store)
class StoreAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "active")
    search_fields = ("name", "code")


@admin.register(SalesSource)
class SalesSourceAdmin(admin.ModelAdmin):
    list_display = ("name", "source_type", "active")
    list_filter = ("source_type", "active")


class VehicleColorInline(admin.TabularInline):
    model = VehicleColor
    extra = 1


@admin.register(VehicleModel)
class VehicleModelAdmin(admin.ModelAdmin):
    list_display = ("brand", "name", "energy_type", "active")
    list_filter = ("energy_type", "active")
    search_fields = ("brand", "name")
    inlines = [VehicleColorInline]


@admin.register(VehicleInventory)
class VehicleInventoryAdmin(admin.ModelAdmin):
    list_display = (
        "identifier",
        "vehicle_model",
        "color",
        "location_store",
        "status",
    )
    list_filter = ("status", "location_store", "vehicle_model")
    search_fields = ("engine_number", "frame_number")


class AccessoryLineInline(admin.TabularInline):
    model = AccessoryLine
    extra = 0


class OrderEventInline(admin.TabularInline):
    model = OrderEvent
    extra = 0
    readonly_fields = ("created_at",)


class OtherFeeLineInline(admin.TabularInline):
    model = OtherFeeLine
    extra = 0


@admin.register(SalesOrder)
class SalesOrderAdmin(admin.ModelAdmin):
    list_display = (
        "number",
        "owner_name",
        "vehicle_model",
        "color",
        "source_type",
        "status",
    )
    list_filter = ("status", "source_type")
    search_fields = (
        "number",
        "owner_name",
        "owner_phone",
        "owner_id_number",
        "final_plate_number",
    )
    inlines = [AccessoryLineInline, OtherFeeLineInline, OrderEventInline]
