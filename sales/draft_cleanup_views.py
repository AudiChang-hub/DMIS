"""admin 草稿清理畫面；路由列在 ROOT_ONLY，只有 admin 能進。"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from sales.services.draft_cleanup import cleanup_rows, delete_draft_as_admin


@login_required
@require_http_methods(["GET", "HEAD"])
def draft_cleanup_list(request):
    drafts = cleanup_rows(request.session.session_key)
    return render(request, "sales/draft_cleanup.html", {"drafts": drafts})


@login_required
@require_POST
def draft_cleanup_delete(request, pk):
    if not request.POST.get("confirmed"):
        messages.error(request, "請勾選確認後再刪除。")
        return redirect("draft_cleanup_list")
    try:
        delete_draft_as_admin(
            draft_id=pk,
            actor=request.user,
            reason=request.POST.get("reason", ""),
            session_key=request.session.session_key,
        )
    except ValueError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "已刪除草稿與暫存證件照片，並留下稽核紀錄。")
    return redirect("draft_cleanup_list")
