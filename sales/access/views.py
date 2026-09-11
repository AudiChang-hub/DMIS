from functools import wraps

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from sales.reporting.models import ReportDefinition
from .models import UserAccessRevision
from .registry import SCREENS, SCREEN_GROUPS
from .services import AccessPolicy, apply_policy, is_root, normalize, policy_for, snapshot

SALT = "dmis.screen-access.preview.v1"


def positive_id(value):
    if not value or not value.isascii() or not value.isdigit() or len(value) > 18:
        raise ValidationError("請選擇有效的人員或版本。")
    return int(value)


def root_required(view):
    @wraps(view)
    @login_required
    @never_cache
    def wrapped(request, *args, **kwargs):
        if not is_root(request.user):
            raise PermissionDenied
        return view(request, *args, **kwargs)
    return wrapped


@login_required
@never_cache
def home(request):
    policy = policy_for(request)
    links = [s for s in SCREENS if s.key != "work" and policy.screen(s.key) and policy.route(s.route)]
    return render(request, "sales/access/home.html", {"access_links": links})


@root_required
def overview(request):
    accounts = get_user_model().objects.order_by("-is_active", "username")
    query = request.GET.get("q", "").strip()
    if query:
        from django.db.models import Q
        accounts = accounts.filter(Q(username__icontains=query) | Q(first_name__icontains=query))
    reports = list(ReportDefinition.objects.filter(published__isnull=False))
    rows = []
    for user in accounts:
        policy = AccessPolicy(user)
        rows.append({"account": user, "root": policy.root, "configured": policy.configured, "version": policy.version,
                     "screens": sum(policy.screen(s.key) for s in SCREENS),
                     "reports": sum(policy.report(r) for r in reports)})
    return render(request, "sales/access/overview.html", {"rows": rows, "query": query})


def rows_for(user, data, before, reports):
    rows = []
    for screen in SCREENS:
        rows.append({"key": screen.key, "kind": "screens", "label": screen.label,
                     "eligible": True,
                     "operate": screen.operate, "export": screen.export})
    for report in reports:
        rows.append({"key": str(report.pk), "kind": "reports", "label": report.published.get("title", "未命名報表"),
                     "eligible": True, "operate": False, "export": True,
                     "section": report.published.get("navigation_group", "custom")})
    for row in rows:
        current = before.get(row["kind"], {}).get(row["key"], {})
        proposed = data.get(row["kind"], {}).get(row["key"], {})
        row["changed"] = current != proposed
        row["cells"] = [{"name": f'{row["kind"]}.{row["key"]}.{action}', "action": action, "label": label,
                         "supported": True, "checked": proposed.get(action, False),
                         "before": current.get(action, False)}
                        for action, label in (("view", "查看"), ("operate", "操作"), ("export", "匯出／列印"))]
    return rows


def grouped_rows(rows):
    from sales.reporting.engine import NAVIGATION_GROUPS
    by_key = {row["key"]: row for row in rows if row["kind"] == "screens"}
    result = []
    for key, label, sections in SCREEN_GROUPS:
        if key == "reports":
            groups = [{"label": name, "rows": [row for row in rows if row["kind"] == "reports" and row["section"] == group]}
                      for group, name in NAVIGATION_GROUPS.items()]
        else:
            groups = [{"label": name, "rows": [by_key[item] for item in keys]} for name, keys in sections]
        result.append({"key": key, "label": label, "sections": [group for group in groups if group["rows"]]})
    return result


@root_required
@require_http_methods(["GET", "POST"])
def edit(request, pk):
    account = get_object_or_404(get_user_model(), pk=pk)
    if account.get_username() == "admin":
        messages.info(request, "admin 權限固定，不可取消或複製覆蓋。")
        return redirect("access_overview")
    reports = list(ReportDefinition.objects.filter(published__isnull=False).order_by("pk"))
    before = snapshot(account, reports)
    draft = normalize(account, before, reports)
    preview = False
    token = ""
    error = ""
    status = 200
    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "apply":
                try:
                    payload = signing.loads(request.POST.get("preview_token", ""), salt=SALT, max_age=1800)
                except signing.BadSignature as exc:
                    raise ValidationError("預覽已逾時或內容不正確，請重新預覽。") from exc
                if payload.get("user") != account.pk or payload.get("actor") != request.user.pk:
                    raise PermissionDenied
                apply_policy(actor=request.user, user=account, expected_version=payload["version"], data=payload["draft"], reports=reports)
                messages.success(request, "畫面權限已套用，該人員下一次請求即生效。")
                return redirect("access_edit", pk=account.pk)
            if action == "copy":
                source = get_object_or_404(get_user_model(), pk=positive_id(request.POST.get("source")))
                if is_root(source):
                    raise ValidationError("不可複製 admin 的固定最高權限。")
                draft = normalize(account, snapshot(source, reports), reports)
            elif action == "restore":
                revision = get_object_or_404(UserAccessRevision, pk=positive_id(request.POST.get("revision")), user=account)
                draft = normalize(account, revision.after, reports)
            elif action == "preview":
                draft = {"screens": {}, "reports": {}}
                for kind, keys in (("screens", [s.key for s in SCREENS]), ("reports", [str(r.pk) for r in reports])):
                    for key in keys:
                        draft[kind][key] = {a: request.POST.get(f"{kind}.{key}.{a}") == "on" for a in ("view", "operate", "export")}
                draft = normalize(account, draft, reports)
            elif action == "back":
                payload = signing.loads(request.POST.get("preview_token", ""), salt=SALT, max_age=1800)
                if payload.get("user") != account.pk or payload.get("actor") != request.user.pk:
                    raise PermissionDenied
                draft = normalize(account, payload["draft"], reports)
            else:
                raise ValidationError("請使用預覽與確認按鈕。")
            if action != "back":
                if str(before["version"]) != request.POST.get("version"):
                    raise ValidationError("此人員權限已更新，請重新載入後再預覽。")
                preview = True
                token = signing.dumps({"actor": request.user.pk, "user": account.pk, "version": before["version"], "draft": draft}, salt=SALT, compress=True)
        except (ValidationError, signing.BadSignature) as exc:
            error = "；".join(exc.messages) if isinstance(exc, ValidationError) else "預覽已逾時，請重新操作。"
            status = 409
    rows = rows_for(account, draft, before, reports)
    revisions = list(account.access_revisions.select_related("actor")[:20])
    for revision in revisions:
        revision.changes = [row for row in rows_for(account, revision.after, revision.before, reports) if row["changed"]]
    return render(request, "sales/access/edit.html", {
        "account": account, "before": before, "rows": rows, "groups": grouped_rows(rows), "preview": preview, "preview_token": token,
        "error": error, "changed_count": sum(row["changed"] for row in rows),
        "visible_rows": [r for r in rows if r["cells"][0]["checked"]],
        "copy_accounts": get_user_model().objects.exclude(pk=account.pk).exclude(username="admin").order_by("username"),
        "revisions": revisions,
    }, status=status)
