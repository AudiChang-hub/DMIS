"""T-198：已暫存區塊小字與伺服器樣板一致；車主類型切換時重算自動偵測的裁切。"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class CropFollowupTests(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_user(username="t198", password="test-pass-123"))

    def page(self):
        return self.client.get(reverse("order_create")).content.decode()

    def test_saved_photo_state_built_by_script_uses_same_hint_as_template(self):
        page = self.page()
        self.assertIn("<small>點卡片可調整裁切／旋轉</small></span>\n        <a target=\"_blank\">查看原圖</a>", page)
        self.assertNotIn("照片已安全保存，可繼續填寫", page)

    def test_owner_type_switch_recomputes_auto_crops(self):
        page = self.page()
        self.assertIn('ownerType.addEventListener("change", recropOnOwnerTypeChange)', page)
        self.assertIn("recropPlan(cropInput(fieldName).value)", page)
