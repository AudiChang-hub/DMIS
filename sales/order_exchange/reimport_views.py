"""訂單回匯批次修改頁面（T-232 第 3a 版）。

GET  `order_bulk_update`：上傳頁＋自己最近的回匯紀錄。POST：讀檔、建立 `OrderBulkUpdate`，導到預覽。
GET  `order_bulk_update_detail`：預覽（每次依系統現值重新比對、驗證，只讀不寫）；已寫入的顯示結果。
POST `order_bulk_update_apply`：帶回預覽指紋與勾選，整批寫入；失敗整批退回並留在預覽頁顯示原因。
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from sales.access.services import is_root
from sales.models import OrderBulkUpdate

from . import reimport
from .columns import BASELINE_DAYS


def _batch(request, pk):
    batch = get_object_or_404(OrderBulkUpdate.objects.select_related("export_record"), pk=pk)
    if not is_root(request.user) and batch.created_by_id != request.user.pk:
        raise Http404
    return batch


@login_required
@never_cache
def order_bulk_update(request):
    if request.method == "POST":
        upload = request.FILES.get("file")
        if upload is None:
            messages.error(request, "請選擇要匯回的 Excel 檔。")
            return redirect("order_bulk_update")
        from sales.services.upload_validation import validate_excel_upload
        try:
            validate_excel_upload(upload, max_bytes=reimport.MAX_BYTES)
            upload.seek(0)
            record, columns, rows, skipped = reimport.read_workbook(upload)
        except ValidationError as error:
            messages.error(request, "；".join(error.messages))
            return redirect("order_bulk_update")
        except reimport.ReimportError as error:
            messages.error(request, str(error))
            return redirect("order_bulk_update")
        batch = OrderBulkUpdate.objects.create(
            created_by=request.user, actor_name=request.user.get_full_name() or request.user.get_username(),
            export_record=record, file_name=upload.name[:255], columns=columns, rows=rows, skipped_rows=skipped,
        )
        return redirect("order_bulk_update_detail", pk=batch.pk)
    recent = OrderBulkUpdate.objects.filter(created_by=request.user).select_related("export_record")[:10]
    return render(request, "sales/order_exchange/reimport_upload.html", {
        "recent": recent, "max_rows": reimport.MAX_ROWS, "baseline_days": BASELINE_DAYS,
        "max_mb": reimport.MAX_BYTES // (1024 * 1024),
    })


@login_required
@never_cache
def order_bulk_update_detail(request, pk):
    batch = _batch(request, pk)
    if batch.status != OrderBulkUpdate.Status.PREVIEW:
        return render(request, "sales/order_exchange/reimport_detail.html", {"batch": batch, "plan": None})
    plan = reimport.build_plan(batch, request.user)
    # 先用預設勾選（衝突、清空不勾）驗證一次，表單錯誤直接列在該列。
    decisions = reimport.default_decisions(plan)
    for item in plan["rows"]:
        if item["order"] is not None and not item["errors"]:
            item["validation"] = reimport.validate_row(item, decisions[str(item["row"])], request.user)
    plan["summary"] = reimport.summarize(plan["rows"], batch.skipped_rows)
    rows = [item for item in plan["rows"] if item["fields"] or item["errors"] or item["ignored"] or item.get("validation")]
    return render(request, "sales/order_exchange/reimport_detail.html", {
        "batch": batch, "plan": plan, "rows": rows, "section_labels": reimport.SECTION_LABELS,
        "can_apply": not plan["blocking"] and any(item["fields"] for item in plan["rows"]),
    })


@login_required
@never_cache
@require_POST
def order_bulk_update_apply(request, pk):
    batch = _batch(request, pk)
    if batch.status != OrderBulkUpdate.Status.PREVIEW:
        messages.error(request, "這份回匯已經處理過了。")
        return redirect("order_bulk_update_detail", pk=pk)
    decisions = reimport.read_decisions(request.POST)
    try:
        result = reimport.apply_plan(batch, request.user, request.POST.get("fingerprint", ""), decisions)
    except (reimport.PlanChanged, reimport.ApplyFailed) as error:
        OrderBulkUpdate.objects.filter(pk=batch.pk).update(last_error=str(error))
        messages.error(request, "沒有寫入任何資料：" + str(error))
        return redirect("order_bulk_update_detail", pk=pk)
    messages.success(request, f"已批次修改 {result['orders']} 張訂單、{result['fields']} 個欄位，每張都留有修改紀錄。")
    return redirect("order_bulk_update_detail", pk=pk)
