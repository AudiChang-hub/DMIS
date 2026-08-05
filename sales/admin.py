from django.contrib import admin

from .models import (
    AccessoryProduct,
    AccessoryLine,
    BusinessHoliday,
    BrandRegistrationFeeRule,
    DealerVolumeBonusAllocation,
    DealerVolumeBonusAdjustment,
    DealerVolumeBonusRule,
    DealerVolumeBonusSettlement,
    DealerVolumeBonusTier,
    DeliveryRecord,
    InstallmentCompany,
    InstallmentPlanOption,
    InstallmentPlanVersion,
    LegacyImportBatch,
    LegacyImportRow,
    LegacySalesSnapshot,
    OrderDraft,
    OtherFeeLine,
    OrderEvent,
    OrderOperationsProfile,
    RegistrationDocument,
    PaymentRecord,
    SalesOrder,
    SalesSource,
    SalesSourceBrandPolicy,
    SalesSourceContact,
    Store,
    SubsidyDocument,
    SubsidyItem,
    VehicleColor,
    VehicleInventory,
    VehicleInventoryHistory,
    VehicleIncentiveRule,
    VehicleIncentiveInstallmentRate,
    VehicleModel,
    VehiclePriceVersion,
    VehicleSettlementCostRule,
)


@admin.register(BusinessHoliday)
class BusinessHolidayAdmin(admin.ModelAdmin):
    list_display = ("date", "name", "active")
    list_filter = ("active",)
    search_fields = ("name",)


@admin.register(DeliveryRecord)
class DeliveryRecordAdmin(admin.ModelAdmin):
    list_display = ("order", "recipient_name", "handover_location", "completed_by")
    search_fields = ("order__number", "recipient_name", "recipient_phone")


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
    list_display = ("name", "source_type", "phone", "vehicle_capacity", "active")
    list_filter = ("source_type", "active")


admin.site.register(InstallmentCompany)
admin.site.register(InstallmentPlanVersion)
admin.site.register(InstallmentPlanOption)
admin.site.register(SalesSourceContact)
admin.site.register(SalesSourceBrandPolicy)
admin.site.register(DealerVolumeBonusRule)
admin.site.register(DealerVolumeBonusTier)
admin.site.register(DealerVolumeBonusSettlement)
admin.site.register(DealerVolumeBonusAllocation)
admin.site.register(DealerVolumeBonusAdjustment)
admin.site.register(LegacyImportBatch)
admin.site.register(LegacyImportRow)
admin.site.register(LegacySalesSnapshot)
admin.site.register(SubsidyItem)
admin.site.register(BrandRegistrationFeeRule)


class VehicleColorInline(admin.TabularInline):
    model = VehicleColor
    extra = 1


@admin.register(VehicleModel)
class VehicleModelAdmin(admin.ModelAdmin):
    list_display = (
        "brand",
        "name",
        "model_number",
        "model_year",
        "model_code",
        "energy_type",
        "displacement_cc",
        "motor_power_kw",
        "horsepower_hp",
        "suggested_price",
        "active",
    )
    list_filter = ("energy_type", "active")
    search_fields = ("brand", "name", "model_number")
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


@admin.register(VehiclePriceVersion)
class VehiclePriceVersionAdmin(admin.ModelAdmin):
    list_display = (
        "vehicle_model",
        "suggested_retail_price",
        "cash_price_including_registration",
        "cash_price_excluding_registration",
        "effective_from",
        "effective_to",
        "active",
    )
    list_filter = ("active",)
    search_fields = (
        "vehicle_model__brand",
        "vehicle_model__name",
        "vehicle_model__model_number",
        "source_note",
    )


@admin.register(AccessoryProduct)
class AccessoryProductAdmin(admin.ModelAdmin):
    list_display = ("name", "sale_price", "labor_fee", "cost", "active")
    list_filter = ("active",)
    search_fields = ("name", "note")


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


@admin.register(VehicleSettlementCostRule)
class VehicleSettlementCostRuleAdmin(admin.ModelAdmin):
    list_display = (
        "vehicle_model",
        "registration_county",
        "amount",
        "effective_from",
        "effective_to",
        "active",
    )
    list_filter = ("registration_county", "active")
    search_fields = (
        "vehicle_model__brand",
        "vehicle_model__name",
        "vehicle_model__model_number",
    )


class VehicleIncentiveInstallmentRateInline(admin.TabularInline):
    model = VehicleIncentiveInstallmentRate
    extra = 1


@admin.register(VehicleIncentiveRule)
class VehicleIncentiveRuleAdmin(admin.ModelAdmin):
    list_display = (
        "vehicle_model",
        "sales_bonus",
        "promotion_subsidy",
        "installment_interest_subsidy",
        "effective_from",
        "effective_to",
        "active",
    )
    list_filter = ("active",)
    search_fields = (
        "vehicle_model__brand",
        "vehicle_model__name",
        "vehicle_model__model_number",
    )
    inlines = [VehicleIncentiveInstallmentRateInline]


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


class PaymentRecordInline(admin.TabularInline):
    model = PaymentRecord
    extra = 0
    readonly_fields = ("confirmed_by", "confirmed_at", "created_at", "updated_at")


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
        PaymentRecordInline,
        OrderEventInline,
    ]


@admin.register(OrderOperationsProfile)
class OrderOperationsProfileAdmin(admin.ModelAdmin):
    list_display = (
        "order",
        "payment_confirmed",
        "installment_transfer_confirmed",
        "updated_by",
        "updated_at",
    )
    list_filter = ("payment_confirmed", "installment_transfer_confirmed")
    search_fields = ("order__number", "order__owner_name", "dealer_name")
    readonly_fields = (
        "vehicle_control_password_encrypted",
        "battery_password_encrypted",
        "created_at",
        "updated_at",
    )
