"""從使用者貼上的網址下載展示圖片；只連公開網路位址，結果走與上傳相同的檢查。"""

import http.client
import io
import ipaddress
import socket
import ssl
import time
import uuid
from urllib.parse import urljoin, urlsplit

from django.core.files.base import ContentFile
from PIL import Image, UnidentifiedImageError

MAX_BYTES = 8 * 1024 * 1024
MAX_REDIRECTS = 3
CONNECT_TIMEOUT = 5
TOTAL_TIMEOUT = 20
ALLOWED_PORTS = {"http": 80, "https": 443}
ALLOWED_TYPES = {"image/jpeg", "image/pjpeg", "image/png", "image/webp"}
FORMAT_EXT = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}
USER_AGENT = "Mozilla/5.0 (compatible; DMIS-catalog-image/1.0)"


class RemoteImageError(Exception):
    """可直接顯示給使用者的中文錯誤。"""


def validate_url(url):
    """回傳 (scheme, host, port, path)；只接受預設埠的 http／https。"""
    try:
        parts = urlsplit(url.strip())
        port = parts.port
    except ValueError:
        raise RemoteImageError("圖片連結格式不正確，請重新貼上。") from None
    scheme = parts.scheme.lower()
    if scheme not in ALLOWED_PORTS:
        raise RemoteImageError("只接受 http:// 或 https:// 開頭的圖片連結。")
    if not parts.hostname or parts.username or parts.password:
        raise RemoteImageError("圖片連結格式不正確，請重新貼上。")
    if port not in (None, ALLOWED_PORTS[scheme]):
        raise RemoteImageError("圖片連結不可指定特殊連接埠。")
    path = parts.path or "/"
    if parts.query:
        path = f"{path}?{parts.query}"
    return scheme, parts.hostname, ALLOWED_PORTS[scheme], path


def public_address(address):
    ip = ipaddress.ip_address(address)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


def resolve(host, port):
    """解析主機並確認每個位址都是公開網路；回傳第一個可連線的位址。"""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError):
        raise RemoteImageError("找不到這個網站，請確認連結是否正確。") from None
    addresses = [info[4][0] for info in infos]
    if not addresses or not all(public_address(address) for address in addresses):
        raise RemoteImageError("這個連結指向內部網路或保留位址，基於安全不能下載。")
    return addresses[0]


class PinnedHTTPConnection(http.client.HTTPConnection):
    """連到已檢查的 IP，避免連線前 DNS 被改指向內網。"""

    def __init__(self, host, address, **kwargs):
        super().__init__(host, **kwargs)
        self.address = address

    def connect(self):
        self.sock = socket.create_connection((self.address, self.port), self.timeout)


class PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host, address, **kwargs):
        super().__init__(host, context=ssl.create_default_context(), **kwargs)
        self.address = address

    def connect(self):
        sock = socket.create_connection((self.address, self.port), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


def request(scheme, host, port, path, address):
    """送出單一 GET（不自動轉址）；回傳 (status, headers, response)。"""
    connection_class = PinnedHTTPSConnection if scheme == "https" else PinnedHTTPConnection
    connection = connection_class(host, address, port=port, timeout=CONNECT_TIMEOUT)
    connection.request("GET", path, headers={
        "User-Agent": USER_AGENT, "Accept": "image/webp,image/png,image/jpeg;q=0.9", "Accept-Encoding": "identity",
    })
    response = connection.getresponse()
    return response.status, response.headers, response


def read_limited(response, deadline):
    length = response.headers.get("Content-Length")
    if length and length.isdigit() and int(length) > MAX_BYTES:
        raise RemoteImageError("圖片超過 8 MB，請改用較小的圖片。")
    chunks, total = [], 0
    while True:
        if time.monotonic() > deadline:
            raise RemoteImageError("下載圖片逾時，請稍後再試或改用上傳檔案。")
        chunk = response.read(64 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_BYTES:
            raise RemoteImageError("圖片超過 8 MB，請改用較小的圖片。")
        chunks.append(chunk)
    if not total:
        raise RemoteImageError("連結回傳的是空檔案，請確認圖片網址。")
    return b"".join(chunks)


def verified_image(data):
    """用 Pillow 實際解碼確認格式；回傳以隨機檔名命名的 ContentFile。"""
    try:
        with Image.open(io.BytesIO(data)) as image:
            fmt = image.format
            image.verify()
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, Image.DecompressionBombError):
        raise RemoteImageError("連結內容不是有效的 JPEG、PNG 或 WebP 圖片。") from None
    if fmt not in FORMAT_EXT:
        raise RemoteImageError("連結內容不是有效的 JPEG、PNG 或 WebP 圖片。")
    return ContentFile(data, name=f"{uuid.uuid4().hex}.{FORMAT_EXT[fmt]}")


def fetch_image(url):
    """下載並驗證圖片；任何失敗都以 RemoteImageError 回報。"""
    deadline = time.monotonic() + TOTAL_TIMEOUT
    current = url.strip()
    for _ in range(MAX_REDIRECTS + 1):
        scheme, host, port, path = validate_url(current)
        address = resolve(host, port)
        try:
            status, headers, response = request(scheme, host, port, path, address)
            try:
                if status in {301, 302, 303, 307, 308}:
                    location = headers.get("Location")
                    if not location:
                        raise RemoteImageError("網站回傳了無效的重新導向。")
                    current = urljoin(current, location)
                    continue
                if status != 200:
                    raise RemoteImageError(f"網站回應錯誤（HTTP {status}），請確認連結可以直接開啟圖片。")
                content_type = (headers.get("Content-Type") or "").split(";")[0].strip().lower()
                if content_type not in ALLOWED_TYPES:
                    raise RemoteImageError("連結不是 JPEG、PNG 或 WebP 圖片，請貼上圖片本身的網址。")
                return verified_image(read_limited(response, deadline))
            finally:
                response.close()
        except RemoteImageError:
            raise
        except (socket.timeout, TimeoutError):
            raise RemoteImageError("下載圖片逾時，請稍後再試或改用上傳檔案。") from None
        except ssl.SSLError:
            raise RemoteImageError("無法建立安全連線（憑證錯誤），請改用上傳檔案。") from None
        except (OSError, http.client.HTTPException):
            raise RemoteImageError("無法連線到這個網站，請稍後再試或改用上傳檔案。") from None
    raise RemoteImageError("重新導向次數過多，請貼上圖片本身的網址。")
