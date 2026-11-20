"""T-260（使用者 2026-11-20「選車圖片一起修」）：選車／車色圖片也要收 iPhone 相機拍的 JPEG。

iPhone 相機的 JPEG 常帶一張附屬影像（MPF），Pillow 把格式報成 "MPO"（見 T-253 c3c16bc9）。選車圖片的檢查
只認 JPEG／PNG／WebP 三種格式名稱，於是直接拍照上傳會被回「請使用 8 MB 以內 JPEG、PNG 或 WebP 圖片」。
全部用程式產生的合成圖。
"""
import io
from types import SimpleNamespace

from django import forms
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase
from PIL import Image

from sales.catalog_views import CatalogForm, checked_upload


def iphone_style_jpeg():
    main = Image.new("RGB", (64, 48), (200, 180, 160))
    output = io.BytesIO()
    main.save(output, "MPO", save_all=True, append_images=[Image.new("RGB", (32, 24), (128, 128, 128))])
    return output.getvalue()


def decoded_upload(name="image.jpg"):
    return forms.ImageField().clean(SimpleUploadedFile(name, iphone_style_jpeg(), content_type="image/jpeg"))


class CatalogIphoneJpegTests(SimpleTestCase):
    def test_photo_board_and_color_uploads_accept_iphone_jpeg(self):
        upload = checked_upload(decoded_upload())
        self.assertTrue(upload.name.endswith(".jpg"))

    def test_catalog_main_image_accepts_iphone_jpeg(self):
        form = SimpleNamespace(cleaned_data={"image": decoded_upload()})
        upload = CatalogForm.clean_image(form)
        self.assertTrue(upload.name.endswith(".jpg"))

    def test_other_formats_still_rejected(self):
        gif = io.BytesIO()
        Image.new("RGB", (8, 8)).save(gif, "GIF")
        upload = forms.ImageField().clean(SimpleUploadedFile("a.gif", gif.getvalue(), content_type="image/gif"))
        with self.assertRaises(forms.ValidationError):
            checked_upload(upload)
        with self.assertRaises(forms.ValidationError):
            CatalogForm.clean_image(SimpleNamespace(cleaned_data={"image": upload}))
