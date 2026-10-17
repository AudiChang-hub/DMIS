"""產生教學影片：重建示範資料庫 → 啟動示範伺服器 → 錄製指定腳本 → 合成 MP4。

用法：python tools/tutorials/run.py <腳本名稱> <輸出資料夾>
例如：python tools/tutorials/run.py open_order C:/Temp/tutorials

全程只用虛構的示範資料（demo_seed.py），不連正式資料庫。
"""
import importlib
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "scenarios"))

from playwright.sync_api import sync_playwright  # noqa: E402

from recorder import CURSOR_SCRIPT, SCALE, VIEWPORT, Recorder, build_video, load_cues, save_cues  # noqa: E402

PORT = 8793
USERNAME, PASSWORD = "admin", "Tutorial-Only-123"

SETTINGS = '''from config.settings import *  # noqa: F401,F403
DATABASES = {{"default": {{"ENGINE": "django.db.backends.sqlite3", "NAME": r"{db}"}}}}
MEDIA_ROOT = r"{media}"
# 保持開發模式：靜態檔直接讀原始碼（關閉 DEBUG 會改讀舊的打包靜態檔）。
ALLOWED_HOSTS = ["127.0.0.1", "localhost"]
'''


def prepare_environment(work):
    if work.exists():
        shutil.rmtree(work)
    (work / "settings").mkdir(parents=True)
    (work / "settings" / "tutorial_settings.py").write_text(
        SETTINGS.format(db=work / "demo.sqlite3", media=work / "media"), encoding="utf-8",
    )
    env = {**os.environ, "PYTHONPATH": str(work / "settings"), "PYTHONUTF8": "1",
           "DJANGO_SETTINGS_MODULE": "tutorial_settings", "TUTORIAL_ASSETS": str(work / "assets")}
    subprocess.run([sys.executable, "manage.py", "migrate", "-v", "0", "--settings=tutorial_settings"], cwd=ROOT, env=env, check=True)
    subprocess.run([sys.executable, str(HERE / "demo_seed.py")], cwd=ROOT, env=env, check=True)
    return env


def start_server(env, log):
    server = subprocess.Popen([sys.executable, str(HERE / "serve.py"), str(PORT)], cwd=ROOT, env=env,
                              stdout=log, stderr=subprocess.STDOUT)
    for _ in range(60):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}/login/", timeout=1)
            return server
        except OSError:
            time.sleep(0.5)
    server.terminate()
    raise RuntimeError("示範伺服器沒有啟動，請看 server.log")


def main(name, out_dir):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    work = out_dir / f".work-{name}"
    env = prepare_environment(work)
    scenario = importlib.import_module(name)
    base_url = f"http://127.0.0.1:{PORT}"
    with open(work / "server.log", "wb") as log:
        server = start_server(env, log)
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                # 先登入取得工作階段，正式錄影從已登入的首頁開始。
                login = browser.new_context(viewport=VIEWPORT, locale="zh-TW")
                page = login.new_page()
                page.goto(f"{base_url}/login/")
                page.fill("input[name=username]", USERNAME)
                page.fill("input[name=password]", PASSWORD)
                page.click("button[type=submit]")
                page.wait_for_load_state("networkidle")
                state = login.storage_state()
                login.close()

                context = browser.new_context(
                    viewport=VIEWPORT, device_scale_factor=SCALE, locale="zh-TW", storage_state=state,
                    record_video_dir=str(work / "raw"), record_video_size=VIEWPORT,
                )
                context.add_init_script(CURSOR_SCRIPT)
                page = context.new_page()
                t0 = time.monotonic()
                recorder = Recorder(page, work, t0)
                scenario.run(recorder, base_url, work / "assets")
                raw = page.video.path()
                context.close()
                browser.close()
        finally:
            server.terminate()
    output = out_dir / f"{name}.mp4"
    save_cues(recorder.cues, work / "cues.json")
    (work / "raw_path.txt").write_text(str(raw), encoding="utf-8")
    build_video(raw, recorder.cues, output, work)
    print(output)
    return output


def rebuild(name, out_dir):
    """只重新合成（不重錄）：沿用上次的錄影與旁白時間。"""
    work = Path(out_dir) / f".work-{name}"
    raw = Path((work / "raw_path.txt").read_text(encoding="utf-8"))
    output = Path(out_dir) / f"{name}.mp4"
    build_video(raw, load_cues(work / "cues.json"), output, work)
    print(output)


if __name__ == "__main__":
    if "--rebuild" in sys.argv:
        rebuild(sys.argv[1], sys.argv[2])
    else:
        main(sys.argv[1], sys.argv[2])
