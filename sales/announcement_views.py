"""公告以應用程式介面管理；不開放 Django admin 寫入。"""
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .access.services import is_root
from .models import SystemAnnouncement, SystemAnnouncementRevision


class AnnouncementForm(forms.ModelForm):
    expected_version = forms.IntegerField(widget=forms.HiddenInput, min_value=0)

    class Meta:
        model = SystemAnnouncement
        fields = ("title", "body", "pinned", "starts_at", "ends_at")
        widgets = {
            "body": forms.Textarea(attrs={"rows": 8}),
            "starts_at": forms.DateTimeInput(format="%Y-%m-%dT%H:%M", attrs={"type": "datetime-local"}),
            "ends_at": forms.DateTimeInput(format="%Y-%m-%dT%H:%M", attrs={"type": "datetime-local"}),
        }


@login_required
@require_http_methods(["GET", "POST"])
def manage(request, pk=None):
    if not is_root(request.user):
        raise PermissionDenied
    item = get_object_or_404(SystemAnnouncement, pk=pk) if pk else SystemAnnouncement(starts_at=timezone.localtime().replace(second=0, microsecond=0))
    form = AnnouncementForm(request.POST or None, instance=item, initial={"expected_version": item.version if pk else 0})
    status = 200
    if request.method == "POST" and form.is_valid():
        action = request.POST.get("action")
        if action not in {"save", "publish", "unpublish"}:
            form.add_error(None, "請選擇儲存、發布或取消發布。")
        else:
            with transaction.atomic():
                current = SystemAnnouncement.objects.select_for_update().get(pk=pk) if pk else None
                if form.cleaned_data["expected_version"] != (current.version if current else 0):
                    form.add_error(None, "公告已由其他視窗修改，本次未覆寫。請重新載入後再編輯。")
                    status = 409
                else:
                    saved = form.save(commit=False)
                    saved.version = current.version + 1 if current else 1
                    saved.published = (current.published if current else False) if action == "save" else action == "publish"
                    saved.updated_by = request.user.get_username()
                    saved.save()
                    SystemAnnouncementRevision.objects.create(announcement=saved, version=saved.version,
                        actor_name=saved.updated_by, content={
                            "title": saved.title, "body": saved.body, "published": saved.published,
                            "pinned": saved.pinned, "starts_at": saved.starts_at.isoformat(),
                            "ends_at": saved.ends_at.isoformat() if saved.ends_at else None,
                        })
                    messages.success(request, f"公告已儲存（{saved.display_status}）。")
                    return redirect("announcement_edit", pk=saved.pk)
    return render(request, "sales/announcement_manage.html", {
        "form": form, "announcement": item if pk else None,
        "page_obj": Paginator(SystemAnnouncement.objects.all(), 12).get_page(request.GET.get("page")),
        "revisions": item.revisions.all()[:10] if pk else [],
    }, status=status)
