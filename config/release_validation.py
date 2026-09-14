"""正式發布規則；不依賴 Django、資料庫或第三方套件。"""

import ast
import re
from datetime import date, datetime, timedelta, timezone


def version_tuple(value):
    # 正式上線只接受穩定版；預覽版不列入正式版本歷程。
    if not isinstance(value, str) or not re.fullmatch(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", value):
        raise ValueError("正式版號必須是無前導零的 X.Y.Z")
    return tuple(map(int, value.split(".")))


def read_literal(source, name):
    """只讀取指定常值，絕不執行基準提交內的 Python。"""
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return ast.literal_eval(node.value)
    return ()


def validate_releases(releases, legacy=(), today=None):
    today = today or datetime.now(timezone(timedelta(hours=8))).date()
    if not releases:
        raise ValueError("至少需要一筆正式版本")
    previous_version = None
    previous_date = None
    for entry in releases:
        version = version_tuple(entry["version"])
        if version[0] < 1:
            raise ValueError("正式版本由 1.0.0 起編")
        if previous_version is not None and version >= previous_version:
            raise ValueError("版號不得重複，必須由新到舊排列")
        day = date.fromisoformat(entry["date"])
        if day.isoformat() != entry["date"] or day > today or (previous_date and day > previous_date):
            raise ValueError("發布日期須為 YYYY-MM-DD、不得在未來或倒序")
        if not entry["title"].strip() or not entry["changes"]:
            raise ValueError("版本標題與更新內容不可空白")
        kinds = set()
        for group in entry["changes"]:
            if group["kind"] not in {"新增", "改善", "修正"} or group["kind"] in kinds:
                raise ValueError("更新分類須為不重複的新增／改善／修正")
            kinds.add(group["kind"])
            if not group["items"] or any(not isinstance(item, str) or not item.strip() for item in group["items"]):
                raise ValueError("更新項目不可空白")
        previous_version, previous_date = version, day
    previous_date = None
    for entry in legacy:
        day = date.fromisoformat(entry["date"])
        if day.isoformat() != entry["date"] or day > today or (previous_date and day > previous_date):
            raise ValueError("歷史提交日期無效或倒序")
        if not entry["title"].strip() or not entry["items"] or any(not item.strip() for item in entry["items"]):
            raise ValueError("歷史更新內容不可空白")
        if not entry["commits"] or any(not re.fullmatch(r"[0-9a-f]{7,40}", commit) for commit in entry["commits"]):
            raise ValueError("歷史更新必須有 Git 來源")
        previous_date = day


def validate_transition(current, previous, runtime_changed):
    if not previous:
        return
    old_by_version = {entry["version"]: entry for entry in previous}
    new_by_version = {entry["version"]: entry for entry in current}
    if any(new_by_version.get(version) != entry for version, entry in old_by_version.items()):
        raise ValueError("已發布版本不可刪除或覆寫，請新增版本")
    new, old = version_tuple(current[0]["version"]), version_tuple(previous[0]["version"])
    if new < old or (runtime_changed and new == old):
        raise ValueError("程式內容變更必須新增正式版號與更新紀錄")
    if new > old and new not in {(old[0] + 1, 0, 0), (old[0], old[1] + 1, 0), (old[0], old[1], old[2] + 1)}:
        raise ValueError("版號須依 MAJOR／MINOR／PATCH 遞增，較低位歸零")


def is_runtime_path(path):
    return (
        path.startswith(("config/", "sales/", "templates/", "static/"))
        and "/tests/" not in path
        and path.endswith((".py", ".html", ".css", ".js"))
    ) or path.startswith(("Dockerfile.django", "docker-compose.django", "requirements-django", "scripts/"))
