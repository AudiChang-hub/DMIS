"""訂單「附件」分頁：把這張訂單的所有檔案集中列出，方便預覽與下載（使用者 2026-10-13）。

只列出目前使用者有權開啟的檔案；網址沿用各檔案原本受權限保護的下載路由。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from django.urls import resolve, reverse

PREVIEW_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".pdf"}


@dataclass(frozen=True)
class OrderFile:
    label: str
    name: str
    url: str
    uploaded_at: datetime | None = None
    uploaded_by: str = ""

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
        return url and OrderFile(label, Path(field_file.name).name, url, **extra)

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
        and OrderFile(attachment.get_kind_display(), attachment.name, url, attachment.created_at)
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
            document.created_at, document.uploaded_by,
        )
        for document in order.registration_documents.all()
        if document.file
    ])
    group("補助文件", [
        (url := _allowed(policy, "subsidy_document_file", [document.pk]))
        and OrderFile(
            document.name or document.get_document_type_display(), Path(document.file.name).name, url,
            document.created_at, document.uploaded_by,
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
