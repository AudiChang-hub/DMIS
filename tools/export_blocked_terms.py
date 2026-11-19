"""從正式站唯讀匯出禁用詞清單，給 CI 的 BLOCKED_TERMS secret 使用。

輸出一定在 repo 外（預設系統暫存資料夾的 dmis-blocked-terms/），本腳本拒絕寫進 repo。
畫面只印數量與檔案路徑，不印名稱。

用法（主機、金鑰、專案目錄都由參數或環境變數給，不寫死在 repo 裡）：

    python tools/export_blocked_terms.py \
        --ssh-host <SSH 別名> --ssh-key <金鑰路徑> --project-dir <正式站專案目錄>

    # 或用先前匯出的 JSON（測試、離線重算）：
    python tools/export_blocked_terms.py --from-json <raw.json>

產生兩個檔：
- blocked_terms.txt：一行一詞，整份貼進 repo secret BLOCKED_TERMS。
- review.md：被排除的詞與原因、每個詞在目前 repo 出現幾個檔案，給人工確認。

建清單規則（詳見 docs/reference/BLOCKED_TERMS.md）：
1. 收：客戶姓名（訂單車主、舊車主）、車行／網路平台／本店來源名稱、通路聯絡人與負責人、
   分期公司、人員帳號與姓名。
2. 不收：本店門市與開單公司名稱（系統本身的身分）；一般詞（內建清單 GENERIC_TERMS、
   台灣地名、repo 外的 exclude.txt）；中文少於 2 字；英文少於 4 字或屬常見英文字
   （COMMON_ASCII）；純數字、電話。
3. 在目前 repo 已出現於 >= --frequent 個檔案的詞，預設先排除並列進 review.md，
   多半是一般詞或程式裡的業務常數，確認後用 --include 檔案加回。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import unicodedata
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 正式站上執行的唯讀查詢：只做 SELECT，輸出 JSON 到 stdout。
REMOTE_SNIPPET = r'''
import json
from django.apps import apps
from django.contrib.auth import get_user_model

out = {k: set() for k in ("customer", "dealer", "platform", "store_source", "contact",
                          "installment", "account", "own")}

def take(qs, field):
    return {v for v in qs.values_list(field, flat=True).distinct() if v}

CUSTOMER_FIELDS = {"owner_name", "old_owner_name", "old_owner_ocr_name"}
CONTACT_FIELDS = {"responsible_person", "contact_person", "assigned_to_name"}
for model in apps.get_models():
    if model._meta.app_label != "sales":
        continue
    names = {f.name for f in model._meta.concrete_fields}
    for field in sorted(CUSTOMER_FIELDS & names):
        out["customer"] |= take(model.objects.all(), field)
    for field in sorted(CONTACT_FIELDS & names):
        out["contact"] |= take(model.objects.all(), field)
    if "dealer_name" in names:
        out["dealer"] |= take(model.objects.all(), "dealer_name")

SalesSource = apps.get_model("sales", "SalesSource")
for source_type, key in (("dealer", "dealer"), ("platform", "platform"), ("store", "store_source")):
    out[key] |= take(SalesSource.objects.filter(source_type=source_type), "name")
out["installment"] |= take(apps.get_model("sales", "InstallmentCompany").objects.all(), "name")
out["own"] |= take(apps.get_model("sales", "Store").objects.all(), "name")
out["own"] |= take(apps.get_model("sales", "PrintCompany").objects.all(), "legal_name")
for user in get_user_model().objects.all():
    out["account"] |= {v for v in (user.username, user.first_name, user.last_name,
                                   f"{user.last_name}{user.first_name}") if v}
print(json.dumps({k: sorted(v) for k, v in out.items()}, ensure_ascii=False))
'''

CATEGORY_LABELS = {
    "customer": "客戶姓名", "dealer": "車行", "platform": "網路平台", "store_source": "本店來源",
    "contact": "通路聯絡人／負責人", "installment": "分期公司", "account": "人員帳號／姓名",
}

# 一般詞：在程式、文件裡常以一般意思出現，放進清單只會誤判。
# 剛好被拿來當店名的一般詞（只因車行取這個名字才需要排除）不寫在這裡，
# 放 repo 外的 <out-dir>/exclude.txt，避免 repo 反過來透露車行名單。
GENERIC_TERMS = {
    "安全", "展場", "假展場", "朋友推薦", "本店", "門市", "車行",
    "平台", "網路", "測試", "客戶", "業務", "店長", "老闆", "現場", "其他", "一店", "二店", "三店",
    "總店", "公司", "自來客", "介紹", "舊客", "員購", "試乘",
    # 車主欄位裡的佔位字，不是人名
    "本人", "同人", "同一人", "新舊車主同一人", "待確認", "未填", "不詳",
}
COMMON_ASCII = {
    "admin", "audi", "test", "user", "demo", "staff", "root", "guest", "sales", "store", "shop",
    "friday", "yahoo", "line", "google", "apple", "home", "boss", "manager", "system", "support",
}
SPLIT = re.compile(r"[、,，/／;；|｜\n]+")


def normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text).strip()


def place_names() -> set[str]:
    """repo 內台灣地址資料出現的中文詞都視為地名（例如區名、里名）。"""
    path = ROOT / "sales/services/taiwan_address.py"
    if not path.exists():
        return set()
    names = set()
    for token in re.findall(r'"([一-鿿]{2,})"', path.read_text(encoding="utf-8")):
        for variant in {token, token.replace("臺", "台")}:
            names.add(variant)
            if variant[-1] in "區鄉鎮市縣" and len(variant) >= 3:
                names.add(variant[:-1])  # 「瑞芳區」也排除「瑞芳」
    return names


def exclusion_reason(term: str, own: set[str], places: set[str]) -> str | None:
    if re.fullmatch(r"[\d\s()+\-#]+", term):
        return "純數字／電話"
    if term.isascii():
        if len(term) < 4:
            return "英文少於 4 字"
        if term.casefold() in COMMON_ASCII:
            return "常見英文字"
    else:
        if len(term) < 2:
            return "中文少於 2 字"
    if term in GENERIC_TERMS:
        return "一般詞"
    if term in places:
        return "台灣地名"
    if term in own or any(term in o for o in own if len(term) >= 2):
        return "本店門市／開單公司"
    return None


def repo_hit_counts(terms: list[str]) -> dict[str, int]:
    counts = {}
    for term in terms:
        result = subprocess.run(
            ["git", "-c", "core.quotepath=false", "grep", "-I", "-l", "-i", "-F", "-e", term, "HEAD", "--"],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        counts[term] = len([line for line in result.stdout.splitlines() if line.strip()])
    return counts


def fetch_remote(args) -> dict:
    missing = [n for n in ("ssh_host", "project_dir") if not getattr(args, n)]
    if missing:
        sys.exit("缺少 --ssh-host／--project-dir（或環境變數 DMIS_PROD_SSH_HOST／DMIS_PROD_PROJECT_DIR）。")
    if re.match(r"^[A-Za-z]:[\\/]", args.project_dir):
        sys.exit("--project-dir 被轉成 Windows 路徑（Git Bash 會改寫 / 開頭的參數）；"
                 "請在 PowerShell 執行，或在 Git Bash 前面加 MSYS_NO_PATHCONV=1。")
    ssh = ["ssh", "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes"]
    if args.ssh_key:
        ssh += ["-i", args.ssh_key]
    remote = (
        f"cd {args.project_dir} && docker compose -f docker-compose.django.yml "
        "-f docker-compose.django.prod.yml exec -T web python manage.py shell "
        "-c 'import sys; exec(sys.stdin.read())'"
    )
    result = subprocess.run(
        ssh + [args.ssh_host, remote], input=REMOTE_SNIPPET, capture_output=True,
        text=True, encoding="utf-8", errors="replace",
    )
    if result.returncode != 0:
        sys.exit(f"正式站唯讀查詢失敗（exit {result.returncode}）；stderr 已略，請手動檢查連線。")
    line = [ln for ln in result.stdout.splitlines() if ln.startswith("{")][-1:]
    if not line:
        sys.exit("正式站沒有回傳 JSON。")
    return json.loads(line[0])


def build(raw: dict, frequent: int, include: set[str], exclude: set[str]):
    own = {normalize(v) for v in raw.get("own", [])}
    places = place_names()
    candidates: dict[str, set[str]] = defaultdict(set)
    for key in CATEGORY_LABELS:
        for value in raw.get(key, []):
            parts = [value] if normalize(value).isascii() else SPLIT.split(value)
            for part in parts:
                term = normalize(part)
                if term:
                    candidates[term].add(CATEGORY_LABELS[key])

    excluded: dict[str, str] = {}
    kept = []
    for term in sorted(candidates):
        reason = "手動排除" if term in exclude else exclusion_reason(term, own, places)
        if reason and term not in include:
            excluded[term] = reason
        else:
            kept.append(term)

    counts = repo_hit_counts(kept)
    final = []
    for term in kept:
        if counts[term] >= frequent and term not in include:
            excluded[term] = f"repo 已有 {counts[term]} 個檔案出現，請人工確認"
        else:
            final.append(term)
    for term in sorted(include - set(final)):
        final.append(normalize(term))
    return sorted(set(final)), excluded, candidates, counts


def read_list(path: str | None) -> set[str]:
    if not path:
        return set()
    return {normalize(ln) for ln in Path(path).read_text(encoding="utf-8").splitlines()
            if normalize(ln) and not ln.startswith("#")}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ssh-host", default=os.environ.get("DMIS_PROD_SSH_HOST"))
    parser.add_argument("--ssh-key", default=os.environ.get("DMIS_PROD_SSH_KEY"))
    parser.add_argument("--project-dir", default=os.environ.get("DMIS_PROD_PROJECT_DIR"))
    parser.add_argument("--from-json", help="改用先前匯出的原始 JSON，不連正式站")
    parser.add_argument("--save-raw", action="store_true", help="另存原始 JSON（repo 外）")
    parser.add_argument("--out-dir", default=str(Path(tempfile.gettempdir()) / "dmis-blocked-terms"))
    parser.add_argument("--frequent", type=int, default=20)
    parser.add_argument("--include", help="一定要收的詞（一行一詞）；預設讀 <out-dir>/include.txt")
    parser.add_argument("--exclude", help="一定不收的詞（一行一詞）；預設讀 <out-dir>/exclude.txt")
    args = parser.parse_args(argv)

    out_dir = Path(args.out_dir).resolve()
    if out_dir == ROOT or ROOT in out_dir.parents:
        sys.exit("輸出路徑在 repo 裡；清單含真實名稱，請改到 repo 外。")
    out_dir.mkdir(parents=True, exist_ok=True)

    if not args.exclude and (out_dir / "exclude.txt").exists():
        args.exclude = str(out_dir / "exclude.txt")
    if not args.include and (out_dir / "include.txt").exists():
        args.include = str(out_dir / "include.txt")

    if args.from_json:
        raw = json.loads(Path(args.from_json).read_text(encoding="utf-8"))
    else:
        raw = fetch_remote(args)
        if args.save_raw:
            (out_dir / "raw.json").write_text(json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8")

    final, excluded, candidates, counts = build(
        raw, args.frequent, read_list(args.include), read_list(args.exclude))

    (out_dir / "blocked_terms.txt").write_text("\n".join(final) + "\n", encoding="utf-8")
    lines = ["# 禁用詞清單檢查（含真實名稱，勿提交、勿外傳）", "",
             "## 收進清單", "", "| 詞 | 類別 | repo 目前檔案數 |", "|---|---|---|"]
    lines += [f"| {t} | {'、'.join(sorted(candidates.get(t, {'手動加入'})))} | {counts.get(t, '-')} |" for t in final]
    lines += ["", "## 排除", "", "| 詞 | 類別 | 原因 |", "|---|---|---|"]
    lines += [f"| {t} | {'、'.join(sorted(candidates.get(t, set())))} | {r} |" for t, r in sorted(excluded.items())]
    (out_dir / "review.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"收進清單 {len(final)} 詞，排除 {len(excluded)} 詞。")
    print(f"清單：{out_dir / 'blocked_terms.txt'}")
    print(f"檢查表：{out_dir / 'review.md'}")
    print("先看 review.md 確認，再請 PM 設定 secret；用完刪除這個資料夾。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
