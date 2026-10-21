"""檢查 migration 能否在舊版程式仍上線時先套用（藍綠部署「先擴充、後收斂」規則）。

藍綠部署會先套用 migration、再把流量切到新版；這幾秒內舊版仍在讀寫資料庫。
刪除／改名欄位或資料表、新增沒有資料庫預設值的必填欄位，都會讓舊版出錯，
這類 migration 會被標成不相容，部署腳本改用短暫停機部署。

代碼：0＝相容（或沒有待套用的 migration）、3＝不相容。
確認上一版已不再使用時（收斂步驟），可在該 Migration 類別加 `zero_downtime_safe = True`。
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import DEFAULT_DB_ALIAS, connections
from django.db.migrations import operations as ops
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.loader import MigrationLoader
from django.db.models.fields import NOT_PROVIDED

INCOMPATIBLE_EXIT_CODE = 3

# 不改既有欄位／資料表結構，或只新增舊版不會碰到的東西。
SAFE_OPERATIONS = (
    ops.CreateModel,
    ops.AddIndex,
    ops.RemoveIndex,
    ops.RenameIndex,
    ops.AddConstraint,
    ops.RemoveConstraint,
    ops.AlterModelOptions,
    ops.AlterModelManagers,
    ops.AlterModelTableComment,
    ops.AlterUniqueTogether,
    ops.AlterIndexTogether,
    ops.RunPython,
)

BREAKING_OPERATIONS = {
    ops.RemoveField: "刪除欄位，舊版仍會讀寫它",
    ops.RenameField: "欄位改名，舊版仍用舊名稱",
    ops.DeleteModel: "刪除資料表，舊版仍會讀寫它",
    ops.RenameModel: "資料表改名，舊版仍用舊名稱",
    ops.AlterModelTable: "資料表改名，舊版仍用舊名稱",
    ops.AlterOrderWithRespectTo: "新增或刪除排序欄位",
    ops.RunSQL: "自訂 SQL 無法自動判斷",
}


def _has_db_default(field):
    return getattr(field, "db_default", NOT_PROVIDED) is not NOT_PROVIDED


def _required_without_db_default(field):
    return not (field.null or field.many_to_many or _has_db_default(field) or field.generated)


def _field_issue(operation, app_label, state):
    model_key = (app_label, operation.model_name_lower)
    if isinstance(operation, ops.AddField):
        if _required_without_db_default(operation.field):
            return "新增必填欄位卻沒有 db_default，舊版新增資料會失敗"
        return None
    # AlterField：只擋會讓舊版讀寫失敗的改變；選項文字、說明、長度放寬都不影響。
    old = state.models[model_key].fields[operation.name]
    new = operation.field
    if old.null and not new.null and not _has_db_default(new):
        return "欄位改成必填卻沒有 db_default，舊版寫入空值會失敗"
    if old.db_column != new.db_column:
        return "欄位的資料庫名稱改變，舊版仍用舊名稱"
    if old.get_internal_type() != new.get_internal_type():
        return f"欄位型別由 {old.get_internal_type()} 改成 {new.get_internal_type()}"
    return None


def operation_issues(operation, app_label, state, created_models):
    """回傳這個 operation 與舊版不相容的原因；相容回傳空清單。"""
    if isinstance(operation, ops.SeparateDatabaseAndState):
        issues = []
        for inner in operation.database_operations:
            issues.extend(operation_issues(inner, app_label, state, created_models))
        return issues
    model_name = getattr(operation, "model_name_lower", None) or getattr(operation, "name_lower", None)
    if (app_label, model_name) in created_models:
        return []  # 同一批新建的資料表，舊版不會用到。
    if isinstance(operation, (ops.AddField, ops.AlterField)):
        issue = _field_issue(operation, app_label, state)
        return [issue] if issue else []
    if isinstance(operation, SAFE_OPERATIONS):
        return []
    for operation_type, reason in BREAKING_OPERATIONS.items():
        if isinstance(operation, operation_type):
            return [reason]
    return [f"{type(operation).__name__} 無法自動判斷"]


def migration_issues(loader, keys):
    """依序檢查多個 migration；回傳 [(migration key, operation 描述, 原因), …]。"""
    issues = []
    created_models = set()
    for key in keys:
        migration = loader.graph.nodes[key]
        if getattr(migration, "zero_downtime_safe", False):
            continue
        app_label = migration.app_label
        state = loader.project_state(key, at_end=False)
        for operation in migration.operations:
            for reason in operation_issues(operation, app_label, state, created_models):
                issues.append((key, operation.describe(), reason))
            if isinstance(operation, ops.CreateModel):
                created_models.add((app_label, operation.name_lower))
            operation.state_forwards(app_label, state)
    return issues


class Command(BaseCommand):
    help = "檢查待套用（或指定）的 migration 是否能在舊版仍上線時先套用"

    def add_arguments(self, parser):
        parser.add_argument(
            "migrations",
            nargs="*",
            help="指定 app_label.migration_name；省略時檢查資料庫尚未套用的 migration",
        )

    def handle(self, *args, **options):
        if options["migrations"]:
            loader = MigrationLoader(None, ignore_no_migrations=True)
            keys = []
            for label in options["migrations"]:
                app_label, _, name = label.partition(".")
                key = (app_label, name)
                if key not in loader.graph.nodes:
                    raise CommandError(f"找不到 migration：{label}")
                keys.append(key)
        else:
            executor = MigrationExecutor(connections[DEFAULT_DB_ALIAS])
            loader = executor.loader
            plan = executor.migration_plan(loader.graph.leaf_nodes())
            keys = [(migration.app_label, migration.name) for migration, backwards in plan if not backwards]

        if not keys:
            self.stdout.write("沒有待套用的 migration。")
            return
        issues = migration_issues(loader, keys)
        if not issues:
            self.stdout.write(f"{len(keys)} 個 migration 皆可在舊版上線時先套用。")
            return
        self.stdout.write(f"{len(issues)} 項與舊版不相容（需短暫停機部署）：")
        for (app_label, name), description, reason in issues:
            self.stdout.write(f"- {app_label}.{name}：{description}｜{reason}")
        raise SystemExit(INCOMPATIBLE_EXIT_CODE)
