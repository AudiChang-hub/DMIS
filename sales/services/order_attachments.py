"""訂單「附件」分頁：把這張訂單的所有檔案集中列出，方便預覽與下載（使用者 2026-10-13）。

只列出目前使用者有權開啟的檔案；網址沿用各檔案原本受權限保護的下載路由。
"""

from __future__ import annotations

import logging
import re
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from django.urls import resolve, reverse

logger = logging.getLogger(__name__)

PREVIEW_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".pdf"}
# 本身已壓縮的格式直接存入 ZIP，不再壓縮，打包大量照片時才不會拖慢。
STORED_EXTENSIONS = PREVIEW_EXTENSIONS | {
    ".heic", ".heif", ".gif", ".zip", ".7z", ".rar", ".gz",
    ".docx", ".xlsx", ".pptx", ".odt", ".ods", ".mp3", ".m4a", ".mp4", ".mov",
}


@dataclass(frozen=True)
class OrderFile:
    label: str
    name: str
    url: str
    uploaded_at: datetime | None = None
    uploaded_by: str = ""
    file: object = field(default=None, compare=False, repr=False)

    @property
    def extension(self):
        return Path(self.name).suffix.lower().removeprefix(".").upper() or "檔案"

    @property
    def is_preview_type(self):
        return Path(self.name).suffix.lower() in PREVIEW_EXTENSIONS


def _allowed(policy, route, args):
    url = reverse(route, args=args)
    return url if policy.route(route, kwargs=resolve(url).kwargs) else None


def collect_order_file_groups(order, request):
    """依類別分組的既有訂單檔案（其他附件另行處理）；空的分組不列出。"""
    from sales.access.services import policy_for

    policy = policy_for(request)
    groups = []

    def group(title, items):
        items = [item for item in items if item]
        if items:
            groups.append({"title": title, "files": items})

    def media(label, model_name, pk, field_name, field_file, **extra):
        if not field_file or not field_file.name:
            return None
        url = _allowed(policy, "protected_media", [model_name, pk, field_name])
        return url and OrderFile(label, Path(field_file.name).name, url, file=field_file, **extra)

    group("簽署文件", [
        media("訂購合約", "order", order.pk, "signed_contract", order.signed_contract),
        media("個資同意書", "order", order.pk, "privacy_consent", order.privacy_consent),
    ])
    group("車主證件", [
        media("證件正面", "order", order.pk, "id_front", order.id_front),
        media("證件反面", "order", order.pk, "id_back", order.id_back),
    ])
    group("下訂附件", [
        (url := _allowed(policy, "order_intake_attachment", [attachment.pk]))
        and OrderFile(attachment.get_kind_display(), attachment.name, url, attachment.created_at, file=attachment.file)
        for attachment in order.intake_attachments.order_by("created_at", "pk")
    ])
    group("收款證明", [
        media(
            f"{record.item_name or '收款'}" + (f"（{record.received_on:%Y/%m/%d}）" if record.received_on else ""),
            "payment", record.pk, "proof", record.proof, uploaded_at=record.created_at,
        )
        for record in order.payment_records.exclude(proof="").order_by("pk")
    ])
    group("領牌文件", [
        (url := _allowed(policy, "registration_document_file", [document.pk]))
        and OrderFile(
            document.display_name, Path(document.file.name).name, url,
            document.created_at, document.uploaded_by, document.file,
        )
        for document in order.registration_documents.all()
        if document.file
    ])
    group("補助文件", [
        (url := _allowed(policy, "subsidy_document_file", [document.pk]))
        and OrderFile(
            document.name or document.get_document_type_display(), Path(document.file.name).name, url,
            document.created_at, document.uploaded_by, document.file,
        )
        for document in order.subsidy_documents.all()
        if document.file
    ])
    from sales.models import DeliveryRecord
    delivery = DeliveryRecord.objects.filter(order=order).first()
    group("交車與退款", [
        delivery and media("交車照片", "delivery", delivery.pk, "handover_photo", delivery.handover_photo),
        media("退款證明", "order", order.pk, "refund_proof", order.refund_proof),
    ])
    return groups


def _zip_part(text, limit=80):
    cleaned = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", str(text)).strip(" .")
    return cleaned[:limit] or "檔案"


def zip_entries(order, request):
    """全部下載要放進 ZIP 的檔案：(資料夾, 檔名, 檔案)；只含目前使用者有權開啟的檔案。"""
    from sales.access.services import policy_for

    policy = policy_for(request)
    entries = [
        ("其他附件", attachment.name, attachment.file)
        for attachment in order.other_attachments.all()
        if attachment.file and _allowed(policy, "order_attachment_file", [attachment.pk])
    ]
    for group in collect_order_file_groups(order, request):
        for item in group["files"]:
            suffix = Path(item.name).suffix.lower()
            # 系統儲存檔名沒有意義，改用項目名稱；下訂附件保留原始檔名。
            name = item.name if group["title"] == "下訂附件" else f"{item.label}{suffix}"
            entries.append((group["title"], name, item.file))
    return entries


def write_order_files_zip(order, request, stream):
    """把訂單檔案依類別資料夾寫入 ZIP；回傳實際放入的檔案數。找不到的檔案列在說明檔。"""
    used, missing, count = set(), [], 0
    with zipfile.ZipFile(stream, "w", allowZip64=True) as archive:
        for folder, name, field_file in zip_entries(order, request):
            stem, suffix = Path(name).stem, Path(name).suffix
            base = f"{_zip_part(folder)}/{_zip_part(stem)}"
            path, number = f"{base}{suffix}", 1
            while path.lower() in used:
                number += 1
                path = f"{base}_{number}{suffix}"
            try:
                with field_file.storage.open(field_file.name, "rb") as source:
                    compress = zipfile.ZIP_STORED if suffix.lower() in STORED_EXTENSIONS else zipfile.ZIP_DEFLATED
                    info = zipfile.ZipInfo(path, date_time=datetime.now().timetuple()[:6])
                    info.compress_type = compress
                    with archive.open(info, "w", force_zip64=True) as target:
                        while chunk := source.read(1024 * 1024):
                            target.write(chunk)
            except (FileNotFoundError, OSError):
                logger.warning("order_zip_missing_file order=%s name=%s", order.pk, field_file.name)
                missing.append(f"{folder}／{name}")
                continue
            used.add(path.lower())
            count += 1
        if missing:
            archive.writestr(
                "缺少的檔案.txt",
                "以下檔案在系統中找不到，未放入壓縮檔：\n" + "\n".join(missing) + "\n",
            )
    return count
