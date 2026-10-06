"""機種沿用：把目前有效的版本沿用到新生效日或新年式。

只建立新版本與新年式，不修改、不刪除任何既有版本；同一車型同一生效日已有版本時略過並回報。
"""
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from sales.models import (
    DealerVehicleRewardItem,
    DealerVehicleRewardPlan,
    InstallmentPlanOption,
    InstallmentPlanVersion,
    UserAccountAuditLog,
    VehicleCatalogEntry,
    VehicleColor,
    VehicleIncentiveRule,
    VehicleModel,
    VehiclePriceVersion,
    VehicleSettlementCostRule,
)
from sales.services.incentive_rule import resolve_incentive_rule
from sales.services.installment_plan import resolve_installment_plan_version
from sales.services.price_version import resolve_vehicle_price_version
from sales.services.settlement_cost import resolve_settlement_cost

# 有生效日的版本資料：(代號, 名稱, 畫面權限, 關聯名稱, 工作區分頁路由)
VERSIONED = (
    ("price", "售價", "models", "price_versions", "vehicle_model_price_versions"),
    ("installment", "分期方案", "models", "installment_plan_versions", "vehicle_installment_plan_list"),
    ("reward", "車行附加獎勵", "commissions", "dealer_reward_plans", "vehicle_model_commission"),
    ("cost", "結算成本", "costs", "settlement_cost_rules", "vehicle_model_settlement_costs"),
    ("incentive", "原廠獎勵與補助", "incentives", "incentive_rules", "vehicle_model_incentives"),
)
VERSIONED_KEYS = tuple(row[0] for row in VERSIONED)
VERSIONED_LABELS = {row[0]: row[1] for row in VERSIONED}
VERSIONED_SCREENS = {row[0]: row[2] for row in VERSIONED}
VERSIONED_RELATED = {row[0]: row[3] for row in VERSIONED}
VERSIONED_ROUTES = {row[0]: row[4] for row in VERSIONED}
VERSIONED_HINTS = {
    "price": "現金價、建議售價與是否含牌險",
    "installment": "各期數、分期公司、每期金額與撥款設定",
    "reward": "實物、紅包、禮券與點數項目",
    "cost": "代銷結算成本",
    "incentive": "實銷獎勵金、促銷補助金與分期補貼息",
}

# 只有沿用到新年式才有的資料：(代號, 名稱, 畫面權限；None 代表限 admin)
YEAR_EXTRAS = (
    ("colors", "車色與車色圖片", "models"),
    ("catalog", "選車圖片與介紹", None),
    ("commission", "車行基礎傭金", "commissions"),
)
YEAR_EXTRA_KEYS = tuple(row[0] for row in YEAR_EXTRAS)
YEAR_EXTRA_LABELS = {row[0]: row[1] for row in YEAR_EXTRAS}
YEAR_EXTRA_HINTS = {
    "colors": "啟用中的車色，車色圖片沿用同一張檔案",
    "catalog": "車款主圖、介紹與排序",
    "commission": "每台現金傭金，無版本、建立即生效",
}
MODEL_ORDER = ("brand", "family__name", "name", "-model_year", "model_code", "pk")


def first_of_next_month(today=None):
    today = today or timezone.localdate()
    return (today.replace(day=1) + timedelta(days=32)).replace(day=1)


def validate_effective_from(value, today=None):
    today = today or timezone.localdate()
    if value is None:
        raise ValidationError("請選擇生效日期。")
    if value < today:
        raise ValidationError(f"生效日期不可早於今天（{today:%Y/%m/%d}）；過去的價格請到機種工作區個別處理。")
    return value


def money(value):
    if value is None:
        return "未填"
    return f"${Decimal(value):,.0f}"


def model_label(model):
    parts = [model.name]
    if model.model_year:
        parts.append(f"{model.model_year} 年式")
    if model.model_code:
        parts.append(model.get_model_code_display())
    return " ".join(parts)


def reward_plans_on(model_id, day):
    return DealerVehicleRewardPlan.objects.filter(
        vehicle_model_id=model_id, active=True, effective_from__lte=day,
    ).filter(Q(effective_to__isnull=True) | Q(effective_to__gte=day)).order_by("-effective_from", "-id")


def current_version(dataset, model_id, day):
    """依各資料原本的解析規則取得指定日期有效的版本；不自行推導。"""
    if dataset == "price":
        return resolve_vehicle_price_version(model_id, day)
    if dataset == "installment":
        return resolve_installment_plan_version(model_id, day)
    if dataset == "cost":
        return resolve_settlement_cost(model_id, day)
    if dataset == "incentive":
        return resolve_incentive_rule(model_id, day)
    if dataset == "reward":
        return reward_plans_on(model_id, day).prefetch_related("items").first()
    raise ValueError(dataset)


VERSION_MODELS = {
    "price": VehiclePriceVersion, "installment": InstallmentPlanVersion, "reward": DealerVehicleRewardPlan,
    "cost": VehicleSettlementCostRule, "incentive": VehicleIncentiveRule,
}


def version_exists_on(dataset, model_id, day):
    return VERSION_MODELS[dataset].objects.filter(vehicle_model_id=model_id, effective_from=day).exists()


def current_versions_bulk(dataset, model_ids, day):
    """清單顯示用：一次取得多個年式在指定日期的有效版本，條件與各 resolve_* 相同（啟用、期間涵蓋、取最新生效）。"""
    queryset = VERSION_MODELS[dataset].objects.filter(
        vehicle_model_id__in=model_ids, active=True, effective_from__lte=day,
    ).filter(Q(effective_to__isnull=True) | Q(effective_to__gte=day)).order_by("vehicle_model_id", "-effective_from", "-id")
    result = {}
    for version in queryset:
        result.setdefault(version.vehicle_model_id, version)
    return result


def models_with_version_on(dataset, model_ids, day):
    return set(
        VERSION_MODELS[dataset].objects.filter(vehicle_model_id__in=model_ids, effective_from=day)
        .values_list("vehicle_model_id", flat=True)
    )


def reward_overlaps(model_id, day):
    """附加獎勵的啟用期間不可重疊；新版本不設結束日，所以任何仍在有效期的啟用方案都會重疊。"""
    return DealerVehicleRewardPlan.objects.filter(vehicle_model_id=model_id, active=True).filter(
        Q(effective_to__isnull=True) | Q(effective_to__gte=day)
    ).exists()


def summarize(dataset, version):
    if version is None:
        return ""
    if dataset == "price":
        registration = "含牌險" if version.suggested_price_includes_registration else "不含牌險"
        return f"現金價 {money(version.cash_price)}／建議售價 {money(version.suggested_price)}（{registration}）"
    if dataset == "installment":
        periods = [f"{option.periods} 期" for option in version.options.all()]
        return "、".join(periods) or "尚未設定期數"
    if dataset == "reward":
        return version.reward_summary or "尚未填寫項目"
    if dataset == "cost":
        return f"結算成本 {money(version.amount)}"
    if dataset == "incentive":
        return (
            f"實銷 {money(version.sales_bonus)}／促銷 {money(version.promotion_subsidy)}／"
            f"分期補貼 {money(version.installment_interest_subsidy)}"
        )
    return ""


def copy_version(dataset, source, target_model, effective_from, note):
    """複製一個版本到目標車型與生效日；新版本一律啟用、不設結束日。"""
    today = timezone.localdate()
    if dataset == "price":
        return VehiclePriceVersion.objects.create(
            vehicle_model=target_model,
            suggested_price=source.suggested_price,
            suggested_price_includes_registration=source.suggested_price_includes_registration,
            cash_price=source.cash_price,
            announced_on=today,
            effective_from=effective_from,
            source_note=note[:250],
            active=True,
        )
    if dataset == "installment":
        version = InstallmentPlanVersion.objects.create(
            vehicle_model=target_model, announced_on=today, effective_from=effective_from, note=note, active=True,
        )
        InstallmentPlanOption.objects.bulk_create([
            InstallmentPlanOption(
                version=version,
                periods=option.periods,
                monthly_amount=option.monthly_amount,
                company_id=option.company_id,
                opening_fee=option.opening_fee,
                expected_disbursement_rate=option.expected_disbursement_rate,
                expected_disbursement_method=option.expected_disbursement_method,
                expected_disbursement_fixed_amount=option.expected_disbursement_fixed_amount,
                extra_disbursement_bonus=option.extra_disbursement_bonus,
            )
            for option in source.options.all()
        ])
        return version
    if dataset == "reward":
        plan = DealerVehicleRewardPlan.objects.create(
            vehicle_model=target_model, effective_from=effective_from, active=True, note=note,
        )
        for item in source.items.select_related("catalog_item"):
            unit_cost = item.unit_cost_snapshot
            if item.catalog_item_id:
                # 與附加獎勵表單相同：成本快照依新版本的生效日重新取得。
                cost_version = item.catalog_item.cost_version_on(effective_from)
                unit_cost = cost_version.unit_cost if cost_version else None
            DealerVehicleRewardItem.objects.create(
                plan=plan,
                catalog_item=item.catalog_item,
                reward_type=item.reward_type,
                name=item.name,
                quantity=item.quantity,
                unit=item.unit,
                unit_cost_snapshot=unit_cost,
                cost_effective_on_snapshot=effective_from,
                note=item.note,
            )
        return plan
    if dataset == "cost":
        return VehicleSettlementCostRule.objects.create(
            vehicle_model=target_model, amount=source.amount, announced_on=today,
            effective_from=effective_from, note=note, active=True,
        )
    if dataset == "incentive":
        return VehicleIncentiveRule.objects.create(
            vehicle_model=target_model,
            sales_bonus=source.sales_bonus,
            promotion_subsidy=source.promotion_subsidy,
            installment_interest_subsidy=source.installment_interest_subsidy,
            announced_on=today,
            effective_from=effective_from,
            note=note,
            active=True,
        )
    raise ValueError(dataset)


def allowed_datasets(policy, *, include_extras=False):
    """回傳 {代號: 是否可操作}；畫面權限不足的資料不能勾選。"""
    allowed = {key: policy.screen(VERSIONED_SCREENS[key], "operate") for key in VERSIONED_KEYS}
    if include_extras:
        for key, _label, screen in YEAR_EXTRAS:
            allowed[key] = policy.root if screen is None else policy.screen(screen, "operate")
    return allowed


# ---- 篩選 ----

def filter_options():
    models = VehicleModel.objects.all()
    brands = sorted({brand for brand in models.values_list("brand", flat=True) if brand}, key=str.casefold)
    families = list(
        models.exclude(family__isnull=True)
        .values_list("family_id", "family__brand", "family__name")
        .distinct()
        .order_by("family__brand", "family__name")
    )
    years = sorted({year for year in models.values_list("model_year", flat=True) if year}, reverse=True)
    return {
        "brands": brands,
        "families": [{"id": pk, "brand": brand, "name": name} for pk, brand, name in families],
        "years": years,
        "energy_types": VehicleModel.EnergyType.choices,
    }


def read_filters(params):
    def digits(name):
        value = (params.get(name) or "").strip()
        return int(value) if value.isdigit() else None

    status = params.get("status") or "active"
    if status not in {"active", "inactive", "all"}:
        status = "active"
    energy = params.get("energy_type") or ""
    if energy not in {value for value, _label in VehicleModel.EnergyType.choices}:
        energy = ""
    return {
        "brand": (params.get("brand") or "").strip(),
        "family": digits("family"),
        "year": digits("year"),
        "energy_type": energy,
        "status": status,
    }


def filtered_models(filters):
    queryset = VehicleModel.objects.select_related("family")
    if filters["brand"]:
        queryset = queryset.filter(brand__iexact=filters["brand"])
    if filters["family"]:
        queryset = queryset.filter(family_id=filters["family"])
    if filters["year"]:
        queryset = queryset.filter(model_year=filters["year"])
    if filters["energy_type"]:
        queryset = queryset.filter(energy_type=filters["energy_type"])
    if filters["status"] == "active":
        queryset = queryset.filter(active=True)
    elif filters["status"] == "inactive":
        queryset = queryset.filter(active=False)
    return queryset.order_by(*MODEL_ORDER)


# ---- 沿用到新生效日 ----

def plan_new_date(models, effective_from, datasets):
    """每個車型、每項資料：沿用前一天有效的版本；沒有版本或該日已有版本則略過並說明原因。"""
    source_day = effective_from - timedelta(days=1)
    rows = []
    for model in models:
        items = []
        for dataset in datasets:
            item = {"dataset": dataset, "label": VERSIONED_LABELS[dataset], "status": "create", "reason": "",
                    "source": None, "summary": ""}
            if version_exists_on(dataset, model.pk, effective_from):
                item.update(status="duplicate", reason=f"{effective_from:%Y/%m/%d} 已有版本，未重複建立")
            else:
                source = current_version(dataset, model.pk, source_day)
                if source is None:
                    item.update(status="missing", reason=f"{source_day:%Y/%m/%d} 沒有有效版本可沿用")
                elif dataset == "reward" and reward_overlaps(model.pk, effective_from):
                    item.update(
                        status="overlap", source=source, summary=summarize(dataset, source),
                        reason="原方案仍在有效期內；附加獎勵期間不可重疊，請先在「傭金與獎勵」分頁設定原方案結束日",
                    )
                else:
                    item.update(source=source, summary=summarize(dataset, source))
            items.append(item)
        rows.append({
            "model": model,
            "label": model_label(model),
            "items": items,
            "create_count": sum(item["status"] == "create" for item in items),
        })
    return rows


@transaction.atomic
def execute_new_date(*, model_ids, effective_from, datasets, actor):
    validate_effective_from(effective_from)
    models = list(VehicleModel.objects.select_for_update().filter(pk__in=model_ids).order_by("pk"))
    models.sort(key=lambda model: (model.brand.casefold(), model.name.casefold(), -(model.model_year or 0), model.pk))
    rows = plan_new_date(models, effective_from, datasets)
    created = []
    for row in rows:
        for item in row["items"]:
            if item["status"] != "create":
                continue
            source = item["source"]
            note = f"沿用自 {source.effective_from:%Y/%m/%d} 起的版本"
            version = copy_version(item["dataset"], source, row["model"], effective_from, note)
            item["created_id"] = version.pk
            created.append({"model_id": row["model"].pk, "dataset": item["dataset"], "version_id": version.pk,
                            "source_id": source.pk})
    skipped = [
        {"model_id": row["model"].pk, "dataset": item["dataset"], "status": item["status"]}
        for row in rows for item in row["items"] if item["status"] != "create"
    ]
    _audit(
        actor, "update",
        f"沿用到新生效日 {effective_from:%Y/%m/%d}：{len(models)} 個年式，建立 {len(created)} 筆新版本、略過 {len(skipped)} 筆",
        {"tool": "vehicle_model_copy_date", "effective_from": effective_from.isoformat(),
         "datasets": list(datasets), "created": created, "skipped": skipped},
    )
    return rows, created


# ---- 沿用到新年式 ----

def year_conflict(model, target_year, reserved=()):
    """同品牌、機種、年份與型式已存在時不可建立（與新增年式表單同一規則）。"""
    if not target_year:
        return "請填寫新年式。"
    if target_year < 1900 or target_year > 2200:
        return "年份需介於 1900 到 2200。"
    key = (model.brand.casefold(), model.name.casefold(), target_year, model.model_code)
    if key in reserved:
        return f"本次已有另一列要建立相同的 {target_year} 年式。"
    exists = VehicleModel.objects.filter(
        brand__iexact=model.brand, name__iexact=model.name, model_year=target_year, model_code=model.model_code,
    ).exists()
    if exists:
        code = model.get_model_code_display() or "未設定型式"
        return f"「{model.name}」已有 {target_year} 年式（{code}），不能重複建立；請直接編輯既有年式。"
    return ""


def plan_new_year(entries, effective_from, datasets, extras):
    """entries 為 [(基準年式, 新年式)]；回傳每列要建立的內容與阻擋原因。"""
    reserved = set()
    rows = []
    for model, target_year in entries:
        conflict = year_conflict(model, target_year, reserved)
        if not conflict:
            reserved.add((model.brand.casefold(), model.name.casefold(), target_year, model.model_code))
        items = []
        for dataset in datasets:
            source = current_version(dataset, model.pk, effective_from)
            items.append({
                "dataset": dataset, "label": VERSIONED_LABELS[dataset],
                "status": "create" if source else "missing",
                "reason": "" if source else f"{effective_from:%Y/%m/%d} 沒有有效版本可沿用",
                "source": source, "summary": summarize(dataset, source),
            })
        extra_items = []
        if "colors" in extras:
            names = list(model.colors.filter(active=True).order_by("name").values_list("name", flat=True))
            extra_items.append({"key": "colors", "label": YEAR_EXTRA_LABELS["colors"],
                                "status": "create" if names else "missing",
                                "summary": "、".join(names) if names else "沒有啟用中的車色"})
        if "catalog" in extras:
            entry = VehicleCatalogEntry.objects.filter(vehicle_model=model).first()
            has_content = bool(entry and (entry.image or entry.description))
            extra_items.append({"key": "catalog", "label": YEAR_EXTRA_LABELS["catalog"],
                                "status": "create" if has_content else "missing",
                                "summary": ("主圖與介紹" if entry and entry.image and entry.description else
                                            "主圖" if entry and entry.image else "介紹") if has_content else "尚未設定"})
        if "commission" in extras:
            extra_items.append({"key": "commission", "label": YEAR_EXTRA_LABELS["commission"], "status": "create",
                                "summary": money(model.base_dealer_commission)})
        rows.append({
            "model": model,
            "label": model_label(model),
            "target_year": target_year,
            "conflict": conflict,
            "items": items,
            "extras": extra_items,
            "create_count": 0 if conflict else sum(item["status"] == "create" for item in items),
        })
    return rows


def _create_year(base, target_year, effective_from, datasets, extras, activate, rows_item):
    new_model = VehicleModel(
        brand=base.brand,
        name=base.name,
        model_number=base.model_number,
        energy_type=base.energy_type,
        model_year=target_year,
        model_code=base.model_code,
        displacement_cc=base.displacement_cc,
        motor_power_kw=base.motor_power_kw,
        horsepower_hp=base.horsepower_hp,
        electric_registration_class=base.electric_registration_class,
        base_dealer_commission=base.base_dealer_commission if "commission" in extras else 0,
        active=activate,
    )
    new_model.clean()
    new_model.save()
    codes = list(base.factory_model_codes.filter(active=True))
    if codes:
        new_model.factory_model_codes.add(*codes)
    if "colors" in extras:
        for color in base.colors.filter(active=True).order_by("name"):
            VehicleColor.objects.create(
                vehicle_model=new_model, name=color.name,
                catalog_image=color.catalog_image.name if color.catalog_image else "",
            )
    if "catalog" in extras:
        entry = VehicleCatalogEntry.objects.filter(vehicle_model=base).first()
        if entry:
            VehicleCatalogEntry.objects.update_or_create(
                vehicle_model=new_model,
                defaults={
                    "image": entry.image.name if entry.image else "",
                    "description": entry.description,
                    "position": entry.position,
                },
            )
    created = []
    for item in rows_item["items"]:
        if item["status"] != "create":
            continue
        source = item["source"]
        note = f"沿用自 {model_label(base)} {source.effective_from:%Y/%m/%d} 起的版本"
        version = copy_version(item["dataset"], source, new_model, effective_from, note)
        item["created_id"] = version.pk
        created.append({"dataset": item["dataset"], "version_id": version.pk, "source_id": source.pk})
    return new_model, created


@transaction.atomic
def execute_new_year(*, entries, effective_from, datasets, extras, activate, actor):
    """entries 為 [(基準年式 pk, 新年式)]；有任何一列無法建立時整批不寫入。"""
    validate_effective_from(effective_from)
    by_pk = VehicleModel.objects.select_for_update().in_bulk([pk for pk, _year in entries])
    pairs = [(by_pk[pk], year) for pk, year in entries if pk in by_pk]
    if len(pairs) != len(entries):
        raise ValidationError("部分年式已不存在，請重新選擇。")
    rows = plan_new_year(pairs, effective_from, datasets, extras)
    conflicts = [f"{row['label']}：{row['conflict']}" for row in rows if row["conflict"]]
    if conflicts:
        raise ValidationError(conflicts)
    results = []
    for row in rows:
        new_model, created = _create_year(row["model"], row["target_year"], effective_from, datasets, extras,
                                          activate, row)
        row["new_model"] = new_model
        results.append({"base_id": row["model"].pk, "model_id": new_model.pk, "versions": created})
    names = "、".join(f"{row['model'].name} {row['target_year']}" for row in rows)
    _audit(
        actor, "create",
        f"沿用到新年式：建立 {len(rows)} 個年式（{names}），版本生效 {effective_from:%Y/%m/%d}，"
        f"{'立即啟用' if activate else '先停用'}",
        {"tool": "vehicle_model_copy_year", "effective_from": effective_from.isoformat(),
         "datasets": list(datasets), "extras": list(extras), "activate": activate, "results": results},
    )
    return rows


def _audit(actor, action, description, metadata):
    UserAccountAuditLog.objects.create(
        actor=actor, target=actor, target_username=actor.get_username(), action=action,
        description=description[:500], metadata=metadata,
    )


# ---- 新增版本預填（A3） ----

PREFILL_FIELDS = {
    "price": ("suggested_price", "suggested_price_includes_registration", "cash_price"),
    "cost": ("amount",),
    "incentive": ("sales_bonus", "promotion_subsidy", "installment_interest_subsidy"),
    "installment": (),
    "reward": (),
}


def prefill_source(dataset, model_id, default_from=None):
    """新增版本表單預填：取預設生效日前一天有效的版本，使用者只需修改差異。"""
    default_from = default_from or first_of_next_month()
    latest = (
        VERSION_MODELS[dataset].objects.filter(vehicle_model_id=model_id, active=True, effective_from__gte=default_from)
        .order_by("-effective_from", "-id").first()
    )
    if latest is not None:
        # 下個月 1 日之後已排定版本時，改以最後一個排定版本為底，生效日順延到它的下個月 1 日，避免撞到同一天。
        default_from = first_of_next_month(latest.effective_from)
    return current_version(dataset, model_id, default_from - timedelta(days=1)), default_from


def prefill_initial(dataset, model_id):
    """回傳 (表單 initial, 來源版本)；生效日預設下個月 1 日，公告日為今天，備註留白讓使用者寫新原因。"""
    source, default_from = prefill_source(dataset, model_id)
    initial = {"effective_from": default_from}
    if source is not None:
        initial.update({name: getattr(source, name) for name in PREFILL_FIELDS[dataset]})
    return initial, source


def installment_option_initial(source):
    return [
        {
            "periods": option.periods,
            "monthly_amount": option.monthly_amount,
            "company": option.company_id,
            "opening_fee": option.opening_fee,
            "expected_disbursement_method": option.expected_disbursement_method,
            "expected_disbursement_rate": option.expected_disbursement_rate,
            "expected_disbursement_fixed_amount": option.expected_disbursement_fixed_amount,
            "extra_disbursement_bonus": option.extra_disbursement_bonus,
        }
        for option in source.options.all()
    ] if source else []


def reward_item_initial(source):
    return [
        {"catalog_item": item.catalog_item_id, "quantity": item.quantity, "note": item.note}
        for item in source.items.all() if item.catalog_item_id
    ] if source else []
