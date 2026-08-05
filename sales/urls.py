from django.urls import path
from django.views.generic import RedirectView

from . import views


urlpatterns = [
    path("api/app-version/", views.app_version, name="app_version"),
    path("", views.dashboard, name="dashboard"),
    path("data/", views.data_maintenance, name="data_maintenance"),
    path("data/customers/", views.customer_list, name="customer_list"),
    path(
        "data/customers/<int:pk>/",
        views.customer_detail,
        name="customer_detail",
    ),
    path("orders/", views.order_list, name="order_list"),
    path("operations/", views.operations_report, name="operations_report"),
    path(
        "operations/reconciliation/",
        views.reconciliation_list,
        name="reconciliation_list",
    ),
    path(
        "operations/reconciliation/<int:pk>/update/",
        views.reconciliation_update,
        name="reconciliation_update",
    ),
    path(
        "operations/export/",
        views.operations_report_export,
        name="operations_report_export",
    ),
    path("orders/new/", views.order_create, name="order_create"),
    path("orders/drafts/save/", views.draft_save, name="draft_save"),
    path(
        "orders/drafts/<uuid:pk>/presence/",
        views.draft_presence,
        name="draft_presence",
    ),
    path("orders/drafts/<uuid:pk>/delete/", views.draft_delete, name="draft_delete"),
    path("orders/<int:pk>/", views.order_detail, name="order_detail"),
    path("orders/<int:pk>/edit/", views.order_edit, name="order_edit"),
    path(
        "orders/<int:pk>/operations/",
        views.order_operations,
        name="order_operations",
    ),
    path(
        "orders/<int:pk>/operations/reveal-secret/",
        views.order_secret_reveal,
        name="order_secret_reveal",
    ),
    path(
        "orders/<int:pk>/edit/presence/",
        views.order_edit_presence,
        name="order_edit_presence",
    ),
    path("orders/<int:pk>/contract/", views.contract_print, name="contract_print"),
    path(
        "orders/<int:pk>/privacy-consent/",
        views.privacy_consent_print,
        name="privacy_consent_print",
    ),
    path(
        "orders/<int:pk>/documents/",
        views.order_documents_print,
        name="order_documents_print",
    ),
    path(
        "orders/<int:pk>/contract/upload/",
        views.contract_upload,
        name="contract_upload",
    ),
    path(
        "orders/<int:pk>/privacy-consent/upload/",
        views.privacy_consent_upload,
        name="privacy_consent_upload",
    ),
    path(
        "orders/<int:pk>/allocate/",
        views.allocate_vehicle,
        name="allocate_vehicle",
    ),
    path(
        "orders/<int:pk>/reallocate/",
        views.reallocate_vehicle,
        name="reallocate_vehicle",
    ),
    path(
        "orders/<int:pk>/registration/save/",
        views.registration_save,
        name="registration_save",
    ),
    path(
        "orders/<int:pk>/registration/documents/upload/",
        views.registration_document_upload,
        name="registration_document_upload",
    ),
    path(
        "orders/<int:pk>/registration/documents/<int:document_pk>/delete/",
        views.registration_document_delete,
        name="registration_document_delete",
    ),
    path(
        "orders/<int:pk>/registration/complete/",
        views.registration_complete,
        name="registration_complete",
    ),
    path(
        "files/registration/<int:document_pk>/",
        views.registration_document_file,
        name="registration_document_file",
    ),
    path(
        "orders/<int:pk>/subsidy/documents/upload/",
        views.subsidy_document_upload,
        name="subsidy_document_upload",
    ),
    path(
        "orders/<int:pk>/subsidy/update/",
        views.subsidy_data_update,
        name="subsidy_data_update",
    ),
    path(
        "orders/<int:pk>/subsidy/ocr-decision/",
        views.subsidy_ocr_decision,
        name="subsidy_ocr_decision",
    ),
    path(
        "orders/<int:pk>/subsidy/documents/<int:document_pk>/delete/",
        views.subsidy_document_delete,
        name="subsidy_document_delete",
    ),
    path(
        "files/subsidy/<int:document_pk>/",
        views.subsidy_document_file,
        name="subsidy_document_file",
    ),
    path("data/inventory/", views.inventory_list, name="inventory_list"),
    path(
        "data/vehicle-models/",
        views.vehicle_model_list,
        name="vehicle_model_list",
    ),
    path(
        "data/vehicle-models/new/",
        views.vehicle_model_create,
        name="vehicle_model_create",
    ),
    path(
        "data/vehicle-models/<int:pk>/edit/",
        views.vehicle_model_edit,
        name="vehicle_model_edit",
    ),
    path(
        "data/accessories/",
        views.accessory_product_list,
        name="accessory_product_list",
    ),
    path(
        "data/accessories/new/",
        views.accessory_product_create,
        name="accessory_product_create",
    ),
    path(
        "data/accessories/<int:pk>/edit/",
        views.accessory_product_edit,
        name="accessory_product_edit",
    ),
    path(
        "data/settlement-costs/",
        views.settlement_cost_rule_list,
        name="settlement_cost_rule_list",
    ),
    path(
        "data/settlement-costs/new/",
        views.settlement_cost_rule_create,
        name="settlement_cost_rule_create",
    ),
    path(
        "data/settlement-costs/<int:pk>/edit/",
        views.settlement_cost_rule_edit,
        name="settlement_cost_rule_edit",
    ),
    path(
        "data/settlement-costs/<int:pk>/delete/",
        views.settlement_cost_rule_delete,
        name="settlement_cost_rule_delete",
    ),
    path(
        "data/incentive-rules/",
        views.incentive_rule_list,
        name="incentive_rule_list",
    ),
    path(
        "data/incentive-rules/new/",
        views.incentive_rule_create,
        name="incentive_rule_create",
    ),
    path(
        "data/incentive-rules/<int:pk>/edit/",
        views.incentive_rule_edit,
        name="incentive_rule_edit",
    ),
    path(
        "data/incentive-rules/<int:pk>/delete/",
        views.incentive_rule_delete,
        name="incentive_rule_delete",
    ),
    path("data/inventory/new/", views.inventory_create, name="inventory_create"),
    path(
        "data/inventory/quick-entry/",
        views.inventory_quick_create,
        name="inventory_quick_create",
    ),
    path(
        "data/inventory/<int:pk>/edit/",
        views.inventory_edit,
        name="inventory_edit",
    ),
    path(
        "inventory/",
        RedirectView.as_view(pattern_name="inventory_list", permanent=False),
    ),
    path(
        "inventory/new/",
        RedirectView.as_view(pattern_name="inventory_create", permanent=False),
    ),
    path(
        "inventory/quick-entry/",
        RedirectView.as_view(pattern_name="inventory_quick_create", permanent=False),
    ),
    path(
        "inventory/<int:pk>/edit/",
        RedirectView.as_view(pattern_name="inventory_edit", permanent=False),
    ),
    path(
        "master/vehicle-models/",
        RedirectView.as_view(pattern_name="vehicle_model_list", permanent=False),
    ),
    path(
        "master/vehicle-models/new/",
        RedirectView.as_view(pattern_name="vehicle_model_create", permanent=False),
    ),
    path(
        "master/vehicle-models/<int:pk>/edit/",
        RedirectView.as_view(pattern_name="vehicle_model_edit", permanent=False),
    ),
    path("api/colors/", views.vehicle_colors, name="vehicle_colors"),
    path("api/sources/", views.sales_sources, name="sales_sources"),
    path("api/id-card-ocr/", views.id_card_ocr, name="id_card_ocr"),
    path(
        "api/id-card-ocr/<uuid:job_id>/",
        views.id_card_ocr_status,
        name="id_card_ocr_status",
    ),
    path(
        "api/id-card-ocr/<uuid:job_id>/invalidate/",
        views.id_card_ocr_invalidate,
        name="id_card_ocr_invalidate",
    ),
    path(
        "files/<str:model_name>/<str:pk>/<str:field_name>/",
        views.protected_media,
        name="protected_media",
    ),
]
