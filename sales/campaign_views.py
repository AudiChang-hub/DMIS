"""獎勵活動畫面（T-149）：原廠獎勵與補助活動、車行獎勵活動、機種工作區唯讀分頁。

活動依品牌、能源別、指定年式與期間套用；訂單依實際領牌日帶入，領牌完成後固定（見 BUSINESS_RULES）。
"""
from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Count, Prefetch, Q
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from .forms import (
    DealerRewardCampaignForm,
    DealerRewardCampaignItemFormSet,
    DealerRewardQuickCatalogForm,
    DEALER_REWARD_STANDARD_UNITS,
    DEALER_REWARD_UNIT_OTHER,
    IncentiveCampaignForm,
    IncentiveCampaignItemFormSet,
)
from .models import (
    DealerRewardCampaign,
    DealerRewardCatalogItem,
    DealerRewardCostVersion,
    IncentiveCampaign,
    VehicleModel,
)
from .services.campaign_conditions import campaigns_for_vehicle_model, condition_summary, vehicle_matches
from .services.vehicle_brands import vehicle_brand_search_q

STATUS_FILTERS = {
    "paused": "已暫停（未選通路）",
    "current": "進行中",
    "future": "尚未開始",
    "expired": "已結束",
    "inactive": "已停用",
}


def _status_filtered(campaigns, status):
    rows = []
    for campaign in campaigns:
        campaign.display_status, campaign.display_status_label = campaign.lifecycle_status
        if campaign.active and getattr(campaign, "is_paused", False):
            campaign.display_status, campaign.display_status_label = "paused", STATUS_FILTERS["paused"]
        campaign.conditions_text = condition_summary(campaign)
        if status and campaign.display_status != status:
            continue
        rows.append(campaign)
    return rows


def _search(queryset, keyword):
    if not keyword:
        return queryset
    return queryset.filter(
        Q(name__icontains=keyword)
        | Q(note__icontains=keyword)
        | Q(vehicle_models__name__icontains=keyword)
        | Q(vehicle_models__brand__icontains=keyword)
        | Q(brands__icontains=keyword)
    ).distinct()


def _prefill_model(request, form):
    """從機種工作區「＋ 新增活動」進入時，預先指定該年式。"""
    model_id = request.GET.get("model", "")
    if request.method == "GET" and model_id.isdigit() and not form.instance.pk:
        form.initial["vehicle_models"] = [int(model_id)]


# ---- 原廠獎勵與補助活動 ----

def _keyword_models(keyword):
    """模糊比對車型（T-161）：品牌（含別名）、機種、車名、型號、原廠型號、年份，不分大小寫、部分符合即可。"""
    query = (
        vehicle_brand_search_q(keyword)
        | Q(family__name__icontains=keyword)
        | Q(name__icontains=keyword)
        | Q(model_number__icontains=keyword)
        | Q(factory_model_codes__code__icontains=keyword)
    )
    if keyword.isdigit() and len(keyword) == 4:
        query |= Q(model_year=int(keyword))
    return list(VehicleModel.objects.filter(query).distinct().order_by("brand", "name", "-model_year", "pk"))


@login_required
@require_http_methods(["GET", "HEAD"])
def incentive_campaign_list(request):
    keyword = request.GET.get("q", "").strip()
    kind = request.GET.get("kind", "")
    status = request.GET.get("status", "")
    status = status if status in STATUS_FILTERS else ""
    campaigns = IncentiveCampaign.objects.prefetch_related("vehicle_models", "items", "dealers").annotate(
        order_count=Count("order_applications", distinct=True),
    )
    if kind in IncentiveCampaign.Kind.values:
        campaigns = campaigns.filter(kind=kind)
    campaigns = list(campaigns.order_by("-active", "kind", "-effective_from", "-id"))
    if keyword:
        # 車型模糊搜尋：列出適用到符合年式的活動，並標出命中的年式；活動名稱或備註符合也列出。
        hits = _keyword_models(keyword)
        folded = keyword.casefold()
        matched = []
        for campaign in campaigns:
            campaign.hit_models = [model for model in hits if vehicle_matches(campaign, model)]
            if campaign.hit_models or folded in campaign.name.casefold() or folded in (campaign.note or "").casefold():
                matched.append(campaign)
        campaigns = matched
    page = Paginator(_status_filtered(campaigns, status), 100).get_page(request.GET.get("page"))
    context = {
        "campaigns": page.object_list,
        "page_obj": page,
        "kinds": IncentiveCampaign.Kind.choices,
        "statuses": STATUS_FILTERS.items(),
        "selected": {"q": keyword, "kind": kind, "status": status},
    }
    template = ("sales/_incentive_campaign_results.html"
                if request.headers.get("X-Requested-With") == "XMLHttpRequest" else "sales/incentive_campaign_list.html")
    return render(request, template, context)


def _incentive_campaign_form_view(request, instance=None):
    campaign = instance or IncentiveCampaign()
    form = IncentiveCampaignForm(request.POST or None, instance=instance)
    _prefill_model(request, form)
    formset = IncentiveCampaignItemFormSet(request.POST or None, instance=campaign, prefix="items")
    if request.method == "POST" and form.is_valid() and formset.is_valid():
        conflicts = form.regular_conflicts(formset.items())
        if conflicts:
            form.add_error(
                "effective_from",
                f"已有同一天開始、涵蓋相同年式且有相同項目的常態活動：{'、'.join(conflicts)}；請改開始日或調整條件。",
            )
        else:
            try:
                with transaction.atomic():
                    saved = form.save()
                    formset.instance = saved
                    formset.save()
            except (ValidationError, IntegrityError) as exc:
                form.add_error(None, exc)
            else:
                messages.success(request, f"已{'更新' if instance else '建立'}原廠獎勵活動：{saved.name}")
                if saved.is_paused:
                    messages.warning(request, f"「{saved.name}」沒有勾選任何通路，已暫停，不會套用到任何訂單。")
                return redirect("incentive_rule_list")
    return render(request, "sales/incentive_campaign_form.html", {
        "form": form,
        "formset": formset,
        "campaign": instance,
        "order_count": instance.order_applications.count() if instance else 0,
    })


@login_required
@require_http_methods(["GET", "HEAD", "POST"])
def incentive_campaign_create(request):
    return _incentive_campaign_form_view(request)


@login_required
@require_http_methods(["GET", "HEAD", "POST"])
def incentive_campaign_edit(request, pk):
    return _incentive_campaign_form_view(request, get_object_or_404(IncentiveCampaign, pk=pk))


@login_required
@require_POST
@transaction.atomic
def incentive_campaign_delete(request, pk):
    campaign = get_object_or_404(IncentiveCampaign.objects.select_for_update(), pk=pk)
    if campaign.order_applications.exists():
        messages.error(request, "此活動已被訂單採用，為保留訂單明細不能刪除；請改為停用或提前結束日期。")
        return redirect("incentive_campaign_edit", pk=pk)
    name = campaign.name
    campaign.delete()
    messages.success(request, f"已刪除原廠獎勵活動：{name}")
    return redirect("incentive_rule_list")


@login_required
def incentive_rule_legacy(request, pk=None):
    """舊的「車型版本」新增／編輯網址：改為活動制後導回活動清單。"""
    messages.info(request, "原廠獎勵與補助已改為活動制，請在活動清單新增或編輯。")
    return redirect("incentive_rule_list")


@login_required
@require_http_methods(["GET", "HEAD"])
def vehicle_model_incentives(request, model_pk):
    """機種工作區「原廠獎勵與補助」分頁：唯讀列出會套用到本年式的活動，今天實際帶入的金額另外試算。"""
    from .services.incentive_rule import incentive_totals

    vehicle_model = get_object_or_404(VehicleModel, pk=model_pk)
    today = timezone.localdate()
    campaigns = _status_filtered(
        campaigns_for_vehicle_model(IncentiveCampaign.objects.order_by("-effective_from", "-id"), vehicle_model), "",
    )
    previews = []
    for source_type, label in (("platform", "網路平台訂單"), ("dealer", "車行訂單"), ("store", "本店訂單")):
        # 試算不帶收款車行：指定車行的活動另在活動卡上標示。
        rows, totals, matched, _promo, _regular = incentive_totals(vehicle_model, source_type, today)
        previews.append({"label": label, "totals": totals, "names": [campaign.name for campaign, _ in rows]})
    return render(request, "sales/vehicle_model_incentives.html", {
        "vehicle_model": vehicle_model,
        "campaigns": campaigns,
        "previews": previews,
        "today": today,
    })


def _backfill_policy(request):
    from .access.services import policy_for

    policy = policy_for(request)
    return policy, policy.screen("incentives", "operate") and policy.screen("order_finance", "operate")


@login_required
@require_http_methods(["GET", "HEAD", "POST"])
def incentive_campaign_backfill(request, pk):
    """掃描既有訂單（T-161）：GET 只讀列出符合的訂單；POST 覆寫勾選的訂單（需原廠獎勵與訂單內部財務的操作權限）。"""
    from .services import incentive_backfill

    campaign = get_object_or_404(IncentiveCampaign.objects.prefetch_related("vehicle_models", "items", "dealers"), pk=pk)
    _policy, can_apply = _backfill_policy(request)
    if request.method == "POST":
        if not can_apply:
            return HttpResponseForbidden("需要「原廠獎勵與補助」與「訂單內部財務編輯」的操作權限。")
        selections = {}
        for value in request.POST.getlist("order"):
            if value.isdigit():
                selections[int(value)] = request.POST.get(f"token_{value}", "")
        if not selections:
            messages.info(request, "沒有勾選訂單，未寫入任何資料。")
            return redirect("incentive_rule_list")
        try:
            updated = incentive_backfill.apply(campaign, selections, request.user.get_username())
        except ValidationError as exc:
            messages.error(request, "；".join(exc.messages))
        else:
            messages.success(request, f"已依「{campaign.name}」覆寫 {updated} 張訂單的原廠獎勵與補助，處理紀錄已留存。")
        return redirect("incentive_rule_list")
    rows = incentive_backfill.scan(campaign)
    return render(request, "sales/_incentive_campaign_backfill.html", {
        "campaign": campaign,
        "rows": rows,
        "can_apply": can_apply,
        "changed_count": sum(1 for row in rows if row["changed"]),
    })


# ---- 車行獎勵活動 ----

def _catalog_metadata(campaign=None):
    catalog_items = DealerRewardCatalogItem.objects.filter(
        Q(active=True) | Q(campaign_items__campaign=campaign) if campaign and campaign.pk else Q(active=True)
    ).distinct().prefetch_related(
        Prefetch(
            "cost_versions",
            queryset=DealerRewardCostVersion.objects.filter(active=True).order_by("-effective_from", "-id"),
            to_attr="prefetched_cost_versions",
        )
    )
    return {str(item.pk): _catalog_entry(item) for item in catalog_items}


def _catalog_entry(item):
    versions = getattr(item, "prefetched_cost_versions", None)
    if versions is None:
        versions = list(item.cost_versions.filter(active=True).order_by("-effective_from", "-id"))
    return {
        "type": item.get_reward_type_display(),
        "unit": item.unit,
        "label": f"{item.name} · {item.get_reward_type_display()}／{item.unit}",
        "costs": [
            {
                "from": version.effective_from.isoformat(),
                "to": version.effective_to.isoformat() if version.effective_to else "",
                "amount": str(version.unit_cost),
            }
            for version in versions
        ],
    }


@login_required
@require_http_methods(["GET", "HEAD"])
def dealer_reward_campaign_list(request):
    keyword = request.GET.get("q", "").strip()
    status = request.GET.get("status", "")
    status = status if status in STATUS_FILTERS else ""
    campaigns = DealerRewardCampaign.objects.prefetch_related("vehicle_models", "dealers", "items").annotate(
        order_count=Count("order_lines__order", distinct=True),
    )
    campaigns = _search(campaigns, keyword).order_by("-active", "-effective_from", "-id")
    page = Paginator(_status_filtered(campaigns, status), 100).get_page(request.GET.get("page"))
    return render(request, "sales/dealer_reward_campaign_list.html", {
        "campaigns": page.object_list,
        "page_obj": page,
        "statuses": STATUS_FILTERS.items(),
        "selected": {"q": keyword, "status": status},
    })


def _dealer_reward_campaign_form_view(request, instance=None):
    from .access.services import policy_for

    campaign = instance or DealerRewardCampaign()
    form = DealerRewardCampaignForm(request.POST or None, instance=instance)
    _prefill_model(request, form)
    formset = DealerRewardCampaignItemFormSet(request.POST or None, instance=campaign, prefix="reward_items")
    if request.method == "POST" and form.is_valid() and formset.is_valid():
        try:
            with transaction.atomic():
                saved = form.save()
                formset.instance = saved
                formset.save()
        except (ValidationError, IntegrityError) as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, f"已{'更新' if instance else '建立'}車行獎勵活動：{saved.name}")
            return redirect("dealer_reward_campaign_list")
    policy = policy_for(request)
    return render(request, "sales/dealer_reward_campaign_form.html", {
        "form": form,
        "formset": formset,
        "campaign": instance,
        "order_count": instance.order_lines.values("order").distinct().count() if instance else 0,
        "reward_catalog_metadata": _catalog_metadata(instance),
        "can_add_catalog": policy.route("dealer_reward_catalog_quick_create", "POST"),
        "quick_catalog_form": DealerRewardQuickCatalogForm(prefix="quick"),
    })


@login_required
@require_http_methods(["GET", "HEAD", "POST"])
def dealer_reward_campaign_create(request):
    return _dealer_reward_campaign_form_view(request)


@login_required
@require_http_methods(["GET", "HEAD", "POST"])
def dealer_reward_campaign_edit(request, pk):
    return _dealer_reward_campaign_form_view(request, get_object_or_404(DealerRewardCampaign, pk=pk))


@login_required
@require_POST
@transaction.atomic
def dealer_reward_campaign_delete(request, pk):
    campaign = get_object_or_404(DealerRewardCampaign.objects.select_for_update(), pk=pk)
    if campaign.order_lines.exists():
        messages.error(request, "此活動已被訂單採用，為保留訂單明細不能刪除；請改為停用或提前結束日期。")
        return redirect("dealer_reward_campaign_edit", pk=pk)
    name = campaign.name
    campaign.delete()
    messages.success(request, f"已刪除車行獎勵活動：{name}")
    return redirect("dealer_reward_campaign_list")


@login_required
@require_POST
def dealer_reward_catalog_quick_create(request):
    """活動表單內直接新增車行獎勵品項（使用者找不到品項維護入口，T-149）；回傳 JSON 給前端加入選單。"""
    data = request.POST.copy()
    unit = (data.get("quick-unit") or "").strip()
    if unit and unit not in DEALER_REWARD_STANDARD_UNITS:
        data["quick-unit"] = DEALER_REWARD_UNIT_OTHER
        data["quick-unit_other"] = unit
    form = DealerRewardQuickCatalogForm(data, prefix="quick")
    if not form.is_valid():
        errors = [str(message) for messages_ in form.errors.values() for message in messages_]
        return JsonResponse({"ok": False, "errors": errors}, status=400)
    try:
        with transaction.atomic():
            item = form.save()
            unit_cost = form.cleaned_data.get("unit_cost")
            if unit_cost is not None:
                start = form.data.get("quick-cost_from") or ""
                try:
                    effective_from = date.fromisoformat(start) if start else timezone.localdate()
                except ValueError:
                    effective_from = timezone.localdate()
                DealerRewardCostVersion.objects.create(
                    catalog_item=item, unit_cost=unit_cost, effective_from=effective_from, active=True,
                    note="由車行獎勵活動表單新增",
                )
    except (ValidationError, IntegrityError) as exc:
        detail = "；".join(exc.messages) if isinstance(exc, ValidationError) else "已有相同類型、名稱與單位的品項。"
        return JsonResponse({"ok": False, "errors": [detail]}, status=400)
    return JsonResponse({"ok": True, "id": item.pk, **_catalog_entry(item)})


def workspace_reward_campaigns(vehicle_model):
    """機種工作區「傭金與獎勵」分頁：會套用到本年式的車行獎勵活動（唯讀）。"""
    return _status_filtered(
        campaigns_for_vehicle_model(
            DealerRewardCampaign.objects.prefetch_related("dealers", "items").order_by("-effective_from", "-id"),
            vehicle_model,
        ),
        "",
    )


def campaign_tab_count(model, vehicle_model):
    return len(campaigns_for_vehicle_model(model.objects.all(), vehicle_model))
