from django.apps import apps
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, models, transaction

# 帳號、權限、門市與系統參照資料；其餘 sales 資料（含主檔）全部清除。
KEEP_MODELS = {
    "UserAccessState",
    "ScreenAccessGrant",
    "ReportAccessGrant",
    "UserAccessRevision",
    "UserSecurityProfile",
    "UserAccountAuditLog",
    "UserAppearancePreference",
    "OrderAccountProfile",
    "ReportDefinition",
    "ReportRevision",
    "ReportClassification",
    "ReportClassificationRevision",
    "ReleasePublication",
    "SalesSourceCategory",
    "BusinessHoliday",
    "Store",
    "PrintCompany",
}
# 保留列指向將清除資料的欄位，清除前先改為空白。
DETACHED_FIELDS = {("OrderAccountProfile", "source"), ("PrintCompany", "source")}
CONFIRM_PHRASE = "清除全部業務資料"


def models_to_clear():
    cleared = []
    for model in apps.get_models(include_auto_created=True):
        if model._meta.app_label != "sales":
            continue
        owner = model._meta.auto_created or model
        if owner.__name__ in KEEP_MODELS:
            continue
        cleared.append(model)
    kept = [m for m in apps.get_models(include_auto_created=True) if m not in cleared]
    for model in kept:
        for field in model._meta.concrete_fields:
            if (
                field.is_relation
                and field.related_model in cleared
                and (model.__name__, field.name) not in DETACHED_FIELDS
            ):
                raise CommandError(f"保留的 {model.__name__}.{field.name} 參照將清除的 {field.related_model.__name__}")
    admin_log = apps.get_model("admin", "LogEntry")
    return cleared + [admin_log]


def referenced_files(cleared):
    names = set()
    for model in cleared:
        file_fields = [f.name for f in model._meta.concrete_fields if isinstance(f, models.FileField)]
        for field in file_fields:
            names.update(
                value for value in model._default_manager.exclude(**{field: ""}).values_list(field, flat=True) if value
            )
    return names


def detach_kept_rows():
    """車行帳號失去所屬車行後停用，待重新綁定再啟用；車行的訂購單公司隨車行清除。"""
    from django.contrib.auth import get_user_model

    from sales.models import OrderAccountProfile, PrintCompany, UserAccountAuditLog

    dealer_profiles = OrderAccountProfile.objects.filter(kind="dealer").select_related("user")
    deactivated = []
    for profile in dealer_profiles:
        user = profile.user
        if user.is_active:
            get_user_model().objects.filter(pk=user.pk).update(is_active=False)
            UserAccountAuditLog.objects.create(
                target=user,
                target_username=user.get_username(),
                action=UserAccountAuditLog.Action.DEACTIVATE,
                description="清除業務資料：所屬車行已清除，重新綁定車行後再啟用。",
            )
            deactivated.append(user.get_username())
    OrderAccountProfile.objects.filter(order_scope="dealer").update(order_scope="own")
    for profile in OrderAccountProfile.objects.exclude(source=None):
        profile.source = None
        profile.save(update_fields=["source"])
    dealer_companies = PrintCompany.objects.exclude(source=None)
    dealer_companies._raw_delete(dealer_companies.db)
    return deactivated


class Command(BaseCommand):
    help = "清除全部業務與主檔資料（訂單、庫存、主檔、匯入、附件），只保留帳號、權限、門市與系統參照資料。預設只預覽。"

    def add_arguments(self, parser):
        parser.add_argument("--confirm", default="", help=f"須輸入「{CONFIRM_PHRASE}」才會執行")

    def handle(self, *args, **options):
        cleared = models_to_clear()
        counts = {m._meta.db_table: m._default_manager.count() for m in cleared}
        for table, count in sorted(counts.items()):
            if count:
                self.stdout.write(f"{table}\t{count}")
        self.stdout.write(f"共 {sum(counts.values())} 筆、{sum(1 for c in counts.values() if c)} 個資料表")
        if options["confirm"] != CONFIRM_PHRASE:
            self.stdout.write(self.style.WARNING(f"預覽模式；執行請加 --confirm {CONFIRM_PHRASE}"))
            return

        files = referenced_files(cleared)
        quote = connection.ops.quote_name
        with transaction.atomic():
            with connection.constraint_checks_disabled():
                deactivated = detach_kept_rows()
                with connection.cursor() as cursor:
                    for model in cleared:
                        cursor.execute(f"DELETE FROM {quote(model._meta.db_table)}")
            connection.check_constraints()

        from django.core.files.storage import default_storage

        removed = 0
        for name in sorted(files):
            if default_storage.exists(name):
                default_storage.delete(name)
                removed += 1
        if deactivated:
            self.stdout.write(f"已停用車行帳號（需重新綁定車行）：{'、'.join(deactivated)}")
        self.stdout.write(self.style.SUCCESS(f"已清除 {sum(counts.values())} 筆資料、{removed} 個附件檔"))
