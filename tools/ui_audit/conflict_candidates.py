"""從 style_diff.py 的輸出找出「搬出去後層疊結果變了」的規則，給 css_split.py 的 keep 清單（T-242）。不進 CI。

用法：python tools/ui_audit/conflict_candidates.py <style_diff 輸出檔> <批次名>
做法：每個變了的「元素｜屬性」，找本批模組 CSS 裡最後一段選擇器含有該元素 class、且宣告同一屬性（含簡寫）的規則。
寧可多留：留在 app.css 一定不會改變結果，只是少搬一點。
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from css_coverage import parse_rules  # noqa: E402
from css_split import BATCHES, ROOT, split_selector  # noqa: E402

LINE = re.compile(r"^\s+(?P<path>.+?) \| (?P<prop>[\w-]+): ")
SIDES = re.compile(r"-(top|right|bottom|left|block|inline)(-(start|end))?$")


def base_props(prop):
    names = {prop}
    stripped = SIDES.sub("", prop)
    names.add(stripped)
    if prop.startswith("grid-template"):
        names.add("grid-template")
    if stripped in ("border", "border-width", "border-color", "border-style"):
        names.add("border")
    if "gap" in prop:
        names.add("gap")
    return names


def main():
    log, batch = Path(sys.argv[1]), sys.argv[2]
    changes = []
    for line in log.read_text(encoding="utf-8").splitlines():
        match = LINE.match(line)
        if not match or "元素不見了" in line:
            continue
        last = match["path"].split(" > ")[-1].split(":")[0]
        classes = set(last.split(".")[1:])
        changes.append((classes, base_props(match["prop"])))
    keep = set()
    for module in BATCHES[batch]:
        text = (ROOT / "static" / "css" / module["css"]).read_text(encoding="utf-8")
        for start, end, selector, conditions in parse_rules(text):
            body = text[start:end].split("{", 1)[1]
            declared = set(re.findall(r"(?:^|[;{\s])([\w-]+)\s*:", body))
            for part in split_selector(selector):
                compound = re.split(r"\s*[>+~\s]\s*", part.strip())[-1]
                own = set(re.findall(r"\.([A-Za-z_][\w-]*)", compound))
                if any(own & classes and declared & props for classes, props in changes):
                    keep.add(" ".join(selector.split()))
    for selector in sorted(keep):
        print(selector)


if __name__ == "__main__":
    main()
