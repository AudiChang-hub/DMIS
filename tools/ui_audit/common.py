"""UI 量測工具共用：暫存資料庫＋合成資料、示範伺服器、登入、爬路由（T-242）。

全程只用 seed_help_demo 的合成資料與 tmp/ 下的暫存 SQLite，不連正式資料庫、不碰專案的 db.sqlite3。
不進 CI；在本機手動執行。
"""
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from collections import deque
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse

ROOT = Path(__file__).resolve().parents[2]
SERVE = ROOT / "tools" / "help_screens" / "serve.py"
SETTINGS = '''from config.settings import *  # noqa: F401,F403
DATABASES = {{"default": {{"ENGINE": "django.db.backends.sqlite3", "NAME": r"{db}"}}}}
MEDIA_ROOT = r"{media}"
ALLOWED_HOSTS = ["127.0.0.1", "localhost", "testserver"]
'''
THEMES = ("professional", "night-blue", "deep-blue", "graphite-gold", "bright-indigo", "high-contrast")
# 不爬的網址：登出、下載與匯出、列印 PDF、外部轉址、Django admin、媒體與靜態檔。
SKIP = ("logout", "export", "download", ".pdf", "/pdf/", "csv", "xlsx", "/media/", "/static/", "/admin/",
        "/parts/suzuki/", "/print/file", "/backup")


def env_for(work):
    return {**{k: v for k, v in os.environ.items() if k != "POSTGRES_HOST"},
            "PYTHONPATH": str(work / "settings"), "PYTHONUTF8": "1", "DJANGO_SETTINGS_MODULE": "help_demo_settings"}


def prepare(work, *, fresh=True):
    """建立暫存資料庫與合成資料；fresh=False 時沿用上次的（省時間）。"""
    env = env_for(work)
    if fresh or not (work / "demo.sqlite3").exists():
        if work.exists():
            shutil.rmtree(work)
        (work / "settings").mkdir(parents=True)
        (work / "settings" / "help_demo_settings.py").write_text(
            SETTINGS.format(db=work / "demo.sqlite3", media=work / "media"), encoding="utf-8")
        password = os.urandom(12).hex()  # 只存在這個暫存資料庫
        run_env = {**env, "HELP_DEMO_ADMIN_PASSWORD": password}
        manage = [sys.executable, "manage.py"]
        subprocess.run([*manage, "migrate", "-v", "0"], cwd=ROOT, env=run_env, check=True)
        subprocess.run([*manage, "seed_help_demo", "--confirm-demo-database"], cwd=ROOT, env=run_env, check=True)
        subprocess.run([*manage, "seed_help_demo", "--confirm-demo-database", "--manage"], cwd=ROOT, env=run_env, check=True)
    return env


def session_key(env):
    """直接替 admin 建一個登入 session（不用輸入密碼）。"""
    code = ("from django.contrib.sessions.backends.db import SessionStore;"
            "from django.contrib.auth import get_user_model, SESSION_KEY, BACKEND_SESSION_KEY, HASH_SESSION_KEY;"
            "u=get_user_model().objects.get(username='admin');s=SessionStore();s[SESSION_KEY]=str(u.pk);"
            "s[BACKEND_SESSION_KEY]='django.contrib.auth.backends.ModelBackend';s[HASH_SESSION_KEY]=u.get_session_auth_hash();"
            "s.create();print(s.session_key)")
    out = subprocess.run([sys.executable, "manage.py", "shell", "-v", "0", "-c", code], cwd=ROOT, env=env,
                         check=True, capture_output=True, text=True)
    return out.stdout.strip().splitlines()[-1]


def start_server(env, port, log):
    server = subprocess.Popen([sys.executable, str(SERVE), str(port)], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
    for _ in range(240):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/login/", timeout=1)
            return server
        except OSError:
            time.sleep(0.5)
    server.terminate()
    raise RuntimeError("示範伺服器沒有啟動，請看 server.log")


def route_of(env):
    """回傳把路徑對應到 URL 樣式（例如 orders/<int:pk>/）的函式；同一樣式只爬幾頁。"""
    os.environ.update({"DJANGO_SETTINGS_MODULE": env["DJANGO_SETTINGS_MODULE"]})
    sys.path.insert(0, env["PYTHONPATH"]); sys.path.insert(0, str(ROOT))
    import django
    django.setup()
    if sys.platform == "win32":  # 專案設定會改用 selector 事件迴圈，Playwright 在 Windows 需要 proactor 才能啟動瀏覽器
        import asyncio
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    from django.urls import Resolver404, resolve

    def route(path):
        try:
            match = resolve(path)
        except Resolver404:
            return None
        return match.route or match.url_name
    return route


def crawl(page, base, route, *, start=("/", "/data/", "/orders/", "/reports/", "/operations/"), limit=260, per_route=2):
    """從幾個入口沿站內連結廣度優先爬；同一 URL 樣式（加上查詢參數的鍵）最多 per_route 頁。"""
    seen_routes, urls, queue, visited = {}, [], deque(start), set()
    while queue and len(urls) < limit:
        url = queue.popleft()
        if url in visited:
            continue
        visited.add(url)
        parsed = urlparse(url)
        if any(s in url for s in SKIP):
            continue
        key = (route(parsed.path), tuple(sorted(k for k, _ in parse_qsl(parsed.query))))
        if key[0] is None or seen_routes.get(key, 0) >= per_route:
            continue
        try:
            response = page.goto(base + url, wait_until="domcontentloaded", timeout=30000)
        except Exception:  # noqa: BLE001
            continue
        if not response or response.status >= 400 or not response.headers.get("content-type", "").startswith("text/html"):
            continue
        if urlparse(page.url).path.startswith("/login"):
            continue
        seen_routes[key] = seen_routes.get(key, 0) + 1
        urls.append(url)
        for href in page.evaluate("[...document.querySelectorAll('a[href]')].map(a => a.getAttribute('href'))"):
            if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
                continue
            target = urlparse(urljoin(base + url, href))
            if target.netloc and target.netloc != urlparse(base).netloc:
                continue
            query = urlencode(sorted(parse_qsl(target.query)))
            nxt = target.path + (f"?{query}" if query else "")
            if nxt not in visited:
                queue.append(nxt)
    return urls
