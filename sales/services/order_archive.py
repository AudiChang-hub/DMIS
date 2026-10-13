"""訂單檔案同步到 NAS（使用者 2026-10-13 選方案 A：系統為正本，NAS 為自動整理的副本）。

資料夾：<根目錄>/DMIS訂單/<車型>/<年>/<月>/<車行>_<車主>_<車型>_<訂單編號>/
- 車型用機種名稱（不含年式）；年月依訂單成立日期（沒有時用訂單日期）；本店訂單的車行寫「馭盛」。
- 訂單內所有檔案（車輛訂購單、個資同意書、證件、收款證明、交車照片、領牌與補助文件、下訂附件）複製進去，
  以中文檔名命名；車主、車型或日期改了，資料夾跟著搬移改名。
- 只管理系統自己放進去的檔案（記在 OrderArchiveRecord.files）；人員手動放進資料夾的檔案不會被刪除。
- NAS 斷線或寫入失敗只記錄錯誤，不影響訂單操作；下次異動或補同步時再處理。
"""
import logging
import os
import re
import shutil
from pathlib import Path, PurePosixPath

import django_rq
from django.conf import settings
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

ARCHIVE_FOLDER = "DMIS訂單"
STORE_LABEL = "馭盛"
_INVALID = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')


def archive_root():
    root = getattr(settings, "ORDER_ARCHIVE_DIR", "") or ""
    return Path(root) if root else None


def _clean(text, limit=60):
    value = _INVALID.sub(" ", str(text or "")).strip().rstrip(".").strip()
    value = re.sub(r"\s+", " ", value)
    return value[:limit].strip() or "未填"


def _model_label(order):
    model = order.vehicle_model
    family = getattr(model, "family", None)
    return _clean(family.name if family else model.name, 40)


def _dealer_label(order):
    if order.source_type == order.SourceType.STORE or not order.source_id:
        return STORE_LABEL
    return _clean(order.source.name, 40)


def order_folder(order):
    """相對於根目錄的資料夾路徑（POSIX 形式，存到資料庫比對搬移用）。"""
    day = order.established_on or order.order_date or timezone.localdate(order.created_at)
    model = _model_label(order)
    leaf = "_".join([_dealer_label(order), _clean(order.owner_name, 40), model, order.number])
    return str(PurePosixPath(ARCHIVE_FOLDER, model, f"{day:%Y}", f"{day:%m}", leaf))


def _extension(field_file):
    return os.path.splitext(field_file.name)[1].lower() or ".bin"


def order_files(order):
    """回傳 [(檔名, FieldFile)]；同名時加序號。"""
    entries = []

    def add(label, field_file):
        if field_file and field_file.name:
            entries.append((label, field_file))

    add("車輛訂購單", order.signed_contract)
    add("個資同意書", order.privacy_consent)
    add("車主證件正面", order.id_front)
    add("車主證件反面", order.id_back)
    add("退款證明", order.refund_proof)
    from sales.models import DeliveryRecord
    delivery = DeliveryRecord.objects.filter(order=order).first()
    if delivery is not None:
        add("交車照片", delivery.handover_photo)
    for attachment in order.intake_attachments.all():
        add(f"下訂附件_{attachment.get_kind_display()}", attachment.file)
    for record in order.payment_records.exclude(proof="").order_by("pk"):
        add(f"收款證明_{record.received_on:%Y%m%d}" if record.received_on else "收款證明", record.proof)
    for document in order.registration_documents.all():
        add(f"領牌文件_{document.get_document_type_display()}", document.file)
    for document in order.subsidy_documents.all():
        add(f"補助文件_{document.get_document_type_display()}", document.file)
    named, used = [], {}
    for label, field_file in entries:
        base = _clean(label, 80)
        used[base] = used.get(base, 0) + 1
        suffix = f"_{used[base]}" if used[base] > 1 else ""
        named.append((f"{base}{suffix}{_extension(field_file)}", field_file))
    return named


def _same(target, field_file):
    try:
        return target.exists() and target.stat().st_size == field_file.size
    except (OSError, ValueError):
        return False


def sync_order(order_id):
    """把一張訂單的檔案同步到 NAS；沒有啟用或沒有檔案時不建立資料夾。回傳資料夾路徑或 None。"""
    from sales.models import OrderArchiveRecord, SalesOrder

    root = archive_root()
    if root is None:
        return None
    order = (SalesOrder.all_objects.select_related("vehicle_model__family", "source")
             .filter(pk=order_id).first())
    if order is None:
        return None
    record, _ = OrderArchiveRecord.objects.get_or_create(order=order)
    files = order_files(order)
    if not files and not record.folder:
        return None
    relative = order_folder(order)
    target = root / relative
    try:
        if not root.is_dir():
            raise OSError(f"找不到 NAS 根目錄 {root}")
        previous = root / record.folder if record.folder else None
        if previous and record.folder != relative and previous.is_dir():
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                for item in previous.iterdir():
                    shutil.move(str(item), str(target / item.name))
                previous.rmdir()
            else:
                shutil.move(str(previous), str(target))
            _prune_empty_parents(previous.parent, root)
        target.mkdir(parents=True, exist_ok=True)
        names = []
        for name, field_file in files:
            names.append(name)
            destination = target / name
            if _same(destination, field_file):
                continue
            with field_file.open("rb") as source, open(destination, "wb") as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)
        for stale in set(record.files) - set(names):
            try:
                (target / stale).unlink(missing_ok=True)
            except OSError:
                pass
        record.folder, record.files, record.synced_at, record.last_error = relative, names, timezone.now(), ""
    except Exception as exc:  # NAS 斷線、權限或檔案讀取失敗都只記錄，不影響訂單操作
        if isinstance(exc, OSError):
            logger.warning("訂單檔案同步到 NAS 失敗：%s", exc, extra={"order_id": order_id})
        else:
            logger.exception("訂單檔案同步到 NAS 失敗", extra={"order_id": order_id})
        record.last_error = str(exc)[:500]
        record.save(update_fields=["last_error"])
        return None
    record.save(update_fields=["folder", "files", "synced_at", "last_error"])
    return target


def _prune_empty_parents(folder, root):
    """搬移後清掉空的年月／車型資料夾（只清系統建立的層級）。"""
    base = root / ARCHIVE_FOLDER
    current = folder
    while current != base and base in current.parents:
        try:
            current.rmdir()
        except OSError:
            break
        current = current.parent


def schedule_order_archive(order_id):
    """交易提交後排入背景同步；沒有 Redis（開發測試）時直接同步。"""
    if archive_root() is None or not order_id:
        return

    def enqueue():
        if not settings.REDIS_URL:
            sync_order(order_id)
            return
        try:
            django_rq.get_queue("archive").enqueue(
                sync_order, order_id, job_id=f"order-archive-{order_id}",
                job_timeout=600, result_ttl=300, failure_ttl=86400,
            )
        except Exception:
            logger.exception("訂單檔案同步無法排入背景佇列", extra={"order_id": order_id})

    transaction.on_commit(enqueue)
