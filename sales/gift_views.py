"""手動送禮清單，與每月價格表分發完全獨立。"""
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction, IntegrityError
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from .models import GiftDistribution, GiftDistributionItem, GiftDistributionEvent, SalesSource


class DistributionForm(forms.ModelForm):
    class Meta:
        model = GiftDistribution
        fields = ["title", "scheduled_on", "note"]
        widgets = {"scheduled_on": forms.DateInput(attrs={"type": "date"}), "note": forms.Textarea(attrs={"rows": 3})}


class ItemForm(forms.ModelForm):
    class Meta:
        model = GiftDistributionItem
        fields = ["recipient", "gift", "note"]
        widgets = {"note": forms.Textarea(attrs={"rows": 2})}


@login_required
@require_http_methods(["GET", "POST"])
def manage(request, pk=None):
    activity = get_object_or_404(GiftDistribution, pk=pk) if pk else None
    form = DistributionForm(request.POST or None) if not activity else ItemForm(request.POST or None)
    if request.method == "POST":
        action = request.POST.get("action", "add")
        if activity and activity.archived:
            messages.error(request, "此活動已封存，不可再修改工作紀錄。")
        elif action == "archive" and activity and request.POST.get("confirm") == "yes":
            with transaction.atomic():
                activity = GiftDistribution.objects.select_for_update().get(pk=pk)
                activity.archived = True
                activity.save(update_fields=["archived", "updated_at"])
                GiftDistributionEvent.objects.create(distribution=activity, actor=request.user.get_username(), description="封存活動")
            return redirect("gift_distribution")
        elif action == "add" and form.is_valid():
            try:
                with transaction.atomic():
                    if activity:
                        activity = GiftDistribution.objects.select_for_update().get(pk=pk)
                        if activity.archived:
                            messages.error(request, "活動已由其他人封存，未新增名單。")
                            return redirect("gift_distribution_detail", pk=pk)
                        item = form.save(commit=False)
                        item.distribution = activity
                        previous = GiftDistributionItem.objects.filter(distribution=activity, recipient=item.recipient, removed=True).first()
                        if previous:
                            # 沿用舊列保留建立時間及來源，不以新物件覆寫非空時間欄位。
                            previous.gift = item.gift
                            previous.note = item.note
                            previous.removed = False
                            previous.completed = False
                            previous.completed_at = None
                            previous.completed_by = ""
                            previous.version += 1
                            item = previous
                        item.save()
                        description = f"新增送禮對象：{item.recipient}／{item.gift}"
                    else:
                        activity = form.save(commit=False)
                        activity.created_by = request.user.get_username()
                        activity.save()
                        description = "手動建立活動（尚無名單）"
                    GiftDistributionEvent.objects.create(distribution=activity, actor=request.user.get_username(), description=description)
                messages.success(request, "已儲存。")
                return redirect("gift_distribution_detail", pk=activity.pk)
            except IntegrityError:
                form.add_error("recipient", "此活動已有相同對象，請檢查是否重複。")
        elif action == "add_sources" and activity:
            ids = request.POST.getlist("sources")[:500]
            sources = SalesSource.objects.filter(pk__in=[i for i in ids if i.isdigit()], active=True, source_type="dealer")
            with transaction.atomic():
                activity = GiftDistribution.objects.select_for_update().get(pk=pk)
                if activity.archived:
                    messages.error(request, "活動已由其他人封存，未新增名單。")
                    return redirect("gift_distribution_detail", pk=pk)
                count = 0
                for source in sources:
                    item, created = GiftDistributionItem.objects.get_or_create(distribution=activity, recipient=source.name, defaults={"source": source})
                    if item.removed:
                        item.removed = False
                        item.completed = False
                        item.completed_at = None
                        item.completed_by = ""
                        item.version += 1
                        item.save()
                        created = True
                    count += created
                GiftDistributionEvent.objects.create(distribution=activity, actor=request.user.get_username(), description=f"手動勾選加入 {count} 位送禮對象")
            messages.success(request, f"已加入 {count} 位；重複名單不再新增。")
            return redirect("gift_distribution_detail", pk=pk)
    rows = activity.items.filter(removed=False) if activity else GiftDistribution.objects.filter(archived=request.GET.get("history") == "1").annotate(total=Count("items", filter=Q(items__removed=False)), done=Count("items", filter=Q(items__removed=False, items__completed=True)))
    query = request.GET.get("q", "").strip()
    if query:
        rows = rows.filter(recipient__icontains=query) if activity else rows.filter(title__icontains=query)
    if activity and request.GET.get("state") in {"pending", "done"}:
        rows = rows.filter(completed=request.GET["state"] == "done")
    return render(request, "sales/gift_distribution.html", {"activity": activity, "form": form,
        "page_obj": Paginator(rows, 20).get_page(request.GET.get("page")),
        "sources": SalesSource.objects.filter(active=True, source_type="dealer").order_by("name") if activity else [],
        "events": activity.events.all()[:30] if activity else [], "history": request.GET.get("history") == "1"})


@login_required
@require_http_methods(["POST"])
@transaction.atomic
def update_item(request, pk):
    # 鎖定活動後鎖定列，與封存／新增順序一致。
    item = get_object_or_404(GiftDistributionItem, pk=pk)
    activity = GiftDistribution.objects.select_for_update().get(pk=item.distribution_id)
    item = GiftDistributionItem.objects.select_for_update().get(pk=pk)
    if activity.archived or item.removed or str(item.version) != request.POST.get("version"):
        messages.error(request, "紀錄已變更或封存，請重新確認後操作。")
    elif request.POST.get("action") in {"complete", "reopen", "remove"}:
        action = request.POST["action"]
        if action == "remove":
            item.removed = True
        else:
            item.completed = action == "complete"
            item.completed_at = timezone.now() if item.completed else None
            item.completed_by = request.user.get_username() if item.completed else ""
        item.version += 1
        item.save()
        label = {"complete": "完成送禮", "reopen": "取消完成", "remove": "移除名單"}[action]
        GiftDistributionEvent.objects.create(distribution=activity, actor=request.user.get_username(), description=f"{item.recipient}：{label}")
    return redirect("gift_distribution_detail", pk=activity.pk)
