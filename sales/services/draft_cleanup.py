"""admin 清理草稿：列出所有人的草稿（不含客戶內容），填原因後刪除並留下稽核紀錄。

一般人員的草稿只看得到自己的（含接待草稿），這裡是 admin 處理卡住或遺留草稿的唯一入口。
有人正在編輯（草稿頁的心跳仍有效）時不刪除，避免刪掉別人正在輸入的資料。
"""
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from sales.models import OrderDraft, UserAccountAuditLog

# 與草稿編輯頁的心跳逾時一致（sales.views.DRAFT_PRESENCE_TIMEOUT）。
EDIT_LOCK_TIMEOUT = timedelta(seconds=90)


def editing_by_someone_else(draft, session_key):
    """有其他工作階段在 90 秒內送過編輯心跳時，回傳編輯人員名稱；否則回傳空字串。"""
    if not draft.editing_session or draft.editing_session == session_key or not draft.editing_at:
        return ""
    if draft.editing_at < timezone.now() - EDIT_LOCK_TIMEOUT:
        return ""
    return draft.editing_by or "其他人員"


def cleanup_rows(session_key):
    drafts = list(OrderDraft.objects.select_related("owner_account").order_by("-updated_at", "pk"))
    for draft in drafts:
        draft.locked_by = editing_by_someone_else(draft, session_key)
        owner = draft.owner_account
        draft.owner_label = (
            (owner.get_full_name() or owner.username) if owner else (draft.created_by or "（沒有下單帳號）")
        )
    return drafts


@transaction.atomic
def delete_draft_as_admin(*, draft_id, actor, reason, session_key):
    """刪除草稿與暫存證件照片，寫入帳號稽核紀錄；回傳寫入的說明文字。"""
    reason = (reason or "").strip()
    if len(reason) < 2:
        raise ValueError("請填寫刪除原因。")
    draft = (
        OrderDraft.objects.select_for_update(of=("self",))
        .select_related("owner_account")
        .filter(pk=draft_id)
        .first()
    )
    if draft is None:
        raise ValueError("找不到這份草稿，可能已經被刪除。")
    editor = editing_by_someone_else(draft, session_key)
    if editor:
        raise ValueError(f"{editor} 正在編輯這份草稿，請稍後再刪除。")
    owner = draft.owner_account
    kind = "接待草稿" if draft.is_reception_draft else "草稿"
    photos = "有暫存證件照片" if (draft.id_front or draft.id_back) else "沒有暫存證件照片"
    description = (
        f"admin 刪除{kind} {str(draft.pk)[:8]}（建立人 {draft.created_by or '未記錄'}，"
        f"建立於 {timezone.localtime(draft.created_at):%Y/%m/%d %H:%M}，車型 {draft.display_vehicle}，{photos}）；"
        f"原因：{reason}"
    )[:500]
    draft.delete_with_files()
    UserAccountAuditLog.objects.create(
        actor=actor,
        target=owner,
        target_username=owner.username if owner else (draft.created_by or "（沒有下單帳號）"),
        action=UserAccountAuditLog.Action.UPDATE,
        description=description,
    )
    return description
