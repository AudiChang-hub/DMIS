import hashlib
import json
import re
from datetime import timedelta

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.db import transaction
from django.utils import timezone

from .collaboration import merge_text
from .models import DraftFieldPresence, DraftFieldState, OrderDraft


FIELD_KEY_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,200}$")
PRESENCE_TIMEOUT = timedelta(seconds=60)
MAX_VALUE_BYTES = 20_000


def _editor_color(identity):
    hue = int(hashlib.sha256(identity.encode()).hexdigest()[:6], 16) % 360
    return f"hsl({hue} 65% 42%)"


class DraftCollaborationConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        user = self.scope["user"]
        if not user.is_authenticated:
            await self.close(code=4401)
            return
        self.draft_id = str(self.scope["url_route"]["kwargs"]["draft_id"])
        self.group_name = f"draft_{self.draft_id.replace('-', '')}"
        self.client_id = self.scope["query_string"].decode()[:64]
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", self.client_id):
            await self.close(code=4400)
            return
        self.session_key = self.scope["session"].session_key or ""
        self.editor_name = user.get_full_name() or user.get_username()
        self.editor_color = _editor_color(f"{self.session_key}:{self.client_id}")
        if not await self._draft_exists():
            await self.close(code=4404)
            return

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        snapshot = await self._snapshot()
        await self.send_json({"type": "snapshot", **snapshot})

    async def disconnect(self, close_code):
        if not hasattr(self, "group_name"):
            return
        await self._clear_presence()
        await self.channel_layer.group_send(
            self.group_name,
            {
                "type": "collaboration.message",
                "payload": {
                    "type": "presence.leave",
                    "client_id": self.client_id,
                },
            },
        )
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive_json(self, content, **kwargs):
        message_type = content.get("type")
        if message_type == "presence.focus":
            field_key = content.get("field")
            if not self._valid_field_key(field_key):
                return
            await self._set_presence(field_key)
            await self._broadcast(
                {
                    "type": "presence.focus",
                    "field": field_key,
                    "client_id": self.client_id,
                    "editing_by": self.editor_name,
                    "color": self.editor_color,
                }
            )
        elif message_type == "presence.blur":
            await self._clear_presence()
            await self._broadcast(
                {"type": "presence.blur", "client_id": self.client_id}
            )
        elif message_type == "field.update":
            await self._update_field(content)
        elif message_type == "ping":
            await self._touch_presence()
            await self.send_json({"type": "pong"})

    async def _update_field(self, content):
        field_key = content.get("field")
        value = content.get("value")
        base_value = content.get("base_value", "")
        if not self._valid_field_key(field_key):
            return
        try:
            if len(json.dumps(value, ensure_ascii=False).encode()) > MAX_VALUE_BYTES:
                raise ValueError
            base_version = max(0, int(content.get("base_version", 0)))
        except (TypeError, ValueError):
            await self.send_json({"type": "field.error", "field": field_key})
            return

        result = await self._save_field(
            field_key=field_key,
            value=value,
            base_value=base_value,
            base_version=base_version,
            kind=content.get("kind", ""),
            force=content.get("force") is True,
        )
        if result["status"] == "conflict":
            await self.send_json(
                {
                    "type": "field.conflict",
                    "field": field_key,
                    "server_value": result["value"],
                    "server_version": result["version"],
                    "my_value": value,
                    "updated_by": result["updated_by"],
                }
            )
            return
        await self._broadcast(
            {
                "type": "field.updated",
                "field": field_key,
                "value": result["value"],
                "version": result["version"],
                "updated_by": self.editor_name,
                "client_id": self.client_id,
                "merged": result["status"] == "merged",
            }
        )

    async def _broadcast(self, payload):
        await self.channel_layer.group_send(
            self.group_name,
            {"type": "collaboration.message", "payload": payload},
        )

    async def collaboration_message(self, event):
        await self.send_json(event["payload"])

    @staticmethod
    def _valid_field_key(field_key):
        return isinstance(field_key, str) and FIELD_KEY_PATTERN.fullmatch(field_key)

    @database_sync_to_async
    def _draft_exists(self):
        return OrderDraft.objects.filter(pk=self.draft_id).exists()

    @database_sync_to_async
    def _snapshot(self):
        cutoff = timezone.now() - PRESENCE_TIMEOUT
        DraftFieldPresence.objects.filter(
            draft_id=self.draft_id, updated_at__lt=cutoff
        ).delete()
        fields = {
            state.field_key: {
                "value": state.value,
                "version": state.version,
                "updated_by": state.updated_by,
            }
            for state in DraftFieldState.objects.filter(draft_id=self.draft_id)
        }
        presences = [
            {
                "field": presence.field_key,
                "client_id": presence.client_id,
                "editing_by": presence.editing_by,
                "color": presence.color,
            }
            for presence in DraftFieldPresence.objects.filter(
                draft_id=self.draft_id, updated_at__gte=cutoff
            ).exclude(client_id=self.client_id)
        ]
        return {"fields": fields, "presences": presences}

    @database_sync_to_async
    def _set_presence(self, field_key):
        DraftFieldPresence.objects.update_or_create(
            draft_id=self.draft_id,
            session_key=self.session_key,
            client_id=self.client_id,
            defaults={
                "field_key": field_key,
                "editing_by": self.editor_name,
                "color": self.editor_color,
            },
        )

    @database_sync_to_async
    def _touch_presence(self):
        DraftFieldPresence.objects.filter(
            draft_id=self.draft_id,
            session_key=self.session_key,
            client_id=self.client_id,
        ).update(updated_at=timezone.now())

    @database_sync_to_async
    def _clear_presence(self):
        DraftFieldPresence.objects.filter(
            draft_id=self.draft_id,
            session_key=self.session_key,
            client_id=self.client_id,
        ).delete()

    @database_sync_to_async
    def _save_field(
        self, field_key, value, base_value, base_version, kind, force=False
    ):
        with transaction.atomic():
            draft = OrderDraft.objects.select_for_update().get(pk=self.draft_id)
            current_draft_value = draft.data.get(field_key, "")
            if isinstance(current_draft_value, list):
                current_draft_value = (
                    current_draft_value[-1] if current_draft_value else ""
                )
            state, _ = DraftFieldState.objects.select_for_update().get_or_create(
                draft=draft,
                field_key=field_key,
                defaults={"value": current_draft_value, "version": 0},
            )
            status = "updated"
            resolved_value = value
            if state.version != base_version and not force:
                if kind in {"text", "textarea"} and all(
                    isinstance(item, str)
                    for item in (base_value, state.value, value)
                ):
                    resolved_value = merge_text(base_value, state.value, value)
                    if resolved_value is not None:
                        status = "merged"
                if resolved_value is None or kind not in {"text", "textarea"}:
                    return {
                        "status": "conflict",
                        "value": state.value,
                        "version": state.version,
                        "updated_by": state.updated_by,
                    }
            if resolved_value == state.value:
                return {
                    "status": status,
                    "value": state.value,
                    "version": state.version,
                    "updated_by": state.updated_by,
                }
            state.value = resolved_value
            state.version += 1
            state.updated_by = self.editor_name
            state.save(update_fields=["value", "version", "updated_by", "updated_at"])
            draft_data = dict(draft.data)
            draft_data[field_key] = resolved_value
            draft.data = draft_data
            draft.updated_by = self.editor_name
            draft.save(update_fields=["data", "updated_by", "updated_at"])
            return {
                "status": status,
                "value": state.value,
                "version": state.version,
                "updated_by": state.updated_by,
            }
