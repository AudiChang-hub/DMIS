import io
import socket
import tempfile
from unittest.mock import patch

from django.test import TestCase, SimpleTestCase, override_settings
from django.urls import reverse
from PIL import Image

from sales.models import UserAccountAuditLog
from sales.services import remote_image
from sales.services.remote_image import MAX_BYTES, RemoteImageError, fetch_image
from sales.tests import test_catalog_color_list as color_fixtures

URL = "https://www.e-moving.com.tw/emwspublished/C0013/28_20240712163321.jpg"


def image_bytes(fmt="JPEG"):
    data = io.BytesIO()
    Image.new("RGB", (16, 10), "steelblue").save(data, fmt)
    return data.getvalue()


class FakeResponse:
    def __init__(self, body=b"", headers=None, chunk=64 * 1024):
        self.body, self.headers, self.chunk, self.closed = body, headers or {}, chunk, False

    def read(self, size):
        part, self.body = self.body[:min(size, self.chunk)], self.body[min(size, self.chunk):]
        return part

    def close(self):
        self.closed = True


def addr(*ips):
    return [(socket.AF_INET6 if ":" in ip else socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443)) for ip in ips]


def ok(body=None, content_type="image/jpeg", **headers):
    body = image_bytes() if body is None else body
    headers = {"Content-Type": content_type, **headers}
    return 200, headers, FakeResponse(body, headers)


class RemoteImageServiceTests(SimpleTestCase):
    def fetch(self, responses, ips=("93.184.216.34",), url=URL):
        responses = list(responses)
        with patch.object(remote_image.socket, "getaddrinfo", return_value=addr(*ips)) as resolver, \
                patch.object(remote_image, "request", side_effect=responses) as requester:
            try:
                return fetch_image(url), resolver, requester
            except RemoteImageError as error:
                return error, resolver, requester

    def test_success_returns_verified_file_with_random_name(self):
        result, _, requester = self.fetch([ok(content_type="image/jpeg; charset=binary")])
        self.assertRegex(result.name, r"^[0-9a-f]{32}\.jpg$")
        self.assertEqual(result.read()[:3], b"\xff\xd8\xff")
        scheme, host, port, path, address = requester.call_args.args
        self.assertEqual((scheme, host, port, address), ("https", "www.e-moving.com.tw", 443, "93.184.216.34"))
        self.assertEqual(path, "/emwspublished/C0013/28_20240712163321.jpg")
        for fmt, ext, ctype in (("PNG", "png", "image/png"), ("WEBP", "webp", "image/webp")):
            result, *_ = self.fetch([ok(image_bytes(fmt), ctype)])
            self.assertTrue(result.name.endswith(ext))

    def test_too_large_by_header_or_stream_is_aborted(self):
        error, *_ = self.fetch([ok(b"x", **{"Content-Length": str(MAX_BYTES + 1)})])
        self.assertIn("8 MB", str(error))
        stream = FakeResponse(b"\xff" * (MAX_BYTES + 1024 * 1024))
        error, *_ = self.fetch([(200, {"Content-Type": "image/jpeg"}, stream)])
        self.assertIn("8 MB", str(error))
        self.assertTrue(stream.closed)
        self.assertGreater(len(stream.body), 0)  # 超過即中止，不讀完整份

    def test_wrong_content_type_or_fake_image_is_rejected(self):
        for response in (ok(content_type="text/html"), ok(content_type="image/svg+xml"),
                         ok(b"<html>not image</html>", "image/jpeg"), ok(image_bytes("GIF"), "image/png"),
                         ok(b"", "image/png")):
            error, *_ = self.fetch([response])
            self.assertIsInstance(error, RemoteImageError)
        error, *_ = self.fetch([(404, {"Content-Type": "text/html"}, FakeResponse())])
        self.assertIn("HTTP 404", str(error))

    def test_internal_and_reserved_addresses_are_blocked_before_connecting(self):
        for ips in (("127.0.0.1",), ("10.1.2.3",), ("192.168.1.10",), ("172.16.0.5",), ("169.254.169.254",),
                    ("100.64.0.1",), ("0.0.0.0",), ("::1",), ("fe80::1",), ("fc00::1",), ("::ffff:127.0.0.1",),
                    ("93.184.216.34", "10.0.0.1"), ("240.0.0.1",), ("224.0.0.1",)):
            error, _, requester = self.fetch([ok()], ips=ips)
            self.assertIn("內部網路", str(error), ips)
            requester.assert_not_called()

    def test_only_http_https_on_default_ports(self):
        for url in ("file:///etc/passwd", "ftp://example.com/a.jpg", "gopher://example.com/", "javascript:alert(1)",
                    "https://example.com:8443/a.jpg", "http://user:pw@example.com/a.jpg", "https:///a.jpg", "not a url"):
            error, resolver, requester = self.fetch([ok()], url=url)
            self.assertIsInstance(error, RemoteImageError, url)
            resolver.assert_not_called()
            requester.assert_not_called()

    def test_redirects_are_rechecked_each_hop(self):
        to_metadata = (302, {"Location": "http://169.254.169.254/latest/meta-data"}, FakeResponse())
        with patch.object(remote_image.socket, "getaddrinfo",
                          side_effect=[addr("93.184.216.34"), addr("169.254.169.254")]), \
                patch.object(remote_image, "request", side_effect=[to_metadata, ok()]) as requester:
            with self.assertRaisesMessage(RemoteImageError, "內部網路"):
                fetch_image(URL)
        self.assertEqual(requester.call_count, 1)
        error, *_ = self.fetch([(301, {"Location": "file:///etc/passwd"}, FakeResponse())])
        self.assertIn("http", str(error))
        relative = (302, {"Location": "/cdn/a.jpg"}, FakeResponse())
        result, _, requester = self.fetch([relative, ok()])
        self.assertTrue(result.name.endswith(".jpg"))
        self.assertEqual(requester.call_args.args[3], "/cdn/a.jpg")
        loop = [(302, {"Location": URL}, FakeResponse())] * 5
        error, *_ = self.fetch(loop)
        self.assertIn("重新導向次數過多", str(error))

    def test_timeouts_and_connection_errors_are_reported(self):
        for exc, text in ((socket.timeout("timed out"), "逾時"), (TimeoutError(), "逾時"),
                          (ConnectionRefusedError(), "無法連線"), (remote_image.ssl.SSLError(), "憑證")):
            error, *_ = self.fetch([exc])
            self.assertIn(text, str(error))
        with patch.object(remote_image.time, "monotonic", side_effect=[0, 0, remote_image.TOTAL_TIMEOUT + 1]):
            error, *_ = self.fetch([ok()])
        self.assertIn("逾時", str(error))
        with patch.object(remote_image.socket, "getaddrinfo", side_effect=socket.gaierror()):
            with self.assertRaisesMessage(RemoteImageError, "找不到這個網站"):
                fetch_image(URL)

    def test_connection_is_pinned_to_checked_address_with_timeout(self):
        with patch.object(remote_image.socket, "create_connection", side_effect=OSError("stop")) as connect:
            for scheme, cls in (("http", remote_image.PinnedHTTPConnection), ("https", remote_image.PinnedHTTPSConnection)):
                connection = cls("www.e-moving.com.tw", "93.184.216.34", port=443, timeout=remote_image.CONNECT_TIMEOUT)
                with self.assertRaises(OSError):
                    connection.connect()
                connect.assert_called_with(("93.184.216.34", 443), remote_image.CONNECT_TIMEOUT)


class CatalogRemoteImageViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        color_fixtures.CatalogColorListTests.setUpTestData.__func__(cls)

    image = color_fixtures.CatalogColorListTests.image

    def setUp(self):
        self.client.force_login(self.root)
        self.url = reverse("catalog_edit", args=[self.model.pk])
        self.payload = {"expected_revision": 0, "description": "更新介紹", "position": 0}
        media = tempfile.TemporaryDirectory()
        self.addCleanup(media.cleanup)
        settings = override_settings(MEDIA_ROOT=media.name)
        settings.enable()
        self.addCleanup(settings.disable)

    def test_page_offers_upload_or_link_for_each_color(self):
        response = self.client.get(self.url)
        for color in (self.gray, self.white):
            self.assertContains(response, f'name="color_url_{color.pk}"')
            self.assertContains(response, f'name="source_color_image_{color.pk}" value="url"')
        self.assertContains(response, "</svg>貼上連結</span>", count=2)
        self.assertContains(response, 'referrerpolicy="no-referrer"')

    def test_link_is_downloaded_saved_and_audited(self):
        with patch("sales.catalog_views.fetch_image", return_value=remote_image.ContentFile(image_bytes(), "a" * 32 + ".jpg")) as fetch:
            response = self.client.post(self.url, {**self.payload, f"color_url_{self.gray.pk}": f"  {URL} "})
        self.assertRedirects(response, self.url, fetch_redirect_response=False)
        fetch.assert_called_once_with(URL)
        self.gray.refresh_from_db()
        self.assertTrue(self.gray.catalog_image.name.endswith(".jpg"))
        audit = UserAccountAuditLog.objects.filter(metadata__model_id=self.model.pk).latest("pk")
        self.assertEqual(audit.metadata["color_image_urls"], {str(self.gray.pk): URL})
        page = self.client.get(reverse("catalog_detail", args=[self.model.pk]), {"color": self.gray.pk})
        self.assertContains(page, reverse("catalog_color_image", args=[self.model.pk, self.gray.pk]))

    def test_link_and_file_together_or_with_remove_is_rejected_without_download(self):
        with patch("sales.catalog_views.fetch_image") as fetch:
            response = self.client.post(self.url, {**self.payload, f"color_url_{self.gray.pk}": URL,
                                                   f"color_image_{self.gray.pk}": self.image()})
            self.assertContains(response, "請擇一：上傳檔案或貼上圖片連結。")
            self.gray.catalog_image = "catalog/old.png"
            self.gray.save()
            response = self.client.post(self.url, {**self.payload, f"color_url_{self.gray.pk}": URL,
                                                   f"color_remove_{self.gray.pk}": "on"})
            self.assertContains(response, "同一車色不可同時貼上連結與移除圖片。")
            response = self.client.post(self.url, {**self.payload, f"color_url_{self.gray.pk}": "ftp://x.test/a.jpg"})
            self.assertContains(response, "只接受 http:// 或 https://")
        fetch.assert_not_called()
        self.gray.refresh_from_db()
        self.assertEqual(self.gray.catalog_image.name, "catalog/old.png")

    def test_failed_link_keeps_url_and_error_while_other_colors_save(self):
        with patch("sales.catalog_views.fetch_image", side_effect=RemoteImageError("這個連結指向內部網路或保留位址，基於安全不能下載。")):
            response = self.client.post(self.url, {**self.payload, f"color_url_{self.gray.pk}": "http://10.0.0.1/a.jpg",
                                                   f"color_image_{self.white.pk}": self.image()})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "這個連結指向內部網路或保留位址", count=1)
        self.assertContains(response, 'value="http://10.0.0.1/a.jpg"')
        self.assertContains(response, "灰 的圖片連結無法下載")
        self.gray.refresh_from_db(); self.white.refresh_from_db()
        self.assertFalse(self.gray.catalog_image)
        self.assertTrue(self.white.catalog_image)
        form = response.context["form"]
        self.assertEqual(form["expected_revision"].value(), 1)
        self.assertEqual(self.client.post(self.url, {**self.payload, "expected_revision": 1}).status_code, 302)
