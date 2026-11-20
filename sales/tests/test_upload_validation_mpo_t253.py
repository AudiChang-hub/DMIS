"""T-253（使用者 2026-11-20「iphone上傳的會是jpeg檔，結果不支援這個格式」）：

iPhone 相機拍的 JPEG 常在檔尾多帶一張附屬影像（MPF，例如 HDR 增益圖）。這種檔案仍是 JPEG（FFD8 開頭、
瀏覽器與相簿都當 JPEG），但 Pillow 會把格式報成 "MPO"；Django 的 ImageField 也因此把 content_type 改成 image/mpo。
共用的圖片驗證只認 "JPEG" 與 image/jpeg，於是證件照、辨識、自動偵測都回「圖片內容與副檔名不符」或
「檔案類型與副檔名不符」。全部用程式產生的合成圖。
"""
import io

from django import forms
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase
from PIL import Image

from sales.services.upload_validation import validate_document_upload, validate_image_upload


def iphone_style_jpeg():
    """主影像＋一張附屬影像的 JPEG（Pillow 存成 MPO，檔頭仍是 JPEG）。"""
    main = Image.new("RGB", (64, 48), (200, 180, 160))
    gain_map = Image.new("RGB", (32, 24), (128, 128, 128))
    output = io.BytesIO()
    main.save(output, "MPO", save_all=True, append_images=[gain_map])
    return output.getvalue()


class IphoneJpegUploadTests(SimpleTestCase):
    def test_fixture_is_a_jpeg_that_pillow_calls_mpo(self):
        data = iphone_style_jpeg()
        self.assertEqual(data[:2], b"\xff\xd8")
        self.assertEqual(Image.open(io.BytesIO(data)).format, "MPO")

    def test_raw_upload_from_browser_is_accepted(self):
        # 辨識（id_card_ocr）與自動偵測直接驗 request.FILES：瀏覽器送的是 image/jpeg。
        for name in ("image.jpg", "IMG_0001.JPEG"):
            with self.subTest(name=name):
                upload = SimpleUploadedFile(name, iphone_style_jpeg(), content_type="image/jpeg")
                self.assertIs(validate_image_upload(upload), upload)
                self.assertIs(validate_document_upload(upload), upload)

    def test_form_upload_after_image_field_is_accepted(self):
        # 證件照欄位先經過 Django ImageField，content_type 會被改成 image/mpo。
        upload = forms.ImageField().clean(SimpleUploadedFile("image.jpg", iphone_style_jpeg(), content_type="image/jpeg"))
        self.assertEqual(upload.content_type, "image/mpo")
        self.assertIs(validate_image_upload(upload), upload)

    def test_mpo_content_is_still_rejected_under_non_jpeg_extension(self):
        upload = SimpleUploadedFile("photo.png", iphone_style_jpeg(), content_type="image/png")
        with self.assertRaises(forms.ValidationError):
            validate_image_upload(upload)
