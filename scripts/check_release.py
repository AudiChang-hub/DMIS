"""唯讀版本檢查：python scripts/check_release.py [--base SHA] [--tag vX.Y.Z]。"""

import argparse
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config.release_notes import CURRENT_VERSION, LEGACY_UPDATES, RELEASES
from config.release_validation import is_runtime_path, read_literal, validate_releases, validate_transition, version_tuple


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, encoding="utf-8", timeout=30).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", help="比較用的完整 Git SHA")
    parser.add_argument("--tag", help="部署前核對已建立的正式標籤")
    args = parser.parse_args()
    validate_releases(RELEASES, LEGACY_UPDATES)
    if args.base and set(args.base) != {"0"}:
        if not re.fullmatch(r"[0-9a-f]{40}", args.base):
            raise ValueError("基準必須是完整 Git SHA")
        # 以已發布標籤為界，不把尚未發布的中間修正 commit 當成另一個版本。
        tags = [tag for tag in git("tag", "--merged", args.base, "--list", "v*").splitlines()
                if re.fullmatch(r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", tag)]
        baseline = f"refs/tags/{max(tags, key=lambda tag: version_tuple(tag[1:]))}" if tags else None
        previous = read_literal(git("show", f"{baseline}:config/release_notes.py"), "RELEASES") if baseline else ()
        changed = git("diff", "--name-only", baseline or args.base, "HEAD").splitlines()
        validate_transition(RELEASES, previous, any(is_runtime_path(path) for path in changed))
    for entry in LEGACY_UPDATES:
        for commit in entry["commits"]:
            timestamp = int(git("show", "-s", "--format=%ct", commit))
            if datetime.fromtimestamp(timestamp, timezone(timedelta(hours=8))).date().isoformat() != entry["date"]:
                raise ValueError(f"歷史日期與提交 {commit} 不符")
    if args.tag:
        if args.tag != f"v{CURRENT_VERSION}":
            raise ValueError("標籤與目前正式版號不符")
        ref = f"refs/tags/{args.tag}"
        if git("cat-file", "-t", ref) != "tag" or git("rev-parse", f"{ref}^{{commit}}") != git("rev-parse", "HEAD"):
            raise ValueError("必須使用指向目前提交的附註標籤")
        if git("status", "--porcelain", "--untracked-files=no"):
            raise ValueError("部署標籤核對時，工作樹不可有未提交變更")
    print(f"正式版本 {CURRENT_VERSION}：版本歷程與發布核對通過")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        print(f"版本檢查失敗：{exc}", file=sys.stderr)
        sys.exit(1)
