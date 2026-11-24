"""T-311：電動車銷售統計（#5）、油車銷售統計（#7）的圖卡改成 B 案（使用者 2026-11-24 經 PM 同意改這兩張內建報表的設定）。

改法（與 sales.reporting.source_templates.electric_vehicle_sales／gasoline_vehicle_sales 相同，測試核對）：
- 原本三張：每月銷售來源（月份堆疊）、每月銷售型號（月份堆疊）、型號占比（圓餅）。
- 改成四張：每月銷售型號、每月銷售來源、型號占比、**銷售來源占比（新增圓餅）**。前三張只調順序，內容一字不改；
  閱讀頁把兩張月份圖合成一張可切換的圖（reader_layouts.reader_cards，型號在前），下面並排兩個圓餅。
- 總車輛銷售（#4）的圖卡本來就是兩張月份圖＋兩個圓餅，合併只靠版型，不改設定，所以這裡不動。

範圍與安全：
- 只改「版型是電動車／油車銷售、標題是內建名稱、圖卡仍是內建原樣（三張、種類與維度相符）」的報表；
  使用者自建的報表、改過圖卡的報表、已經是新樣子的報表一律略過，可重跑（idempotent）。
- 只改 published；draft 與 published 相同時一起改，管理者有未發布的草稿就不動草稿。
- 每改一筆加一筆 publish 版本紀錄；改前的設定留在上一筆版本紀錄，報表編輯頁「版本紀錄與還原」可還原。
- reverse：把仍是本 migration 產生樣子的報表改回原本三張（順序還原、拿掉新增的圓餅），同樣留版本紀錄。
- 擴充相容：舊版程式讀到新設定只是多畫一張圓餅（設定欄位都是既有的），新版程式讀到舊設定也照常合併月份圖，
  藍綠切換前後都能看，不需要停機，也沒有要收斂的欄位。
"""
import copy

from django.db import migrations
from django.utils import timezone

TARGETS = {"electric_overview": ("電動車", "電動車銷售統計", "電車"), "gasoline_overview": ("油車", "油車銷售統計", "油車")}


def _stack(card, series):
    return (isinstance(card, dict) and card.get("chart") == "stacked" and card.get("dimension") == "month"
            and card.get("series") == series)


def _donut(card, dimension):
    return isinstance(card, dict) and card.get("chart") == "donut" and card.get("dimension") == dimension


def source_donut(vehicle):
    return {"title": f"{vehicle}銷售來源占比", "chart": "donut", "dimension": "legacy_sales_source", "metric": "count",
            "formula": "", "limit": 10, "sort": "value"}


def _target(config):
    if not isinstance(config, dict) or config.get("audience") != "admin" or config.get("reader_layout") not in TARGETS:
        return None
    vehicle, title, energy = TARGETS[config["reader_layout"]]
    if str(config.get("title", "")).split("｜")[0].strip() != title:
        return None
    if (config.get("fixed_filters") or {}).get("legacy_energy") != [energy]:
        return None
    return vehicle


def upgraded(config):
    """內建原樣的 #5／#7 設定 → B 案設定；其他（自建、改過、已升級）回傳 None。"""
    vehicle = _target(config)
    cards = config.get("cards") if vehicle else None
    if not isinstance(cards, list) or len(cards) != 3:
        return None
    source, model, donut = cards
    if not (_stack(source, "legacy_sales_source") and _stack(model, "legacy_model") and _donut(donut, "legacy_model")):
        return None
    updated = copy.deepcopy(config)
    updated["cards"] = [copy.deepcopy(model), copy.deepcopy(source), copy.deepcopy(donut), source_donut(vehicle)]
    return updated


def downgraded(config):
    """本 migration 產生的 B 案設定 → 原本三張；其他回傳 None。"""
    vehicle = _target(config)
    cards = config.get("cards") if vehicle else None
    if not isinstance(cards, list) or len(cards) != 4:
        return None
    model, source, donut, added = cards
    if not (_stack(model, "legacy_model") and _stack(source, "legacy_sales_source") and _donut(donut, "legacy_model")
            and added == source_donut(vehicle)):
        return None
    restored = copy.deepcopy(config)
    restored["cards"] = [copy.deepcopy(source), copy.deepcopy(model), copy.deepcopy(donut)]
    return restored


def _apply(apps, schema_editor, transform):
    Report = apps.get_model("sales", "ReportDefinition")
    Revision = apps.get_model("sales", "ReportRevision")
    alias = schema_editor.connection.alias
    for report in Report.objects.using(alias).select_for_update().order_by("pk"):
        current = report.published
        changed = transform(current) if current else None
        if changed is None or changed == current:
            continue
        if report.draft == current:
            report.draft = copy.deepcopy(changed)
        report.published = changed
        report.version += 1
        report.published_at = timezone.now()
        report.save(using=alias)
        Revision.objects.using(alias).create(report_id=report.pk, version=report.version, action="publish",
                                             config=copy.deepcopy(changed))


def forwards(apps, schema_editor):
    _apply(apps, schema_editor, upgraded)


def backwards(apps, schema_editor):
    _apply(apps, schema_editor, downgraded)


class Migration(migrations.Migration):
    dependencies = [("sales", "0226_t309_compulsory_insurance_gift")]
    operations = [migrations.RunPython(forwards, backwards)]
