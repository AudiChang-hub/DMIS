"""禁用詞掃描：擋下把真實客戶、車行、平台、分期公司、人員帳號寫進公開 repo。

清單只從環境變數 BLOCKED_TERMS 讀（CI 由 repo secret 注入），一行一詞，`#` 開頭為註解。
掃描範圍：BASE..HEAD 之間「新增或修改的行」、新增檔案的路徑，以及這段範圍內的 commit 訊息。
既有內容不掃；舊資料清理另案處理。

輸出只列檔名與行號（或 commit 與訊息行號），絕不印出命中的詞或該行內容。

比對規則：
- 兩邊都先做 NFKC 正規化並轉小寫（全形英數、大小寫都視為相同）。
- 含非 ASCII 字元的詞（中文名稱）用子字串比對。
- 純 ASCII 的詞（帳號、英文名）只比對完整單字：前後不能緊鄰英數字，避免 `test` 命中 `latest`。

離開代碼：0 沒命中（或依設定略過）；1 有命中；2 清單缺少且要求必填，或 git 指令失敗。
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import unicodedata
from dataclasses import dataclass

ZERO_SHA = re.compile(r"^0+$")
HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


@dataclass(frozen=True)
class Hit:
    where: str  # 檔名，或 "commit <sha>"
    line: int
    kind: str  # "file"、"path"、"commit"


def normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold()


def parse_terms(raw: str) -> list[str]:
    terms = []
    seen = set()
    for line in raw.splitlines():
        term = normalize(line.strip())
        if not term or term.startswith("#") or term in seen:
            continue
        seen.add(term)
        terms.append(term)
    return terms


def build_matcher(terms: list[str]):
    """回傳 match(text) -> bool；只告訴呼叫端有沒有命中，不回傳是哪個詞。"""
    cjk = [t for t in terms if not t.isascii()]
    ascii_terms = [t for t in terms if t.isascii()]
    pattern = None
    if ascii_terms:
        alternation = "|".join(re.escape(t) for t in sorted(ascii_terms, key=len, reverse=True))
        pattern = re.compile(rf"(?<![0-9a-z])(?:{alternation})(?![0-9a-z])")

    def match(text: str) -> bool:
        norm = normalize(text)
        if any(t in norm for t in cjk):
            return True
        return bool(pattern and pattern.search(norm))

    return match


def _unquote_path(text: str) -> str:
    """core.quotepath=false 後，只有含引號、反斜線或控制字元的路徑還會被加引號。"""
    text = text.rstrip("\t")
    if len(text) >= 2 and text[0] == text[-1] == '"':
        body = text[1:-1].encode("latin-1", "backslashreplace").decode("unicode_escape")
        return body.encode("latin-1", "replace").decode("utf-8", "replace")
    return text


def git(*args: str) -> str:
    result = subprocess.run(
        ["git", "-c", "core.quotepath=false", *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {args[0]} 失敗（exit {result.returncode}）")
    return result.stdout


def resolve_range(base: str | None, head: str) -> tuple[str | None, str]:
    """找不到可用的比較基準（新分支、force push、排程）時，只檢查 HEAD 這一個 commit。"""
    if base and not ZERO_SHA.match(base):
        try:
            git("cat-file", "-e", f"{base}^{{commit}}")
            return base, head
        except RuntimeError:
            pass
    try:
        parent = git("rev-parse", "--verify", "--quiet", f"{head}^").strip()
    except RuntimeError:
        parent = ""
    print("::warning::找不到可用的比較基準，只檢查最新一個 commit。")
    return (parent or None), head


def scan_diff(base: str | None, head: str, match) -> list[Hit]:
    if base:
        diff = git("diff", "--unified=0", "--no-color", "--no-ext-diff", "--no-renames", base, head)
    else:  # 根 commit：整個 commit 都是新增
        diff = git("show", "--format=", "--unified=0", "--no-color", "--no-ext-diff", "--no-renames", head)
    hits: list[Hit] = []
    path = None
    line_no = 0
    old_path = None
    in_header = False
    for raw in diff.splitlines():
        # 檔頭只出現在 "diff --git" 與第一個 @@ 之間；hunk 內以 "--"、"++" 開頭的內容不是檔頭。
        if raw.startswith("diff --git "):
            in_header, path, old_path = True, None, None
            continue
        if in_header:
            if raw.startswith("--- "):
                old_path = raw[4:]
            elif raw.startswith("+++ "):
                target = _unquote_path(raw[4:])
                path = None if target == "/dev/null" else target[2:] if target.startswith("b/") else target
                if path and old_path == "/dev/null" and match(path):
                    hits.append(Hit(path, 0, "path"))
            elif raw.startswith("@@"):
                in_header = False
            if in_header:
                continue
        if raw.startswith("@@"):
            m = HUNK.match(raw)
            line_no = int(m.group(1)) if m else 0
            continue
        if path is None:
            continue
        if raw.startswith("+"):
            if match(raw[1:]):
                hits.append(Hit(path, line_no, "file"))
            line_no += 1
    return hits


def scan_commit_messages(base: str | None, head: str, match) -> list[Hit]:
    rev_range = f"{base}..{head}" if base else head
    extra = [] if base else ["-1"]
    log = git("log", *extra, "--format=%H%x00%B%x1e", rev_range)
    hits: list[Hit] = []
    for record in log.split("\x1e"):
        record = record.strip("\n")
        if not record:
            continue
        sha, _, body = record.partition("\x00")
        for number, text in enumerate(body.splitlines(), start=1):
            if match(text):
                hits.append(Hit(f"commit {sha[:12]}", number, "commit"))
    return hits


def report(hits: list[Hit], match) -> None:
    hidden = "（檔名含禁用詞，不顯示；請在本機用 git diff --name-only 檢查）"
    for hit in hits:
        if hit.kind == "commit":
            print(f"{hit.where} 訊息第 {hit.line} 行")
            print(f"::error title=禁用詞::{hit.where} 的 commit 訊息第 {hit.line} 行命中禁用詞清單")
            continue
        if match(hit.where):
            print(f"{hidden}" + ("" if hit.kind == "path" else f" 第 {hit.line} 行"))
            print("::error title=禁用詞::有檔名命中禁用詞清單（不顯示檔名）")
        elif hit.kind == "path":
            print(f"{hit.where}（檔名）")
            print(f"::error file={hit.where},title=禁用詞::新增的檔名命中禁用詞清單")
        else:
            print(f"{hit.where}:{hit.line}")
            print(f"::error file={hit.where},line={hit.line},title=禁用詞::這一行命中禁用詞清單")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", default="", help="比較基準 SHA；空白或全 0 時只檢查 HEAD")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument(
        "--missing",
        choices=["fail", "skip"],
        default="fail",
        help="BLOCKED_TERMS 不存在或為空時：fail 失敗（push 到 main），skip 只警告（fork 的 PR）",
    )
    args = parser.parse_args(argv)

    terms = parse_terms(os.environ.get("BLOCKED_TERMS", ""))
    if not terms:
        if args.missing == "skip":
            print("::warning::沒有 BLOCKED_TERMS（fork 的 PR 拿不到 secret），略過禁用詞掃描。")
            return 0
        print(
            "::error::沒有 BLOCKED_TERMS secret 或內容為空。"
            "請到 repo Settings → Secrets and variables → Actions 設定（一行一詞），"
            "清單產生方式見 docs/reference/BLOCKED_TERMS.md。"
        )
        return 2

    match = build_matcher(terms)
    try:
        base, head = resolve_range(args.base.strip() or None, args.head)
        hits = scan_diff(base, head, match) + scan_commit_messages(base, head, match)
    except RuntimeError as exc:
        print(f"::error::{exc}")
        return 2

    print(f"禁用詞清單 {len(terms)} 個詞；檢查範圍 {(base or '(root)')[:12]}..{head[:12]}")
    if not hits:
        print("沒有命中禁用詞。")
        return 0
    print(f"命中 {len(hits)} 處（不顯示命中的詞）：")
    report(hits, match)
    print(
        "請改成假名或通用寫法後再推送。已推上去的 commit 訊息無法改，"
        "需另案處理；不要為了通過檢查而改寫歷史或 force push。"
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
