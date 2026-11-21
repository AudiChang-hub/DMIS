"""T-268：大數據分析新增已發布報表「車型 顏色 vs 年齡分布」（使用者 2026-11-21 同意寫入這一筆報表設定）。

- 只新增一筆 ReportDefinition（＋一筆 publish 版本紀錄），不動其他報表、訂單或財務資料。
- 已有同名報表（草稿或發布）就略過，不覆蓋。
- 沒有啟用中的 admin 管理者（新建或測試資料庫）時不建立：這份報表只開放給 admin，與 create_source_report_draft 相同條件；
  正式站有 admin。若部署後未出現，可用 `manage.py create_source_report_draft --page model-color-age` 補建草稿再發布。
- reverse 只刪這個 migration 建立、而且之後沒有再存過的那一筆（版本仍為 1、唯一的紀錄是本 migration 的 publish）；
  已被管理者改過或手動建立的同名報表保留。
- 設定是寫入當下的快照（與 sales.reporting.source_templates.model_color_age_analysis 相同，測試核對），
  之後改範本不會回頭改這筆資料。不需要停機：新維度只在新版程式讀取，藍綠切換前舊版看到這份報表會顯示設定錯誤，切換後正常。
"""
import copy

from django.conf import settings
from django.db import migrations
from django.utils import timezone

CONFIG = {
    "title": "車型 顏色 vs 年齡分布",
    "audience": "admin",
    "date_basis": "registration_date",
    "description": ("每一列是一個車型的一個顏色，依年齡層分段，看哪些車型的哪些顏色集中在哪些年齡。"
                    "同一車型各年式合併計算，同一廣告色依年式分開的色碼也合併。"
                    "年齡為當年度減出生年度；生日未填、生日異常、公司或其他獨立列示。"
                    "不含草稿及取消、待退款、例外結案的訂單；可用領牌年月選期間，或在車型篩選只看部分車型。"),
    "include_undated": True,
    "navigation_group": "analysis",
    "page_order": 140,
    "reader_layout": "analysis_overview",
    "fixed_filters": {"model_presence": ["present"]},
    "cards": [{"title": "車型顏色 × 年齡層", "chart": "stacked", "dimension": "family_color", "series": "age_group",
               "metric": "count", "formula": "", "limit": 200, "sort": "key", "series_sort": "key", "width": 12}],
}


def _same_title(Report, alias):
    return [report for report in Report.objects.using(alias).all()
            if (report.draft or {}).get("title") == CONFIG["title"] or (report.published or {}).get("title") == CONFIG["title"]]


def create_report(apps, schema_editor):
    Report = apps.get_model("sales", "ReportDefinition")
    Revision = apps.get_model("sales", "ReportRevision")
    alias = schema_editor.connection.alias
    User = apps.get_model(*settings.AUTH_USER_MODEL.split("."))
    if not User.objects.using(alias).filter(username="admin", is_active=True, is_superuser=True).exists():
        return
    if _same_title(Report, alias):
        return
    report = Report.objects.using(alias).create(draft=copy.deepcopy(CONFIG), published=copy.deepcopy(CONFIG), version=1,
                                                published_at=timezone.now())
    Revision.objects.using(alias).create(report_id=report.pk, version=1, action="publish", config=copy.deepcopy(CONFIG))


def remove_report(apps, schema_editor):
    Report = apps.get_model("sales", "ReportDefinition")
    Revision = apps.get_model("sales", "ReportRevision")
    alias = schema_editor.connection.alias
    for report in _same_title(Report, alias):
        revisions = list(Revision.objects.using(alias).filter(report_id=report.pk))
        untouched = (report.version == 1 and report.draft == CONFIG and report.published == CONFIG and len(revisions) == 1
                     and revisions[0].action == "publish" and revisions[0].actor_id is None and revisions[0].config == CONFIG)
        if untouched:
            report.delete()


class Migration(migrations.Migration):
    dependencies = [("sales", "0221_t257_discount_internal_note"), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [migrations.RunPython(create_report, remove_report)]
