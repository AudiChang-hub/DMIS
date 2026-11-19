"""兩棵工作樹同一頁的 computed style 逐元素比對，找出搬樣式後哪個元素、哪個屬性變了（T-242）。不進 CI。

用法：python tools/ui_audit/style_diff.py <基準工作樹> <合成資料庫> /頁面 [/頁面 …] [--width 1440]
兩邊各起一個示範伺服器（同一份合成資料），逐頁比對所有元素的 computed style，列出不同的元素與屬性。
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
COLLECT = """() => {
  const path = el => { const parts = []; for (let e = el; e && e.nodeType === 1 && e !== document.body; e = e.parentElement) {
    let i = 1; for (let s = e.previousElementSibling; s; s = s.previousElementSibling) i++;
    parts.unshift(e.tagName.toLowerCase() + (e.className && typeof e.className === 'string' ? '.' + e.className.trim().split(/\\s+/).join('.') : '') + ':' + i); }
    return parts.join(' > '); };
  const out = {};
  for (const el of document.querySelectorAll('body *')) {
    const cs = getComputedStyle(el), map = {};
    for (let i = 0; i < cs.length; i++) map[cs[i]] = cs.getPropertyValue(cs[i]);
    out[path(el)] = map;
  }
  return out;
}"""


def serve(root, db_from, port):
    code = ("import sys;sys.path.insert(0,r'%s');from snapshot_compare import restore_db, WORK;from common import prepare, session_key, start_server;"
            "from pathlib import Path;restore_db(Path(r'%s'));env=prepare(WORK, fresh=False);print(session_key(env), flush=True);"
            "log=open(WORK/'style-diff.log','wb');s=start_server(env,%d,log);print('ready',flush=True);sys.stdin.read();s.terminate()") % (root / "tools" / "ui_audit", db_from, port)
    proc = subprocess.Popen([sys.executable, "-c", code], cwd=root, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
                            env={**__import__("os").environ, "PYTHONUTF8": "1", "UI_AUDIT_DB_DIR": str(root / "tmp" / "ui-style-db")})
    key = proc.stdout.readline().strip()
    assert proc.stdout.readline().strip() == "ready"
    return proc, key


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("baseline", type=Path)
    parser.add_argument("db_from")
    parser.add_argument("pages", nargs="+")
    parser.add_argument("--width", type=int, default=1440)
    args = parser.parse_args()
    current = HERE.parents[1]
    servers = [serve(args.baseline, args.db_from, 8871), serve(current, args.db_from, 8872)]
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            for url in args.pages:
                styles = []
                for (proc, key), port in zip(servers, (8871, 8872)):
                    context = browser.new_context(viewport={"width": args.width, "height": 900}, is_mobile=args.width < 860)
                    context.add_cookies([{"name": "sessionid", "value": key, "url": f"http://127.0.0.1:{port}"}])
                    page = context.new_page()
                    page.goto(f"http://127.0.0.1:{port}{url}", wait_until="networkidle")
                    styles.append(page.evaluate(COLLECT))
                    context.close()
                before, after = styles
                changes = []
                for element, props in before.items():
                    other = after.get(element)
                    if other is None:
                        changes.append((element, "（元素不見了）")); continue
                    for prop, value in props.items():
                        if other.get(prop) != value:
                            changes.append((element[-120:], f"{prop}: {value} → {other.get(prop)}"))
                print(f"== {url}：{len(changes)} 處不同")
                for element, change in changes:
                    print("  ", element, "|", change)
            browser.close()
    finally:
        for proc, _ in servers:
            proc.stdin.close(); proc.wait(timeout=30)


if __name__ == "__main__":
    main()
