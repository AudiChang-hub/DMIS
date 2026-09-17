"""公告以應用程式介面管理；不開放 Django admin 寫入。"""
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .access.services import is_root
from .models import SystemAnnouncement, SystemAnnouncementRevision


class AnnouncementForm(forms.ModelForm):
    expected_version = forms.IntegerField(widget=forms.HiddenInput, min_value=0)

    class Meta:
        model = SystemAnnouncement
        fields = ("title", "body", "pinned", "starts_at", "ends_at", "audience", "recipients")
        widgets = {
            "body": forms.Textarea(attrs={"rows": 8}),
            "starts_at": forms.DateTimeInput(format="%Y-%m-%dT%H:%M", attrs={"type": "datetime-local"}),
            "ends_at": forms.DateTimeInput(format="%Y-%m-%dT%H:%M", attrs={"type": "datetime-local"}),
            "recipients": forms.CheckboxSelectMultiple,
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["recipients"].queryset = get_user_model().objects.filter(is_active=True).order_by("username")
        self.fields["recipients"].label_from_instance = lambda user: f"{user.get_full_name() or user.username}（{user.username}）"
        # 舊版已開啟的表單仍可儲存，未帶新欄位時維持原受眾。
        if self.is_bound and "audience" not in self.data:
            self.data = self.data.copy()
            self.data["audience"] = self.instance.audience or "all"
            if self.instance.pk:
                self.data.setlist("recipients", list(self.instance.recipients.values_list("pk", flat=True)))

    def clean(self):
        data = super().clean()
        if data.get("audience") == "selected" and not data.get("recipients"):
            self.add_error("recipients", "請至少勾選一位人員，或改選其他顯示對象。")
        return data


@login_required
@require_http_methods(["GET", "POST"])
def manage(request, pk=None):
    if not is_root(request.user):
        raise PermissionDenied
    item = get_object_or_404(SystemAnnouncement, pk=pk, deleted_at__isnull=True) if pk else SystemAnnouncement(starts_at=timezone.localtime().replace(second=0, microsecond=0))
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
                    form.save_m2m()
                    SystemAnnouncementRevision.objects.create(announcement=saved, version=saved.version,
                        actor_name=saved.updated_by, content={
                            "title": saved.title, "body": saved.body, "published": saved.published,
                            "pinned": saved.pinned, "starts_at": saved.starts_at.isoformat(),
                            "ends_at": saved.ends_at.isoformat() if saved.ends_at else None,
                            "audience": saved.audience, "recipients": list(saved.recipients.values_list("pk", flat=True)),
                        })
                    messages.success(request, f"公告已儲存（{saved.display_status}）。")
                    return redirect("announcement_edit", pk=saved.pk)
    history = request.GET.get("history") == "1"
    expired = Q(ends_at__lte=timezone.now()) | Q(archived_at__isnull=False)
    rows = SystemAnnouncement.objects.filter(deleted_at__isnull=True)
    rows = rows.filter(expired) if history else rows.exclude(expired)
    if request.GET.get("q"):
        rows = rows.filter(Q(title__icontains=request.GET["q"]) | Q(body__icontains=request.GET["q"]))
    return render(request, "sales/announcement_manage.html", {
        "form": form, "announcement": item if pk else None,
        "page_obj": Paginator(rows, 10).get_page(request.GET.get("page")), "history": history,
        "revisions": item.revisions.all()[:10] if pk else [],
    }, status=status)


@login_required
@require_http_methods(["GET", "POST"])
def lifecycle(request, pk):
    if not is_root(request.user):
        raise PermissionDenied
    item = get_object_or_404(SystemAnnouncement, pk=pk, deleted_at__isnull=True)
    if request.method == "POST":
        action = request.POST.get("action")
        if action not in {"archive", "delete"} or request.POST.get("confirm") != "yes":
            messages.error(request, "請確認操作後再送出。")
        else:
            with transaction.atomic():
                item = SystemAnnouncement.objects.select_for_update().get(pk=pk)
                if str(item.version) != request.POST.get("expected_version") or item.deleted_at:
                    return render(request, "sales/announcement_action.html", {"item": item, "conflict": True}, status=409)
                setattr(item, "deleted_at" if action == "delete" else "archived_at", timezone.now())
                item.published = False
                item.version += 1
                item.updated_by = request.user.get_username()
                item.save()
                SystemAnnouncementRevision.objects.create(announcement=item, version=item.version,
                    actor_name=item.updated_by, content={"action": action, "title": item.title, "body": item.body})
            messages.success(request, "公告已刪除，稽核紀錄保留。" if action == "delete" else "公告已移至歷史公告。")
            return redirect("announcement_manage")
    return render(request, "sales/announcement_action.html", {"item": item})


@login_required
def detail(request, pk):
    item = get_object_or_404(SystemAnnouncement.visible(user=request.user), pk=pk)
    return render(request, "sales/announcement_detail.html", {"item": item})


def home_news_context(request):
    from sales.services.audience_content import release_context
    from sales.access.services import policy_for
    context = release_context(policy_for(request))
    context["release_history"] = context["release_history"][:2]
    context["legacy_updates"] = []
    context["release_compact"] = True
    context["news_tab"] = "releases" if request.GET.get("news") == "releases" else "announcements"
    context["page_obj"] = Paginator(SystemAnnouncement.visible(user=request.user), 10).get_page(request.GET.get("page"))
    context["expired_announcement_count"] = SystemAnnouncement.objects.filter(
        ends_at__lte=timezone.now(), archived_at__isnull=True, deleted_at__isnull=True).count() if is_root(request.user) else 0
    return context


@login_required
def release_history(request):
    from sales.services.audience_content import release_context
    from sales.access.services import policy_for
    context = release_context(policy_for(request))
    page = Paginator(context["release_history"], 10).get_page(request.GET.get("page"))
    return render(request, "sales/release_history.html", {**context, "release_history": page, "page_obj": page})
