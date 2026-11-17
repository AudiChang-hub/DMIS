"""使用說明的資料格式（T-197 方案 A）：文章只寫一次，說明頁與 USER_MANUAL.md 都由它產生。

文字欄位可用兩種標記，其餘一律當純文字跳脫：
- 「[[按鈕名稱]]」：畫面上的按鈕或欄位名稱，照畫面原字抄寫。
- 「**重點**」：粗體。
"""
from dataclasses import dataclass, field
from pathlib import Path

from django.conf import settings

SCREEN_DIR = "help/screens"  # 相對於 static/；圖檔由 tools/help_screens 依合成資料自動產生
MIN_STEPS, MAX_STEPS = 3, 7
RESERVED_SLUGS = {"new", "start"}



@dataclass(frozen=True)
class Figure:
    src: str  # SCREEN_DIR 底下的路徑，例如 "create-order/01-catalog.jpg"
    alt: str
    caption: str = ""  # 圖上橘色編號的說明，例如「① 選這台接單」


@dataclass(frozen=True)
class Step:
    text: str
    example: str = ""  # 「範例：」後面的內容
    figure: Figure | None = None
    note: str = ""


@dataclass(frozen=True)
class Faq:
    question: str
    answer: str
    flag: str = ""  # 待核對事項，畫面以黃色標籤顯示


@dataclass(frozen=True)
class Example:
    story: str
    facts: tuple = ()  # ((標籤, 值), ...)
    results: tuple = ()  # ((結果, 怎麼算), ...)，數字必須是系統實際顯示的值


@dataclass(frozen=True)
class Article:
    slug: str
    title: str
    group: str
    when: str
    steps: tuple
    example: Example
    minutes: str = ""
    before: str = ""
    done: str = ""
    next_slug: str = ""
    faqs: tuple = ()
    rules: tuple = ()
    related: tuple = ()
    routes: tuple = ()  # 「這頁怎麼用」：從哪些路由開說明會直接到這篇
    access: tuple = ()  # 與 audience_content.permitted 相同的規則（每項都要符合；寫成 tuple 的項目任一符合即可）；空白＝登入就看得到
    depends: tuple = ()  # 這篇依賴的模板，發版時用來提醒要不要重拍截圖或改文字
    open_route: str = ""  # 頁首「打開○○」按鈕要去的路由（不需參數）
    open_label: str = ""
    replaces: tuple = ()  # 舊版說明的 topic id；/help/?topic= 帶這些值時直接轉到這篇
    verified: str = ""  # 依哪一版畫面核對，例如 "2.14.0"


@dataclass(frozen=True)
class Group:
    key: str
    title: str
    hint: str


@dataclass(frozen=True)
class Stop:
    article: str
    summary: str
    example: str
    figure: Figure
    minutes: str
    open_route: str = ""
    open_hint: str = ""


@dataclass(frozen=True)
class PageTip:
    """功能頁頁首的一行提示（T-201）：這頁做什麼、下一步去哪，連到對應文章。"""
    article: str
    does: str
    next: str = ""


@dataclass(frozen=True)
class Tip:
    title: str
    text: str
    article: str = ""


def figure_path(figure):
    return Path(settings.BASE_DIR) / "static" / SCREEN_DIR / figure.src


def article_figures(article):
    return [step.figure for step in article.steps if step.figure]


def validate(articles, groups, stops=(), tips=()):
    """回傳錯誤清單；測試要求為空。"""
    errors = []
    slugs = {item.slug for item in articles}
    group_keys = {group.key for group in groups}
    seen = set()
    for item in articles:
        where = f"〈{item.title}〉"
        if item.slug in seen:
            errors.append(f"{where} slug 重複：{item.slug}")
        seen.add(item.slug)
        if item.slug in RESERVED_SLUGS:
            errors.append(f"{where} slug 不能用保留字 {item.slug}")
        if item.group not in group_keys:
            errors.append(f"{where} 分組不存在：{item.group}")
        if not item.when.strip():
            errors.append(f"{where} 缺少「什麼時候用」")
        if not MIN_STEPS <= len(item.steps) <= MAX_STEPS:
            errors.append(f"{where} 步驟要 {MIN_STEPS}–{MAX_STEPS} 步，目前 {len(item.steps)} 步")
        if not item.example.story.strip():
            errors.append(f"{where} 缺少範例")
        for figure in article_figures(item):
            if not figure_path(figure).is_file():
                errors.append(f"{where} 截圖不存在：{figure.src}")
        for slug in (*item.related, item.next_slug):
            if slug and slug not in slugs:
                errors.append(f"{where} 連到不存在的文章：{slug}")
    for stop in stops:
        if stop.article not in slugs:
            errors.append(f"主線連到不存在的文章：{stop.article}")
        if not figure_path(stop.figure).is_file():
            errors.append(f"主線截圖不存在：{stop.figure.src}")
    for tip in tips:
        if tip.article and tip.article not in slugs:
            errors.append(f"「你可能不知道」連到不存在的文章：{tip.article}")
    route_owner = {}
    for item in articles:
        for route in item.routes:
            if route in route_owner:
                errors.append(f"路由 {route} 同時對應〈{route_owner[route]}〉與〈{item.title}〉")
            route_owner[route] = item.title
    return errors
