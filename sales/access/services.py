from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import ReportAccessGrant, ScreenAccessGrant, UserAccessRevision, UserAccessState
from .registry import BY_KEY, LOOKUPS, MEDIA_SCREENS, PERSONAL, REPORT_ROUTES, ROOT_ONLY, ROUTES, SCREENS, TOGGLE_RESOURCES


def is_root(user):
    return bool(user.is_authenticated and user.is_active and user.is_superuser and user.get_username() == "admin")


def report_ceiling(user, report, *, include_inactive=False):
    config = report.published
    return bool(user.is_authenticated and (user.is_active or include_inactive) and config and ((user.is_superuser and user.get_username() == "admin") or (
        config.get("audience") == "team" and config.get("records_mode") != "population"
        and "legacy_notes" not in config.get("records_columns", [])
    )))


class AccessPolicy:
    """只在單次請求保留，撤權不依賴 session 或全域快取失效。"""
    def __init__(self, user):
        self.user = user
        self.root = is_root(user)
        self.active = bool(user.is_authenticated and user.is_active)
        state = UserAccessState.objects.filter(user_id=user.pk).first() if user.is_authenticated else None
        self.configured = bool(state and state.configured)
        self.version = state.version if state else 0
        self.screens = {}
        self.reports = {}
        self._report_definitions = {}
        if self.configured and not self.root:
            self.screens = {row["screen_key"]: row for row in ScreenAccessGrant.objects.filter(user=user).values("screen_key", "view", "operate", "export")}
            self.reports = {row["report_id"]: row for row in ReportAccessGrant.objects.filter(user=user).values("report_id", "view", "export")}

    def screen(self, key, action="view"):
        screen = BY_KEY.get(key)
        if not self.active or not screen or action not in {"view", "operate", "export"}:
            return False
        if screen.ceiling == "superuser" and not self.user.is_superuser:
            return False
        if action != "view" and not getattr(screen, action):
            return False
        if self.root or not self.configured:
            return True
        grant = self.screens.get(key, {})
        return bool(grant.get("view") and grant.get(action))

    def report(self, report, action="view"):
        if not report_ceiling(self.user, report):
            return False
        if self.root or not self.configured:
            return True
        grant = self.reports.get(report.pk, {})
        return bool(grant.get("view") and grant.get(action))

    def route(self, name, method="GET", kwargs=None):
        kwargs = kwargs or {}
        if name in PERSONAL:
            return True
        if not self.active:
            return False
        if self.root:
            return True
        if name in ROOT_ONLY:
            return self.root
        if name in {"data_maintenance", "report_center"}:
            # 空白目錄是安全入口；實際項目仍依個別授權過濾。
            return True
        if name in REPORT_ROUTES:
            from sales.reporting.models import ReportDefinition
            pk = kwargs.get("pk")
            if pk not in self._report_definitions:
                self._report_definitions[pk] = ReportDefinition.objects.filter(pk=pk).first()
            report = self._report_definitions[pk]
            return bool(report and self.report(report, REPORT_ROUTES[name]))
        if name in LOOKUPS:
            return method in {"GET", "HEAD", "OPTIONS"} and any(self.screen(key) for key in LOOKUPS[name])
        if name == "master_record_set_active":
            return self.screen(TOGGLE_RESOURCES.get(kwargs.get("resource")), "operate")
        if name == "protected_media":
            return self.screen(MEDIA_SCREENS.get(kwargs.get("model_name")))
        entry = ROUTES.get(name)
        if not entry:
            return self.root or not self.configured
        key, action = entry
        if action == "auto":
            action = "view" if method in {"GET", "HEAD", "OPTIONS"} else "operate"
        return self.screen(key, action)


def policy_for(request):
    if not hasattr(request, "_screen_access_policy"):
        request._screen_access_policy = AccessPolicy(request.user)
    return request._screen_access_policy


def snapshot(user, reports):
    policy = AccessPolicy(user)
    # 停用只使權限無效，不清除已保存的勾選；admin 可先設定再啟用帳號。
    if policy.configured and not policy.root:
        data = {"screens": policy.screens, "reports": {str(key): grant for key, grant in policy.reports.items()}}
    else:
        data = {"screens": {s.key: {a: True for a in ("view", "operate", "export")} for s in SCREENS},
                "reports": {str(r.pk): {"view": True, "export": True} for r in reports}}
    return {"configured": policy.configured, "version": policy.version, **normalize(user, data, reports)}


def normalize(user, data, reports):
    """從舊歷程或複製來源還原也要重驗目前能力與敏感資料上限。"""
    result = {"screens": {}, "reports": {}}
    for screen in SCREENS:
        grant = data.get("screens", {}).get(screen.key, {})
        view = grant.get("view") is True and (screen.ceiling != "superuser" or user.is_superuser)
        result["screens"][screen.key] = {"view": view,
            "operate": view and screen.operate and grant.get("operate") is True,
            "export": view and screen.export and grant.get("export") is True}
    for report in reports:
        grant = data.get("reports", {}).get(str(report.pk), {})
        view = grant.get("view") is True and report_ceiling(user, report, include_inactive=True)
        result["reports"][str(report.pk)] = {"view": view, "export": view and grant.get("export") is True}
    return result


@transaction.atomic
def apply_policy(*, actor, user, expected_version, data, reports):
    if not is_root(actor) or is_root(user):
        raise ValidationError("只有 admin 可設定人員畫面權限；admin 本身權限固定。")
    # 先鎖 user，連尚無 state 的首次儲存也可避免兩視窗競爭建立。
    user = get_user_model().objects.select_for_update().get(pk=user.pk)
    if is_root(user):
        raise ValidationError("admin 本身權限固定。")
    state, _ = UserAccessState.objects.get_or_create(user=user)
    if state.version != expected_version:
        raise ValidationError("此人員權限已被另一個視窗更新，請重新載入再預覽；本次未覆寫。")
    normalized = normalize(user, data, reports)
    if normalized != data:
        raise ValidationError("帳號資格或報表清單已變更，請重新預覽。")
    before = snapshot(user, reports)
    ScreenAccessGrant.objects.filter(user=user).delete()
    ReportAccessGrant.objects.filter(user=user).delete()
    ScreenAccessGrant.objects.bulk_create([ScreenAccessGrant(user=user, screen_key=key, **grant) for key, grant in normalized["screens"].items() if grant["view"]])
    ReportAccessGrant.objects.bulk_create([ReportAccessGrant(user=user, report_id=key, **grant) for key, grant in normalized["reports"].items() if grant["view"]])
    state.configured = True
    state.version += 1
    state.updated_at = timezone.now()
    state.save(update_fields=["configured", "version", "updated_at"])
    UserAccessRevision.objects.create(user=user, version=state.version, before=before, after=normalized,
                                      actor=actor, actor_name=actor.get_username())
    return state.version
