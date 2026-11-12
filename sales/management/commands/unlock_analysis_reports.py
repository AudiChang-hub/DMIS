"""T-151：解開大數據分析報表的車種／電車固定條件（使用者 2026-11-11 要求，僅執行一次）。

- 車型 X 性別、車型 X 顏色、性別 X 車型顏色：四張綁死 eReady 車型的圖，改成一張「依勾選車型各一張圖」範本。
- 性別 X 年齡：拿掉報表層的「型號 EV 開頭」「電車」，保留年齡口徑（age_scope）與 model_presence。

預設只列出會改什麼（dry-run）。--apply 必須同時給 --backup，先把原設定寫成 JSON 再改；
寫入走與設計器「發布」相同的檢查（validate_config、實際查詢一次），版本加一並留下 ReportRevision。
--restore 用備份 JSON 寫回原設定（同樣版本加一、留下紀錄）。其他群組的報表一律不動。
"""
import copy
import json
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from sales.reporting.engine import base_query, validate_config
from sales.reporting.models import ReportDefinition, ReportRevision
from sales.reporting.records import record_context
from sales.reporting.tree_filter import PER_MODEL_LIMIT, expand_cards
from sales.reporting.views import results

PER_MODEL_TITLES = ("車型 X 性別", "車型 X 顏色", "性別 X 車型顏色")
AGE_TITLE = "性別 X 年齡"
CAR_SCOPES = ("model_prefix", "legacy_energy")
PER_MODEL_INTRO = f"依右側「車型篩選」勾選的車型，每款一張圖，台數由多到少，最多 {PER_MODEL_LIMIT} 張。"
AGE_OLD = "其餘保留 EV 開頭、電車及 20 歲以上條件"
AGE_NEW = "保留 20 歲以上條件，涵蓋全部車種與能源（含油車）"


def unlocked(config):
    """回傳解開後的設定；已解開或不是預期的原設定時回傳 None。"""
    title = config.get("title")
    if config.get("navigation_group") != "analysis":
        return None
    new = copy.deepcopy(config)
    if title in PER_MODEL_TITLES:
        cards = config.get("cards", [])
        if len(cards) != 4 or not all(card.get("fixed_filters") for card in cards):
            return None
        template = copy.deepcopy(cards[0])
        template.pop("fixed_filters", None)
        template["title"] = template["title"].split("－", 1)[-1]
        template["per_model"] = True
        new["cards"] = [template]
        rest = config.get("description", "").split("。", 1)[-1].strip()
        new["description"] = (PER_MODEL_INTRO + rest)[:1000]
        return new
    if title == AGE_TITLE:
        scope = config.get("fixed_filters", {})
        if not any(scope.get(key) for key in CAR_SCOPES):
            return None
        new["fixed_filters"] = {key: value for key, value in scope.items() if key not in CAR_SCOPES}
        description = config.get("description", "")
        new["description"] = (description.replace(AGE_OLD, AGE_NEW) if AGE_OLD in description
                              else description + AGE_NEW + "。")[:1000]
        return new
    return None


def coverage(config):
    expanded, _ = expand_cards(config, {})
    total = base_query(expanded, {}).count()
    pks = set()
    for card in expanded["cards"]:
        pks.update(base_query(expanded, {}, card).values_list("pk", flat=True))
    return len(pks), total


class Command(BaseCommand):
    help = "解開大數據分析報表的車種／電車固定條件（預設 dry-run；--apply 需 --backup；--restore 還原）"

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="實際寫入（需同時指定 --backup）")
        parser.add_argument("--backup", help="寫入前匯出原設定的 JSON 路徑（不可已存在）")
        parser.add_argument("--restore", help="用先前的備份 JSON 寫回原設定")

    def handle(self, *args, **options):
        admin = get_user_model().objects.filter(username="admin", is_active=True, is_superuser=True).first()
        if options["restore"]:
            return self.restore(Path(options["restore"]), admin, options["apply"])
        targets = []
        for report in ReportDefinition.objects.filter(published__isnull=False).order_by("pk"):
            new = unlocked(report.published)
            if new is None:
                continue
            if report.draft != report.published:
                self.stdout.write(f"#{report.pk} {report.published['title']}：草稿與發布版本不同，略過，請先在設計器處理。")
                continue
            targets.append((report, new))
        if not targets:
            self.stdout.write("沒有需要解開的大數據分析報表（可能已經解開過）。")
            return
        for report, new in targets:
            before, after = coverage(report.published), coverage(new)
            self.stdout.write(f"#{report.pk} {report.published['title']} v{report.version}")
            self.stdout.write(f"  報表固定條件：{json.dumps(report.published.get('fixed_filters', {}), ensure_ascii=False)}"
                              f" → {json.dumps(new.get('fixed_filters', {}), ensure_ascii=False)}")
            self.stdout.write(f"  圖卡：{[card['title'] for card in report.published['cards']]} → "
                              f"{[card['title'] + ('（依勾選車型展開）' if card.get('per_model') else '') for card in new['cards']]}")
            self.stdout.write(f"  圖表涵蓋訂單：{before[0]}／{before[1]} → {after[0]}／{after[1]}")
        if not options["apply"]:
            self.stdout.write("dry-run：未寫入。確認後加 --apply --backup <路徑> 執行。")
            return
        if not options["backup"]:
            raise CommandError("--apply 需要 --backup，先匯出原設定。")
        if not admin:
            raise CommandError("找不到有效的 admin 管理者。")
        backup = Path(options["backup"])
        if backup.exists():
            raise CommandError(f"{backup} 已存在，請換一個檔名，避免覆蓋先前的備份。")
        backup.parent.mkdir(parents=True, exist_ok=True)
        backup.write_text(json.dumps([{
            "pk": report.pk, "version": report.version, "draft": report.draft, "published": report.published,
            "published_at": report.published_at.isoformat() if report.published_at else None,
        } for report, _ in targets], ensure_ascii=False, indent=2), encoding="utf-8")
        self.stdout.write(f"已備份 {len(targets)} 份原設定：{backup}")
        with transaction.atomic():
            for report, new in targets:
                self.publish(report.pk, report.version, new, admin, "publish")
        self.stdout.write(f"已解開 {len(targets)} 份報表並重新發布（ReportRevision 已記錄）。")

    def publish(self, pk, version, config, admin, action):
        report = ReportDefinition.objects.select_for_update().get(pk=pk)
        if report.version != version:
            raise CommandError(f"#{pk} 版本已變更（{version} → {report.version}），全部不寫入，請重新檢查。")
        try:
            validate_config(config)
            # 與設計器發布相同：實際查一次，無效設定不進讀者版本。
            expanded, _ = expand_cards(config, {})
            results(expanded, {})
            if config.get("include_records"):
                record_context(expanded, {})
        except ValidationError as error:
            raise CommandError(f"#{pk} 新設定驗證失敗：{'；'.join(error.messages)}")
        report.draft = copy.deepcopy(config)
        report.published = copy.deepcopy(config)
        report.published_at = timezone.now()
        report.version += 1
        report.save()
        ReportRevision.objects.create(report=report, version=report.version, action=action, config=config, actor=admin)

    def restore(self, path, admin, apply):
        rows = json.loads(path.read_text(encoding="utf-8"))
        for row in rows:
            report = ReportDefinition.objects.get(pk=row["pk"])
            self.stdout.write(f"#{report.pk} {report.published.get('title') if report.published else ''} v{report.version} → 還原為備份時的 v{row['version']} 設定")
        if not apply:
            self.stdout.write("dry-run：未寫入。確認後加 --apply 執行還原。")
            return
        if not admin:
            raise CommandError("找不到有效的 admin 管理者。")
        with transaction.atomic():
            for row in rows:
                current = ReportDefinition.objects.get(pk=row["pk"]).version
                self.publish(row["pk"], current, row["published"], admin, "restore")
        self.stdout.write(f"已還原 {len(rows)} 份報表。")
