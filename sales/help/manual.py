"""由文章資料產生 docs/USER_MANUAL.md（T-197 方案 A）。

不要直接改 USER_MANUAL.md：改 articles.py 後執行 `python manage.py build_user_manual`。
"""
import re
from pathlib import Path

from django.conf import settings

from .articles import ARTICLES, GROUPS, START_HERE
from .schema import SCREEN_DIR

MANUAL_PATH = Path("docs") / "USER_MANUAL.md"
_UI = re.compile(r" ?\[\[(.+?)\]\] ?")  # 中文前後不留空白


def _md(text):
    """[[按鈕]] 寫成「按鈕」，**粗體** 保留 Markdown 寫法。"""
    return _UI.sub(r"「\1」", text or "").strip()


def _image(figure):
    return f"![{figure.alt}](../static/{SCREEN_DIR}/{figure.src})"


def _article(article, number, titles):
    lines = [f"## {number}. {article.title}", "", f"**什麼時候用**：{_md(article.when)}", ""]
    meta = [part for part in (article.minutes, f"{len(article.steps)} 個步驟") if part]
    lines += [f"_{'・'.join(meta)}_", ""]
    example = article.example
    lines += ["### 範例", "", _md(example.story), ""]
    lines += [f"- {label}：{_md(value)}" for label, value in example.facts]
    if example.facts:
        lines.append("")
    if example.results:
        lines += ["系統會算出：", ""]
        lines += [f"- **{_md(result)}**＝{_md(formula)}" for result, formula in example.results]
        lines.append("")
    lines += ["### 怎麼做", ""]
    if article.before:
        lines += [f"開始前：{_md(article.before)}", ""]
    for index, step in enumerate(article.steps, 1):
        lines.append(f"{index}. {_md(step.text)}")
        if step.example:
            lines.append(f"   - 範例：{_md(step.example)}")
        if step.note:
            lines.append(f"   - {_md(step.note)}")
        if step.figure:
            lines += ["", f"   {_image(step.figure)}"]
            if step.figure.caption:
                lines.append(f"   _{step.figure.caption}_")
        lines.append("")
    if article.done:
        tail = f" 下一步：{titles[article.next_slug]}。" if article.next_slug else ""
        lines += [f"> 完成：{_md(article.done)}{tail}", ""]
    if article.faqs:
        lines += ["### 常見問題", ""]
        for faq in article.faqs:
            lines += [f"**{_md(faq.question)}**", "", _md(faq.answer), ""]
    if article.rules:
        lines += ["### 規則細節", ""]
        lines += [f"- {_md(rule)}" for rule in article.rules]
        lines.append("")
    if article.related:
        lines += [f"相關：{'、'.join(titles[slug] for slug in article.related)}", ""]
    return lines


def render_manual():
    titles = {article.slug: article.title for article in ARTICLES}
    numbers = {}
    lines = [
        "# 車輛銷售管理系統｜使用說明",
        "",
        "> 本檔由 `sales/help/articles.py` 自動產生，請勿直接修改；改文章後執行 `python manage.py build_user_manual`。",
        "> 系統內的「使用說明」（/help/）與本檔內容相同；截圖用合成資料產生，不含真實客戶。",
        "",
        "## 目錄",
        "",
        "- [從這裡開始](#從這裡開始)",
    ]
    number = 0
    for group in GROUPS:
        items = [article for article in ARTICLES if article.group == group.key]
        if not items:
            continue
        lines.append(f"- {group.title}（{group.hint}）")
        for article in items:
            number += 1
            numbers[article.slug] = number
            lines.append(f"  - {number}. {article.title}")
    lines += ["", "## 從這裡開始", "", "第一次接單，照這幾站走一遍：", ""]
    for index, stop in enumerate(START_HERE, 1):
        lines.append(f"{index}. **{titles[stop.article]}**（第 {numbers[stop.article]} 篇）：{_md(stop.summary)}")
        lines.append(f"   - 範例：{_md(stop.example)}")
    lines.append("")
    for group in GROUPS:
        items = [article for article in ARTICLES if article.group == group.key]
        if not items:
            continue
        lines += [f"# {group.title}", "", group.hint, ""]
        for article in items:
            lines += _article(article, numbers[article.slug], titles)
    return "\n".join(lines).rstrip() + "\n"


def manual_path():
    return Path(settings.BASE_DIR) / MANUAL_PATH


def manual_text():
    """目前檔案內容；Windows 的 autocrlf 只差換行，比對時統一成 LF。"""
    path = manual_path()
    return path.read_text(encoding="utf-8").replace("\r\n", "\n") if path.exists() else ""
