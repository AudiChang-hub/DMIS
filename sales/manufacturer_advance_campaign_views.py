"""代墊／代轉活動設定（T-337）：比照「原廠獎勵與補助」的清單與表單，欄位精簡。

清單分「啟用中」「停用」兩個頁籤，篩選按「套用」才查。存檔後依活動條件重新比對訂單（已勾過的項目不動）。
權限比照原廠獎勵活動（sales/access/registry.py 的 incentives）。比對與掛單邏輯在 services/manufacturer_advance_campaign.py。
"""
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from sales.models import ManufacturerAdvanceCampaign
from sales.services import manufacturer_advance_campaign as advance_campaigns

TABS = (("active", "啟用中", "會自動掛到符合條件的訂單"), ("inactive", "停用", "已停用、不再自動掛單的活動"))


@login_required
@require_http_methods(["GET", "HEAD"])
def campaign_list(request):
    keyword = request.GET.get("q", "").strip()
    manufacturer = request.GET.get("manufacturer", "").strip()
    tab = request.GET.get("tab", "")
    tab = tab if tab in {key for key, _label, _hint in TABS} else "active"
    queryset = ManufacturerAdvanceCampaign.objects.all()
    options = sorted(set(queryset.values_list("manufacturer", flat=True)))
    if manufacturer:
        queryset = queryset.filter(manufacturer=manufacturer)
    if keyword:
        queryset = queryset.filter(Q(name__icontains=keyword) | Q(gift_name__icontains=keyword)
                                   | Q(vehicle_models__name__icontains=keyword)).distinct()
    rows = list(advance_campaigns.campaign_rows(queryset))
    for campaign in rows:
        campaign.models_text = advance_campaigns.models_label(campaign)
    grouped = {"active": [row for row in rows if row.active], "inactive": [row for row in rows if not row.active]}
    kept = {key: value for key, value in (("q", keyword), ("manufacturer", manufacturer)) if value}
    tabs = [{"key": key, "label": label, "hint": hint, "count": len(grouped[key]), "active": key == tab,
             "url": f"{request.path}?{urlencode({**kept, 'tab': key})}"} for key, label, hint in TABS]
    return render(request, "sales/manufacturer_advance_campaign_list.html", {
        "campaigns": grouped[tab],
        "status_tabs": {"status": tab, "counts": {item["key"]: item["count"] for item in tabs},
                        "urls": {item["key"]: item["url"] for item in tabs}},
        "manufacturer_options": options,
        "selected": {"q": keyword, "manufacturer": manufacturer, "tab": tab},
    })


def _form_view(request, instance=None):
    form = advance_campaigns.CampaignForm(request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            campaign = form.save(commit=False)
            if not campaign.pk:
                campaign.created_by = request.user
            campaign.save()
            form.save_m2m()
            attached, removed = advance_campaigns.reconcile_campaign(campaign)
        summary = []
        if attached:
            summary.append(f"掛上 {attached} 張訂單")
        if removed:
            summary.append(f"移除 {removed} 張不再符合的訂單")
        tail = f"，{'、'.join(summary)}" if summary else ""
        messages.success(request, f"已{'更新' if instance else '建立'}代墊／代轉活動：{campaign.name}{tail}")
        return redirect("manufacturer_advance_campaign_list")
    return render(request, "sales/manufacturer_advance_campaign_form.html", {
        "form": form, "campaign": instance,
        "attached_count": instance.advance_items.filter(voided_at__isnull=True).count() if instance else 0,
    })


@login_required
@require_http_methods(["GET", "HEAD", "POST"])
def campaign_create(request):
    return _form_view(request)


@login_required
@require_http_methods(["GET", "HEAD", "POST"])
def campaign_edit(request, pk):
    return _form_view(request, get_object_or_404(ManufacturerAdvanceCampaign, pk=pk))


@login_required
@require_POST
@transaction.atomic
def campaign_delete(request, pk):
    campaign = get_object_or_404(ManufacturerAdvanceCampaign.objects.select_for_update(), pk=pk)
    if campaign.advance_items.exists():
        messages.error(request, "這個活動已經掛到訂單上，為保留紀錄不能刪除；請改成停用。")
        return redirect("manufacturer_advance_campaign_edit", pk=pk)
    name = campaign.name
    campaign.delete()
    messages.success(request, f"已刪除代墊／代轉活動：{name}")
    return redirect("manufacturer_advance_campaign_list")
