from django.urls import path

from . import consumers


websocket_urlpatterns = [
    path("ws/orders/drafts/<uuid:draft_id>/", consumers.DraftCollaborationConsumer.as_asgi()),
]
