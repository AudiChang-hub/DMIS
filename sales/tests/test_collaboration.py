from asgiref.sync import async_to_sync
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.test import Client, TransactionTestCase, override_settings

from config.asgi import application
from sales.collaboration import merge_text
from sales.models import DraftFieldState, OrderDraft


TEST_CHANNEL_LAYERS = {
    "default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}
}


class TextMergeTests(TransactionTestCase):
    def test_merges_non_overlapping_changes(self):
        self.assertEqual(
            merge_text("新北市汐止區", "新北市汐止區福德路", "新北市南港區"),
            "新北市南港區福德路",
        )

    def test_rejects_ambiguous_same_position_changes(self):
        self.assertIsNone(merge_text("", "王小明", "陳小華"))


@override_settings(
    CHANNEL_LAYERS=TEST_CHANNEL_LAYERS,
    ALLOWED_HOSTS=["testserver"],
)
class DraftCollaborationTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.first_user = get_user_model().objects.create_user(
            username="first-editor", password="test-pass-123"
        )
        self.second_user = get_user_model().objects.create_user(
            username="second-editor", password="test-pass-123"
        )
        self.draft = OrderDraft.objects.create(
            data={"owner_name": ""},
            created_by=self.first_user.username,
        )

    def session_cookie(self, user):
        client = Client()
        client.force_login(user)
        return client.cookies["sessionid"].value

    def headers(self, user):
        session_id = self.session_cookie(user)
        return [
            (b"cookie", f"sessionid={session_id}".encode()),
            (b"origin", b"http://testserver"),
        ]

    def test_focus_sync_conflict_and_forced_resolution(self):
        first_headers = self.headers(self.first_user)
        second_headers = self.headers(self.second_user)
        async_to_sync(self.collaboration_scenario)(first_headers, second_headers)

        state = DraftFieldState.objects.get(
            draft=self.draft, field_key="owner_name"
        )
        self.assertEqual(state.value, "陳小華")
        self.assertEqual(state.version, 2)
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.data["owner_name"], "陳小華")

    async def collaboration_scenario(self, first_headers, second_headers):
        first = WebsocketCommunicator(
            application,
            f"/ws/orders/drafts/{self.draft.pk}/?client-first",
            headers=first_headers,
        )
        second = WebsocketCommunicator(
            application,
            f"/ws/orders/drafts/{self.draft.pk}/?client-second",
            headers=second_headers,
        )
        self.assertTrue((await first.connect())[0])
        self.assertTrue((await second.connect())[0])
        self.assertEqual((await first.receive_json_from())["type"], "snapshot")
        self.assertEqual((await second.receive_json_from())["type"], "snapshot")

        await first.send_json_to(
            {"type": "presence.focus", "field": "owner_name"}
        )
        await first.receive_json_from()
        focus = await second.receive_json_from()
        self.assertEqual(focus["type"], "presence.focus")
        self.assertEqual(focus["editing_by"], self.first_user.username)

        await first.send_json_to(
            {
                "type": "field.update",
                "field": "owner_name",
                "value": "王小明",
                "base_value": "",
                "base_version": 0,
                "kind": "text",
            }
        )
        first_update = await first.receive_json_from()
        second_update = await second.receive_json_from()
        self.assertEqual(first_update["version"], 1)
        self.assertEqual(second_update["value"], "王小明")

        await second.send_json_to(
            {
                "type": "field.update",
                "field": "owner_name",
                "value": "陳小華",
                "base_value": "",
                "base_version": 0,
                "kind": "text",
            }
        )
        conflict = await second.receive_json_from()
        self.assertEqual(conflict["type"], "field.conflict")
        self.assertEqual(conflict["server_value"], "王小明")

        await second.send_json_to(
            {
                "type": "field.update",
                "field": "owner_name",
                "value": "陳小華",
                "base_value": "王小明",
                "base_version": 1,
                "kind": "text",
                "force": True,
            }
        )
        await first.receive_json_from()
        resolved = await second.receive_json_from()
        self.assertEqual(resolved["type"], "field.updated")
        self.assertEqual(resolved["version"], 2)
        await first.disconnect()
        await second.disconnect()
