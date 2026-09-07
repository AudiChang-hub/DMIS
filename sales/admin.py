from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import GroupAdmin, UserAdmin
from django.contrib.auth.models import Group

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
    DealerRewardCatalogItem,
    DealerRewardCostVersion,
    DealerVehicleRewardItem,
    DealerVehicleRewardPlan,
    DeliveryRecord,
    InstallmentCompany,
    InstallmentPlanOption,
    InstallmentPlanVersion,
    LegacyImportBatch,
    LegacyImportCorrection,
    LegacyImportMasterMapping,
    LegacyImportRow,
    LegacySalesSnapshot,
    OrderDraft,
    OtherFeeLine,
    OrderEvent,
    OrderOperationsProfile,
    RegistrationDocument,
    PaymentRecord,
    PositionedPrintField,
    PositionedPrintTemplate,
    SalesOrder,
    SalesSource,
    SalesSourceCategory,
    SalesSourceBrandPolicy,
    SalesSourceCooperationProfile,
    SalesSourcePlatformContact,
    Store,
    SubsidyDocument,
    SubsidyItem,
    VehicleColor,
    VehicleBrand,
    VehicleInventory,
    VehicleInventoryHistory,
    VehicleFactoryModelCode,
    VehicleIncentiveRule,
    VehicleModel,
    VehicleModelFamily,
    VehiclePriceVersion,
    VehicleSettlementCostRule,
)


class ReadOnlyAdminMixin:
    """正式異動統一由具驗證、稽核及連動處理的系統頁面執行。"""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class ReadOnlyOperationalAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    pass


# 保留 Django admin 作為緊急查詢入口，但不允許繞過帳號管理流程直接改權限。
User = get_user_model()
admin.site.unregister(User)
admin.site.unregister(Group)


@admin.register(User)
class ReadOnlyUserAdmin(ReadOnlyAdminMixin, UserAdmin):
    pass


@admin.register(Group)
class ReadOnlyGroupAdmin(ReadOnlyAdminMixin, GroupAdmin):
    pass


@admin.register(BusinessHoliday)
class BusinessHolidayAdmin(ReadOnlyOperationalAdmin):
    list_display = ("date", "name", "source", "active", "updated_at")
    list_filter = ("source", "active")
    search_fields = ("name",)


@admin.register(DeliveryRecord)
class DeliveryRecordAdmin(ReadOnlyOperationalAdmin):
    list_display = ("order", "recipient_name", "handover_location", "completed_by")
    search_fields = ("order__number", "recipient_name", "recipient_phone")


@admin.register(OrderDraft)
class OrderDraftAdmin(ReadOnlyOperationalAdmin):
    list_display = ("display_name", "updated_by", "revision", "updated_at")
    readonly_fields = ("created_at", "updated_at", "revision")


@admin.register(Store)
class StoreAdmin(ReadOnlyOperationalAdmin):
    list_display = ("name", "code", "active")
    search_fields = ("name", "code")


class SalesSourcePlatformContactInline(admin.TabularInline):
    model = SalesSourcePlatformContact
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SalesSource)
class SalesSourceAdmin(ReadOnlyOperationalAdmin):
    list_display = (
        "name", "category", "source_type", "responsible_person", "phone", "mobile",
        "city", "district", "staff_commission", "holiday_gift", "has_line_group", "active"
    )
    list_filter = (
        "category", "source_type", "city", "district", "holiday_gift", "has_line_group", "active",
    )
    search_fields = ("name", "code", "responsible_person", "phone", "mobile", "address", "city", "district")
    inlines = [SalesSourcePlatformContactInline]

    def get_inlines(self, request, obj):
        if obj and obj.source_type == SalesSource.SourceType.PLATFORM:
            return self.inlines
        return []


@admin.register(SalesSourceCategory)
class SalesSourceCategoryAdmin(ReadOnlyOperationalAdmin):
    list_display = ("name", "system_behavior", "active")
    list_filter = ("system_behavior", "active")
    search_fields = ("name", "note")


admin.site.register(InstallmentCompany, ReadOnlyOperationalAdmin)
admin.site.register(VehicleBrand, ReadOnlyOperationalAdmin)
admin.site.register(VehicleModelFamily, ReadOnlyOperationalAdmin)
admin.site.register(VehicleFactoryModelCode, ReadOnlyOperationalAdmin)
admin.site.register(InstallmentPlanVersion, ReadOnlyOperationalAdmin)
admin.site.register(InstallmentPlanOption, ReadOnlyOperationalAdmin)
admin.site.register(SalesSourceBrandPolicy, ReadOnlyOperationalAdmin)
admin.site.register(SalesSourceCooperationProfile, ReadOnlyOperationalAdmin)
admin.site.register(DealerVolumeBonusRule, ReadOnlyOperationalAdmin)
admin.site.register(DealerVolumeBonusTier, ReadOnlyOperationalAdmin)
admin.site.register(DealerVolumeBonusSettlement, ReadOnlyOperationalAdmin)
admin.site.register(DealerVolumeBonusAllocation, ReadOnlyOperationalAdmin)
admin.site.register(DealerVolumeBonusAdjustment, ReadOnlyOperationalAdmin)
admin.site.register(DealerRewardCatalogItem, ReadOnlyOperationalAdmin)
admin.site.register(DealerRewardCostVersion, ReadOnlyOperationalAdmin)
admin.site.register(DealerVehicleRewardPlan, ReadOnlyOperationalAdmin)
admin.site.register(DealerVehicleRewardItem, ReadOnlyOperationalAdmin)
admin.site.register(LegacyImportBatch, ReadOnlyOperationalAdmin)
admin.site.register(LegacyImportCorrection, ReadOnlyOperationalAdmin)
admin.site.register(LegacyImportMasterMapping, ReadOnlyOperationalAdmin)
admin.site.register(LegacyImportRow, ReadOnlyOperationalAdmin)
admin.site.register(LegacySalesSnapshot, ReadOnlyOperationalAdmin)
admin.site.register(SubsidyItem, ReadOnlyOperationalAdmin)
admin.site.register(BrandRegistrationFeeRule, ReadOnlyOperationalAdmin)
admin.site.register(PositionedPrintTemplate, ReadOnlyOperationalAdmin)
admin.site.register(PositionedPrintField, ReadOnlyOperationalAdmin)


class VehicleColorInline(admin.TabularInline):
    model = VehicleColor
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(VehicleModel)
class VehicleModelAdmin(ReadOnlyOperationalAdmin):
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
        "active",
    )
    list_filter = ("energy_type", "active")
    search_fields = ("brand", "name", "model_number")
    inlines = [VehicleColorInline]


@admin.register(VehicleInventory)
class VehicleInventoryAdmin(ReadOnlyOperationalAdmin):
    list_display = (
        "identifier",
        "vehicle_model",
        "color",
        "current_dealer",
        "status",
    )
    list_filter = ("status", "current_dealer", "vehicle_model")
    search_fields = ("engine_number", "frame_number")


@admin.register(VehiclePriceVersion)
class VehiclePriceVersionAdmin(ReadOnlyOperationalAdmin):
    list_display = (
        "vehicle_model",
        "suggested_price",
        "suggested_price_includes_registration",
        "cash_price",
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
class AccessoryProductAdmin(ReadOnlyOperationalAdmin):
    list_display = ("name", "sale_price", "labor_fee", "cost", "active")
    list_filter = ("active",)
    search_fields = ("name", "note")


@admin.register(VehicleInventoryHistory)
class VehicleInventoryHistoryAdmin(ReadOnlyOperationalAdmin):
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
class VehicleSettlementCostRuleAdmin(ReadOnlyOperationalAdmin):
    list_display = (
        "vehicle_model",
        "amount",
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


@admin.register(VehicleIncentiveRule)
class VehicleIncentiveRuleAdmin(ReadOnlyOperationalAdmin):
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
    can_delete = False
    readonly_fields = ("uploaded_by", "created_at", "updated_at")


class PaymentRecordInline(admin.TabularInline):
    model = PaymentRecord
    extra = 0
    can_delete = False
    readonly_fields = ("confirmed_by", "confirmed_at", "created_at", "updated_at")


class SubsidyDocumentInline(admin.TabularInline):
    model = SubsidyDocument
    extra = 0
    can_delete = False
    readonly_fields = ("uploaded_by", "created_at", "updated_at")


@admin.register(SalesOrder)
class SalesOrderAdmin(ReadOnlyOperationalAdmin):
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
    readonly_fields = (
        "id_front",
        "id_back",
        "refund_proof",
        "signed_contract",
        "privacy_consent",
    )

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(OrderOperationsProfile)
class OrderOperationsProfileAdmin(ReadOnlyOperationalAdmin):
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
