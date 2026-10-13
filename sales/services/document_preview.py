"""判斷已儲存的 PDF 能否在網頁內預覽。

可解析就預覽，不能解析就只提供下載（使用者 2026-10-13）。結果以儲存檔名快取；
替換檔案時 storage 會產生新檔名，所以不必另外清快取。
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from django.core.cache import cache
from django.http import HttpResponse

from sales.services.upload_validation import DOCUMENT_MAX_BYTES, pdf_is_previewable

PREVIEW_HEADER = "X-Document-Preview"
_CACHE_SECONDS = 7 * 24 * 60 * 60

_PLACEHOLDER = """<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><title>無法預覽</title>
<style>html,body{height:100%;margin:0}body{display:grid;place-items:center;padding:8px;box-sizing:border-box;
font:14px/1.5 system-ui,sans-serif;text-align:center;color:#5b5550;background:#faf8f5}
@media(prefers-color-scheme:dark){body{color:#c9c2ba;background:#1c1a18}}</style>
<p>此 PDF 無法在網頁預覽<br>請下載後開啟</p></html>"""


def is_unpreviewable_pdf(field_file, filename: str = "") -> bool:
    name = filename or getattr(field_file, "name", "") or ""
    if Path(name).suffix.lower() != ".pdf" or not getattr(field_file, "name", ""):
        return False
    key = "pdf-previewable:" + hashlib.sha256(field_file.name.encode()).hexdigest()
    cached = cache.get(key)
    if cached is not None:
        return not cached
    try:
        with field_file.storage.open(field_file.name, "rb") as handle:
            data = handle.read(DOCUMENT_MAX_BYTES + 1)
    except (OSError, ValueError):
        return False
    previewable = len(data) <= DOCUMENT_MAX_BYTES and pdf_is_previewable(data)
    cache.set(key, previewable, _CACHE_SECONDS)
    return not previewable


def preview_unavailable_response() -> HttpResponse:
    """縮圖 iframe 收到這頁時顯示說明；前端看到標頭就改成下載卡片。"""
    response = HttpResponse(_PLACEHOLDER, content_type="text/html; charset=utf-8")
    response[PREVIEW_HEADER] = "unavailable"
    response["Cache-Control"] = "private, no-store, max-age=0"
    response["X-Content-Type-Options"] = "nosniff"
    response["X-Frame-Options"] = "SAMEORIGIN"
    response["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'self'"
    return response
