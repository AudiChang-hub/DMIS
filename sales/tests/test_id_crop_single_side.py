"""T-194：只上傳一面證件或重開草稿時，卡片要馬上自動裁切轉正（不必等兩面都上傳才辨識）。"""
import shutil
import tempfile

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from django.urls import reverse

from sales.models import OrderDraft
from sales.tests import id_card_synthetic as synthetic


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="t194-media-"))
class SingleSideCropTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(settings.MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="t194", password="test-pass-123")
        self.client.force_login(self.user)

    def test_draft_with_only_front_photo_detects_card_on_load(self):
        draft = OrderDraft.objects.create(
            owner_account=self.user, created_by=self.user.username, data={"owner_type": "local"},
            id_front=ContentFile(synthetic.jpeg_bytes(synthetic.scene("front")), name="front.jpg"),
        )
        page = self.client.get(reverse("order_create"), {"draft": draft.pk}).content.decode()
        # 卡片顯示走「已存參數或自動偵測」的同一條路，單面照片也會觸發偵測。
        self.assertIn("dmisIdCrop.cardState", page)
        self.assertIn("ensureAutoCrop(fieldName)", page)
        # 只有正面時，偵測 API 用已存照片也能算出參數（不需要反面）。
        response = self.client.post(reverse("id_card_crop_detect"), {"side": "front", "source": f"draft:{draft.pk}"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["crop"]["mode"], "auto")

    def test_saved_photo_state_built_after_autosave_says_view_original(self):
        page = self.client.get(reverse("order_create")).content.decode()
        self.assertNotIn('<a target="_blank">查看</a>', page)
        self.assertIn('<a target="_blank">查看原圖</a>', page)
