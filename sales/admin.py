from django.contrib import admin

from .models import (
    AccessoryLine,
    OrderDraft,
    OtherFeeLine,
    OrderEvent,
    RegistrationDocument,
    SalesOrder,
    SalesSource,
    Store,
    SubsidyDocument,
    VehicleColor,
    VehicleInventory,
    VehicleInventoryHistory,
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
    list_display = ("brand", "name", "energy_type", "displacement_cc", "active")
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


@admin.register(VehicleInventoryHistory)
class VehicleInventoryHistoryAdmin(admin.ModelAdmin):
    list_display = ("vehicle", "event_type", "actor_name", "created_at")
    list_filter = ("event_type", "status_snapshot", "location_store_snapshot")
    search_fields = ("vehicle__engine_number", "vehicle__frame_number", "actor_name", "reason")
    readonly_fields = (
        "vehicle",
        "event_type",
        "actor_name",
        "reason",
        "changes",
        "status_snapshot",
        "location_store_snapshot",
        "condition_note_snapshot",
        "condition_resolution_snapshot",
        "condition_photo_snapshot",
        "from_location",
        "to_location",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


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


class RegistrationDocumentInline(admin.TabularInline):
    model = RegistrationDocument
    extra = 0
    readonly_fields = ("uploaded_by", "created_at", "updated_at")


class SubsidyDocumentInline(admin.TabularInline):
    model = SubsidyDocument
    extra = 0
    readonly_fields = ("uploaded_by", "created_at", "updated_at")


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
    inlines = [
        AccessoryLineInline,
        OtherFeeLineInline,
        SubsidyDocumentInline,
        RegistrationDocumentInline,
        OrderEventInline,
    ]
