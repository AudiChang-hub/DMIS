"""重拍使用說明截圖（T-197）：暫存資料庫 → 合成資料 → 示範伺服器 → 依序操作並截圖。

用法：python tools/help_screens/run.py            # 全部重拍
      python tools/help_screens/run.py reports    # 只拍某一組（create_order／mainline／reports）

截圖寫到 static/help/screens/<組>/，文章在 sales/help/articles.py 引用。
全程只用 seed_help_demo 的合成資料與暫存 SQLite，不連正式資料庫，也不碰專案的 db.sqlite3。
畫面上的按鈕改名或被移走時，腳本會報錯停下：代表對應的說明要一起改。
"""
import importlib
import os
import secrets
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))

from playwright.sync_api import sync_playwright  # noqa: E402

from cards import make_cards  # noqa: E402

PORT = 8796
SCREENS = ROOT / "static" / "help" / "screens"
GROUPS = ("reports", "create_order", "mainline", "topics", "basics", "manage")  # reports 先拍（只含 seed 的 30 張）；mainline、topics 接著 create_order 建好的訂單；basics、manage 前先補管理類資料

SETTINGS = '''from config.settings import *  # noqa: F401,F403
DATABASES = {{"default": {{"ENGINE": "django.db.backends.sqlite3", "NAME": r"{db}"}}}}
MEDIA_ROOT = r"{media}"
ALLOWED_HOSTS = ["127.0.0.1", "localhost", "testserver"]
'''


def prepare(work, password):
    if work.exists():
        shutil.rmtree(work)
    (work / "settings").mkdir(parents=True)
    (work / "settings" / "help_demo_settings.py").write_text(
        SETTINGS.format(db=work / "demo.sqlite3", media=work / "media"), encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": str(work / "settings"), "PYTHONUTF8": "1",
           "DJANGO_SETTINGS_MODULE": "help_demo_settings", "HELP_DEMO_ADMIN_PASSWORD": password}
    env.pop("POSTGRES_HOST", None)
    manage = [sys.executable, "manage.py"]
    subprocess.run([*manage, "migrate", "-v", "0"], cwd=ROOT, env=env, check=True)
    subprocess.run([*manage, "seed_help_demo", "--confirm-demo-database"], cwd=ROOT, env=env, check=True)
    make_cards(work / "assets")
    return env


def start_server(env, log):
    server = subprocess.Popen([sys.executable, str(HERE / "serve.py"), str(PORT)], cwd=ROOT, env=env,
                              stdout=log, stderr=subprocess.STDOUT)
    for _ in range(120):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}/login/", timeout=1)
            return server
        except OSError:
            time.sleep(0.5)
    server.terminate()
    raise RuntimeError("示範伺服器沒有啟動，請看 server.log")


def main(groups):
    work = ROOT / "tmp" / "help-screens"
    password = secrets.token_urlsafe(18)  # 只存在這次執行的暫存資料庫
    env = prepare(work, password)
    base = f"http://127.0.0.1:{PORT}"
    facts = {"_password": password}  # 示範業務等合成帳號也用這組；底線開頭的不印出
    with open(work / "server.log", "wb") as log:
        server = start_server(env, log)
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(args=["--lang=zh-TW"])
                login = browser.new_context(locale="zh-TW")
                page = login.new_page()
                page.goto(f"{base}/login/")
                page.fill("input[name=username]", "admin")
                page.fill("input[name=password]", password)
                page.click("button[type=submit]")
                page.wait_for_load_state("networkidle")
                state = login.storage_state()
                login.close()
                for name in GROUPS:
                    needs_wang = name == "create_order" and ({"mainline", "topics"} & set(groups))
                    if name not in groups and not needs_wang:
                        continue
                    if name in {"basics", "manage"} and not facts.get("manage_seeded"):
                        subprocess.run([sys.executable, "manage.py", "seed_help_demo", "--confirm-demo-database", "--manage"],
                                       cwd=ROOT, env=env, check=True)
                        facts["manage_seeded"] = True
                    if name in {"topics", "basics", "manage"}:
                        out = SCREENS  # 各篇自己建資料夾、清舊圖
                    else:
                        out = SCREENS / name.replace("_", "-")
                        out.mkdir(parents=True, exist_ok=True)
                        for old in out.glob("*.jpg"):
                            old.unlink()
                    context = browser.new_context(viewport={"width": 1440, "height": 1400}, locale="zh-TW",
                                                  reduced_motion="reduce", storage_state=state)
                    page = context.new_page()
                    page.on("dialog", lambda dialog: dialog.accept())
                    facts[name] = importlib.import_module(f"scenarios.{name}").run(page, base, out, work / "assets", facts)
                    context.close()
                    print(f"{name}: {len(list(out.rglob('*.jpg')) if out == SCREENS else list(out.glob('*.jpg')))} 張 → {out.relative_to(ROOT)}")
                browser.close()
        finally:
            server.terminate()
    return facts


if __name__ == "__main__":
    chosen = set(sys.argv[1:]) or set(GROUPS)
    unknown = chosen - set(GROUPS)
    if unknown:
        sys.exit(f"不認得的組：{', '.join(sorted(unknown))}；可用 {', '.join(GROUPS)}")
    for key, value in main(chosen).items():
        if not key.startswith("_"):
            print(key, value)
