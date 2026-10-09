"""匯入預覽的「既有訂單比對」：對疑似重複或匯入後改動的列，選擇排除、仍新增、維持略過或用 Excel 更新既有訂單。"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.decorators.http import require_POST

from sales.models import LegacyImportBatch, LegacyImportCorrection
from sales.services import import_order_review
from sales.services.legacy_import import apply_import_row_decision

DONE = {
    "update": "已設定用 Excel 更新既有訂單；按「確認匯入」時才會寫入。",
    "create": "已確認為不同交易，此列會新增為新訂單。",
    "keep": "已設定維持略過，不更新既有訂單。",
    "clear": "已取消這一列的比對決定。",
    "exclude": "已排除此列，不會匯入。",
}


@login_required
@require_POST
@transaction.atomic
def legacy_import_order_review(request, pk, row_pk):
    batch = get_object_or_404(LegacyImportBatch.objects.select_for_update(), pk=pk)
    row = get_object_or_404(batch.rows.select_for_update(), pk=row_pk)
    decision = request.POST.get("decision", "")
    reason = request.POST.get("reason", "")
    actor = request.user.get_full_name() or request.user.get_username()
    try:
        if decision == "exclude":
            if len(reason.strip()) < 2:
                raise ValueError("請填寫處理原因。")
            apply_import_row_decision(row, {}, LegacyImportCorrection.Decision.EXCLUDE, reason.strip(), actor)
        elif decision in DONE:
            import_order_review.decide(
                row, decision=decision, order_id=request.POST.get("order"),
                fields=request.POST.getlist("fields"), reason=reason, actor_name=actor,
            )
        else:
            raise ValueError("不明的處理方式。")
    except ValueError as exc:
        messages.error(request, f"Excel 第 {row.source_row} 列：{exc}")
    else:
        messages.success(request, f"Excel 第 {row.source_row} 列：{DONE[decision]}")
    return redirect(f"{reverse('legacy_import_detail', args=[batch.pk])}?review=orders#review-row-{row.pk}")
