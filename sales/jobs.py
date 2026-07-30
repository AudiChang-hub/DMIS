import logging

from django.utils import timezone

from .models import IdOcrJob
from .services.id_ocr import IdOcrError, recognize_id_card


logger = logging.getLogger(__name__)


def run_id_ocr_job(job_id):
    job = IdOcrJob.objects.get(pk=job_id)
    if job.status == IdOcrJob.Status.INVALIDATED:
        return
    job.status = IdOcrJob.Status.RUNNING
    job.attempts += 1
    job.started_at = timezone.now()
    job.error = ""
    job.save(update_fields=["status", "attempts", "started_at", "error", "updated_at"])
    try:
        with job.front.open("rb") as front, job.back.open("rb") as back:
            result = recognize_id_card(front.read(), back.read())
    except IdOcrError as exc:
        job.status = IdOcrJob.Status.FAILED
        job.error = str(exc)
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "error", "finished_at", "updated_at"])
        raise
    except Exception:
        logger.exception("背景身分證 OCR 發生未預期錯誤", extra={"ocr_job": str(job_id)})
        job.status = IdOcrJob.Status.FAILED
        job.error = "辨識服務暫時無法使用，請稍後再試。"
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "error", "finished_at", "updated_at"])
        raise
    job.refresh_from_db(fields=["status"])
    if job.status == IdOcrJob.Status.INVALIDATED:
        return
    job.status = IdOcrJob.Status.SUCCEEDED
    job.result = result
    job.error = ""
    job.finished_at = timezone.now()
    job.save(
        update_fields=["status", "result", "error", "finished_at", "updated_at"]
    )
