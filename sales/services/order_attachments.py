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


# 「該上傳的文件」：各步驟的固定文件格集中在附件分頁上傳或歸類（使用者 2026-10-14 選 A＋B）。
# 上傳一律送到各步驟原本的處理，驗證、替換、處理紀錄與鎖定規則完全相同。
DOCUMENT_ACCEPT = "image/jpeg,image/png,image/webp,application/pdf"
SUBSIDY_ACCEPT = (
    "image/jpeg,image/png,image/webp,image/heic,image/heif,"
    "application/pdf,.doc,.docx,.odt,.xls,.xlsx,.ods,.txt,.csv"
)
DOCUMENT_EXTENSIONS = PREVIEW_EXTENSIONS
SUBSIDY_EXTENSIONS = PREVIEW_EXTENSIONS | {
    ".heic", ".heif", ".doc", ".docx", ".odt", ".xls", ".xlsx", ".ods", ".txt", ".csv",
}


@dataclass(frozen=True)
class DocumentSlot:
    key: str
    group: str
    label: str
    required: bool
    status: str
    done: bool
    route: str
    field_name: str
    document_type: str
    accept: str
    extensions: frozenset
    open: bool
    closed_note: str = ""
    view_url: str | None = None
    view_name: str = ""

    def accepts(self, filename):
        return Path(filename).suffix.lower() in self.extensions


def _signing_slot(order, policy, key, label, field_name, route):
    stored = getattr(order, field_name)
    if getattr(order, f"{field_name}_is_electronic"):
        status, done = "已電子簽署", True
    elif getattr(order, f"has_{field_name}"):
        status, done = "已上傳", True
    else:
        status, done = "缺少", False
    view_url = None
    if stored and stored.name:
        view_url = _allowed(policy, "protected_media", ["order", order.pk, field_name])
    return DocumentSlot(
        key=key, group="簽署文件", label=label, required=True, status=status, done=done,
        route=route, field_name=field_name, document_type="", accept=DOCUMENT_ACCEPT,
        extensions=frozenset(DOCUMENT_EXTENSIONS), open=True,
        view_url=view_url, view_name=Path(stored.name).name if stored else "",
    )


def document_slots(order, request, registration_rows=(), subsidy_rows=()):
    """附件分頁的文件格清單；registration_rows／subsidy_rows 沿用訂單頁已算好的列，顯示規則與原步驟一致。"""
    from sales.access.services import policy_for
    from sales.models import SalesOrder

    policy = policy_for(request)
    slots = []
    if order.needs_customer_signatures:
        slots.append(_signing_slot(order, policy, "contract", "訂購合約", "signed_contract", "contract_upload"))
        slots.append(_signing_slot(order, policy, "privacy", "個資同意書", "privacy_consent", "privacy_consent_upload"))

    locked_status = {SalesOrder.Status.COMPLETED, SalesOrder.Status.CANCELLED}
    if not order.allocated_vehicle_id:
        registration_open, registration_note = False, "配車後開放上傳"
    elif order.is_registration_complete or order.status in locked_status:
        registration_open, registration_note = False, "領牌已完成，文件已鎖定"
    else:
        registration_open, registration_note = True, ""
    for row in registration_rows:
        document = row["document"]
        slots.append(DocumentSlot(
            key=f"registration:{row['type']}", group="領牌文件", label=row["label"],
            required=row["required"], status="已上傳" if document else ("缺少" if row["required"] else "未上傳"),
            done=bool(document),
            route="registration_document_upload", field_name="file", document_type=row["type"],
            accept=DOCUMENT_ACCEPT, extensions=frozenset(DOCUMENT_EXTENSIONS),
            open=registration_open, closed_note=registration_note,
            view_url=document and _allowed(policy, "registration_document_file", [document.pk]),
            view_name=Path(document.file.name).name if document else "",
        ))

    if order.is_trade_in_subsidy:
        subsidy_open = order.can_manage_subsidy
        for row in subsidy_rows:
            document, evidence = row["document"], row.get("existing_evidence")
            if document:
                status, done = "已上傳", True
            elif evidence:
                status, done = "沿用下訂附件", True
            else:
                status, done = ("缺少" if row["required"] else "未上傳"), False
            slots.append(DocumentSlot(
                key=f"subsidy:{row['type']}", group="補助文件", label=row["label"],
                required=row["required"], status=status, done=done,
                route="subsidy_document_upload", field_name="file", document_type=row["type"],
                accept=SUBSIDY_ACCEPT, extensions=frozenset(SUBSIDY_EXTENSIONS),
                open=subsidy_open, closed_note="" if subsidy_open else "已取消訂單無法修改補助文件",
                view_url=document and _allowed(policy, "subsidy_document_file", [document.pk]),
                view_name=Path(document.file.name).name if document else "",
            ))
    return slots


def group_slots(slots):
    groups = {}
    for slot in slots:
        groups.setdefault(slot.group, []).append(slot)
    return [
        {
            "title": title,
            "slots": items,
            "missing": sum(1 for slot in items if slot.required and not slot.done),
            "closed_note": next((slot.closed_note for slot in items if not slot.open), ""),
        }
        for title, items in groups.items()
    ]


def classify_route(target):
    """「歸類到…」的目標 → (路由名稱, 檔案欄位, 文件類型, 顯示名稱)；未知目標回傳 None。"""
    from sales.models import RegistrationDocument, SubsidyDocument

    if target == "contract":
        return "contract_upload", "signed_contract", "", "訂購合約"
    if target == "privacy":
        return "privacy_consent_upload", "privacy_consent", "", "個資同意書"
    prefix, _, document_type = target.partition(":")
    if prefix == "registration" and document_type in set(RegistrationDocument.active_fixed_document_types()):
        label = dict(RegistrationDocument.DocumentType.choices)[document_type]
        return "registration_document_upload", "file", document_type, f"領牌文件／{label}"
    if prefix == "subsidy" and document_type in SubsidyDocument.DocumentType.values:
        label = dict(SubsidyDocument.DocumentType.choices)[document_type]
        return "subsidy_document_upload", "file", document_type, f"補助文件／{label}"
    return None
