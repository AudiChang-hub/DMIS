from django.urls import path

from . import views


urlpatterns = [
    path("api/app-version/", views.app_version, name="app_version"),
    path("", views.dashboard, name="dashboard"),
    path("orders/", views.order_list, name="order_list"),
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
    path("inventory/", views.inventory_list, name="inventory_list"),
    path("inventory/new/", views.inventory_create, name="inventory_create"),
    path("api/colors/", views.vehicle_colors, name="vehicle_colors"),
    path("api/sources/", views.sales_sources, name="sales_sources"),
    path("api/id-card-ocr/", views.id_card_ocr, name="id_card_ocr"),
    path(
        "files/<str:model_name>/<str:pk>/<str:field_name>/",
        views.protected_media,
        name="protected_media",
    ),
]
