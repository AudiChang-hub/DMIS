"""把只有單一模組用到的規則從 app.css 搬到 static/css/<模組>.css（T-242 A 案）。不進 CI，本機手動執行。

用法：python tools/ui_audit/css_split.py <批次名> [--dry-run]
批次定義在 BATCHES：每個模組有輸出檔、class 前綴、頁面模板。

搬移條件（只搬、不改規則內容）：
- 選擇器的每一個逗號段都至少含一個模組前綴的 class（才保證只會在該模組頁面生效）；
- 這些模組 class 只出現在模組自己的模板（含它們 include 的片段）與它們載入的 JS 裡；
  出現在其他模板、其他 JS 或 sales/ 程式（可能動態產生 class）就留在 app.css；
- @keyframes、@font-face 不搬（app.css 每頁都載入，動畫名稱照樣找得到）。
搬出的規則保持原本先後順序，外層 @media／@supports 原樣包回；模組 CSS 的 <link> 放在該頁 {% block head %} 最前面，
讓層疊順序維持「app.css → 搬出的規則 → 頁面原本的模組 CSS」。
"""
import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from css_coverage import parse_rules  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "static" / "css" / "app.css"
CLASS = re.compile(r"\.([A-Za-z_][\w-]*)")
# keep：搬出去會改變結果的規則（原本被 app.css 後段同特異度的規則蓋過，搬到模組 CSS 後反而會贏）。
# 由 style_diff.py 逐元素比對 computed style 找出，留在 app.css 原位，層疊結果才完全不變。
BATCHES = {
    "1": [
        {"css": "price-list.css", "title": "價格表分發與分工（T-242 自 app.css 搬出）",
         "prefixes": ("price-distribution", "price-assignment"),
         "pages": ("sales/price_list_distribution.html", "sales/price_list_distribution_assignments.html"),
         "keep": (".price-distribution-note textarea", ".price-assignment-picker", ".price-distribution-hero")},
        {"css": "dealer-rewards.css", "title": "車行獎勵活動與品項（T-242 自 app.css 搬出）",
         "prefixes": ("dealer-reward",),
         "pages": ("sales/dealer_reward_campaign_form.html", "sales/dealer_reward_campaign_list.html",
                   "sales/dealer_reward_catalog_form.html", "sales/dealer_reward_catalog_list.html"),
         "keep": (".dealer-reward-item__header .button", ".dealer-reward-cost-row__header .button")},
        {"css": "catalog-photo-board.css", "title": "車色圖片看板（T-242 自 app.css 搬出）",
         "prefixes": ("photo-board", "photo-cell"),
         "pages": ("sales/catalog_photo_board.html",)},
        {"css": "business-holidays.css", "title": "工作日與假日設定（T-242 自 app.css 搬出）",
         "prefixes": ("holiday-calendar",),
         "pages": ("sales/business_holiday_list.html",),
         "keep": (".holiday-calendar-hero", ".holiday-calendar-field input", ".holiday-calendar-active input")},
    ],
    "2": [
        {"css": "registration-fee-rules.css", "title": "領牌與強制險規則（T-242 自 app.css 搬出）",
         "prefixes": ("registration-rule",), "pages": ("sales/brand_registration_fee_rule_list.html",),
         "keep": (".registration-rule-panel__heading",)},
        {"css": "vehicle-models.css", "title": "機種與售價、車輛品牌（T-242 自 app.css 搬出）",
         "prefixes": ("vehicle-model", "vehicle-brand", "master-model"),
         "pages": ("sales/vehicle_brand_list.html", "sales/vehicle_model_list.html", "sales/vehicle_model_form.html",
                   "sales/vehicle_model_batch.html", "sales/vehicle_model_copy.html", "sales/vehicle_model_installment_batch.html",
                   "sales/settlement_cost_rule_form.html", "sales/settlement_cost_rule_list.html",
                   "sales/vehicle_model_price_versions.html", "sales/vehicle_model_settlement_costs.html",
                   "sales/vehicle_model_commission.html", "sales/vehicle_model_incentives.html", "sales/vehicle_model_rules.html",
                   "sales/catalog_edit.html", "sales/installment_plan_list.html"),
         "keep": (".master-model-section", ".master-model-grid")},
        {"css": "sales-sources.css", "title": "車行與年節送禮名單（T-242 自 app.css 搬出）",
         "prefixes": ("source-line", "holiday-gift"),
         "pages": ("sales/sales_source_list.html", "sales/sales_source_holiday_gift_manage.html"),
         "keep": (".holiday-gift-summary",)},
        {"css": "order-deletion-queue.css", "title": "刪除審核（T-242 自 app.css 搬出）",
         "prefixes": ("deletion-review",), "pages": ("sales/order_deletion_queue.html",)},
        {"css": "inventory-quick-entry.css", "title": "快速進車（T-242 自 app.css 搬出）",
         "prefixes": ("quick-entry",), "pages": ("sales/inventory_quick_form.html",)},
        {"css": "accessory-bulk.css", "title": "配件與工資批次修改（T-242 自 app.css 搬出）",
         "prefixes": ("accessory-bulk",), "pages": ("sales/accessory_product_list.html",)},
        {"css": "reconciliation.css", "title": "統一撥款對帳（T-242 自 app.css 搬出）",
         "prefixes": ("reconciliation-table",), "pages": ("sales/reconciliation_list.html",)},
    ],
    # 第三批：同一頁已有前一批的模組 CSS 時另開新檔（新檔放在 head 最前面，排在前一批的檔案之前）。
    "3": [
        {"css": "system-integrity-report.css", "title": "系統完整性報告（T-242 自 app.css 搬出）",
         "prefixes": ("integrity-",), "pages": ("sales/system_integrity_report.html",),
         "keep": (".integrity-report-hero", ".integrity-report-meta")},
        {"css": "system-diagnostics.css", "title": "系統狀態（T-242 自 app.css 搬出）",
         "prefixes": ("system-status",), "pages": ("sales/system_diagnostics.html",), "keep": (".system-status-help",)},
        {"css": "dashboard-home.css", "title": "首頁待辦與開始（T-242 自 app.css 搬出）",
         "prefixes": ("home-task", "home-start", "home-link", "news-tabs", "news-row", "news-center"),
         "pages": ("sales/dashboard.html",)},
        {"css": "order-list.css", "title": "訂單列表篩選與排序（T-242 自 app.css 搬出）",
         "prefixes": ("order-sort", "order-filter", "order-drilldown", "sort-chip", "order-list"),
         "pages": ("sales/order_list.html",),
         "keep": (".order-filter-bar", ".order-filter-bar input, .order-filter-bar select", ".order-drilldown > a:not(.button)",
                  ".order-list-hero .hero-actions > .button", ".order-filter-open", ".order-sort-open")},
        {"css": "inventory-list.css", "title": "庫存列表（T-242 自 app.css 搬出）",
         "prefixes": ("inventory-sort", "inventory-filters", "inventory-priority", "inventory-table",
                      "inventory-condition", "inventory-search"),
         "pages": ("sales/inventory_list.html",), "keep": (".inventory-table--stock :is(th, td)",)},
        {"css": "reconciliation-page.css", "title": "統一撥款對帳頁面框架（T-242 自 app.css 搬出）",
         "prefixes": ("reconciliation-guide", "reconciliation-shell", "reconciliation-pick", "reconciliation-channel",
                      "reconciliation-expected", "reconciliation-order"),
         "pages": ("sales/reconciliation_list.html",)},
        {"css": "legacy-import.css", "title": "Excel 匯入（T-242 自 app.css 搬出）",
         "prefixes": ("import-steps", "import-upload", "import-batch", "import-list", "import-sheet", "import-page"),
         "pages": ("sales/legacy_import_list.html", "sales/legacy_import_detail.html"),
         # .import-list-heading 原本被後面同特異度的 .import-preview-heading（min-height 96px）蓋過，搬出去會反過來贏。
         "keep": (".import-upload-form > .button", ".import-list-heading")},
        {"css": "home-favorites.css", "title": "首頁常用功能設定（T-242 自 app.css 搬出）",
         "prefixes": ("favorites-", "favorite-"), "pages": ("sales/home_favorites.html",)},
        {"css": "user-management.css", "title": "帳號管理（T-242 自 app.css 搬出）",
         "prefixes": ("account-audit", "account-panel", "account-row", "account-identity", "account-filter",
                      "account-login", "account-avatar"),
         "pages": ("sales/user_management.html",), "keep": (".account-panel__header h2", ".account-identity h3")},
        {"css": "sales-source-pages.css", "title": "車行列表與編輯（T-242 自 app.css 搬出）",
         "prefixes": ("source-region", "line-group", "source-holiday", "cooperation-summary", "source-district",
                      "source-map", "source-record", "source-system"),
         "pages": ("sales/sales_source_list.html", "sales/sales_source_form.html"),
         "keep": (".line-group-presence", ".source-system-info", ".source-system-info dl",
                  # T-267 手機版「完整顯示文字」的 :is(…, .source-system-info dd, …) 同特異度、排在後面，搬出去會反過來蓋掉它。
                  ".source-system-info dd")},
        {"css": "dealer-programs.css", "title": "車行銷售方案（T-242 自 app.css 搬出）",
         "prefixes": ("dealer-program",),
         "pages": ("sales/dealer_sales_program_list.html", "sales/dealer_reward_campaign_form.html",
                   "sales/vehicle_model_commission.html"),
         "keep": (".dealer-program-directory-table", ".dealer-program-directory-table .inventory-row-action .button",
                  ".dealer-program-directory-table tr", ".dealer-program-directory-table td")},
    ],
}


def split_selector(selector):
    """只在最外層逗號切開選擇器清單；:is(th, td) 這種括號裡的逗號不切。"""
    parts, depth, current = [], 0, ""
    for ch in selector:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(current); current = ""
        else:
            current += ch
    parts.append(current)
    return [part for part in parts if part.strip()]


def required_classes(part):
    """選擇器一段裡「一定要有」的 class：括號外的才算。:is(.a, .b) 裡的只是其中一個選項，不能保證只在模組頁生效。"""
    outside, depth = "", 0
    for ch in part:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif depth == 0:
            outside += ch
    return set(CLASS.findall(outside))


def template_closure(pages):
    """頁面模板加上它們 include 的片段（遞迴），以及它們載入的 JS。"""
    files, queue = set(), list(pages)
    while queue:
        name = queue.pop()
        path = ROOT / "templates" / name
        if name in files or not path.exists():
            continue
        files.add(name)
        text = path.read_text(encoding="utf-8")
        queue += re.findall(r"{%\s*include\s+[\"']([^\"']+)[\"']", text)
        files.update("static/js/" + js for js in re.findall(r"static\s+'js/([\w.-]+\.js)'", text))
    return files


def token_index():
    index = defaultdict(set)
    sources = [(p, "templates/" + p.relative_to(ROOT / "templates").as_posix()) for p in (ROOT / "templates").rglob("*.html")]
    sources += [(p, "static/js/" + p.name) for p in (ROOT / "static" / "js").glob("*.js")]
    sources += [(p, "py:" + p.relative_to(ROOT).as_posix()) for p in (ROOT / "sales").rglob("*.py")
                if "tests" not in p.parts and "migrations" not in p.parts]
    for path, label in sources:
        for token in set(re.findall(r"[A-Za-z_][\w-]*", path.read_text(encoding="utf-8", errors="ignore"))):
            index[token].add(label.replace("templates/", "") if label.startswith("templates/") else label)
    return index


def plan(batch):
    text = APP.read_text(encoding="utf-8")
    rules = parse_rules(text)
    index = token_index()
    moves = defaultdict(list)
    kept = defaultdict(list)
    for module in BATCHES[batch]:
        own = template_closure(module["pages"])
        for start, end, selector, conditions in rules:
            parts = split_selector(selector)
            module_classes = [{c for c in required_classes(part) if c.startswith(module["prefixes"])} for part in parts]
            if not any(module_classes) and any(c.startswith(module["prefixes"]) for c in CLASS.findall(selector)):
                kept[module["css"]].append((selector, "模組 class 只出現在 :is() 等選項裡，其他頁也可能符合"))
                continue
            if not any(module_classes):
                continue
            if " ".join(selector.split()) in module.get("keep", ()):
                kept[module["css"]].append((selector, "層疊衝突：搬出會改變結果"))
                continue
            if not all(module_classes):
                kept[module["css"]].append((selector, "選擇器有一段不含模組 class"))
                continue
            outside = {f for cls in set().union(*module_classes) for f in index.get(cls, ()) if f not in own}
            if outside:
                kept[module["css"]].append((selector, "也出現在 " + ", ".join(sorted(outside)[:3])))
                continue
            moves[module["css"]].append((start, end, conditions))
    return text, moves, kept


def render_module(text, title, rules):
    """依原順序輸出；相鄰而外層條件相同的規則放在同一個 @media 區塊裡。"""
    lines, current = [f"/* {title}：只搬、不改規則內容，規則之間保持原本的先後順序；本檔在該頁其他模組 CSS 之前載入。 */"], None
    for start, end, conditions in rules:
        rule = text[start:end].replace("\r\n", "\n")
        if conditions != current:
            if current:
                lines.append("}" * len(current))
            for depth, condition in enumerate(conditions):
                lines.append("  " * depth + condition + " {")
            current = conditions
        lines.append("  " * len(conditions) + rule)
    if current:
        lines.append("}" * len(current))
    return "\n".join(lines) + "\n"


def remove_rules(text, spans):
    """從 app.css 刪掉搬走的規則（連同同一行後面的空白與換行）；變空的 @media 區塊一起刪。"""
    for start, end in sorted(spans, reverse=True):
        stop = end
        while stop < len(text) and text[stop] in " \t":
            stop += 1
        if text.startswith("\r\n", stop):
            stop += 2
        elif stop < len(text) and text[stop] == "\n":
            stop += 1
        begin = start
        while begin > 0 and text[begin - 1] in " \t":
            begin -= 1
        text = text[:begin] + text[stop:]
    empty = re.compile(r"(?m)^[ \t]*@(media|supports)[^{]*\{\s*\}[ \t]*\r?\n?")
    while empty.search(text):
        text = empty.sub("", text)
    return text


def link_pages(batch):
    for module in BATCHES[batch]:
        tag = "<link rel=\"stylesheet\" href=\"{% static 'css/" + module["css"] + "' %}\">"
        for name in module["pages"]:
            path = ROOT / "templates" / name
            source = path.read_text(encoding="utf-8")
            if module["css"] in source:
                continue
            if "{% block head %}" in source:
                source = source.replace("{% block head %}", "{% block head %}" + tag, 1)
            else:
                first = source.index("\n")
                source = source[:first + 1] + "{% block head %}" + tag + "{% endblock %}\n" + source[first + 1:]
            # {% load static %} 必須排在 {% block head %} 之前；原本寫在後面的那一行移到第一行。
            head = source.index("{% block head %}")
            if not re.search(r"{%\s*load\s[^%]*\bstatic\b", source[:head]):
                source = re.sub(r"(?m)^{%\s*load static\s*%}\n", "", source, count=1)
                # extends 可能用單引號或雙引號（例如 order_deletion_queue.html 用單引號）。
                source = re.sub(r"({%\s*extends\s+['\"][^'\"]+['\"]\s*%})", r"\1{% load static %}", source, count=1)
            path.write_text(source, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("batch", choices=sorted(BATCHES))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    text, moves, kept = plan(args.batch)
    total_rules = total_bytes = 0
    for module in BATCHES[args.batch]:
        rules = moves[module["css"]]
        size = sum(len(text[s:e].replace("\r\n", "\n").encode()) for s, e, _ in rules)
        total_rules += len(rules); total_bytes += size
        print(f"{module['css']}: 搬 {len(rules)} 條、{size / 1024:.1f} KB；留在 app.css {len(kept[module['css']])} 條")
        for selector, reason in kept[module["css"]][:12]:
            print("   留：", " ".join(selector.split())[:90], "—", reason)
    print(f"合計搬出 {total_rules} 條、{total_bytes / 1024:.1f} KB")
    if args.dry_run:
        return
    spans = []
    for module in BATCHES[args.batch]:
        rules = moves[module["css"]]
        if not rules:
            continue
        target = ROOT / "static" / "css" / module["css"]
        if target.exists():
            raise SystemExit(f"{target} 已存在：請先確認要不要合併，再改 BATCHES")
        target.write_text(render_module(text, module["title"], rules), encoding="utf-8")
        spans += [(s, e) for s, e, _ in rules]
    APP.write_text(remove_rules(text, spans), encoding="utf-8", newline="")
    link_pages(args.batch)


if __name__ == "__main__":
    main()
