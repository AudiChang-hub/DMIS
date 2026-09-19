"""只讀、有限輸出的任務定位器；不 import Django、不連 DB、不掃描目錄。"""
import argparse
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTES = {
    "catalog": {
        "section": "車型、車色與方案",
        "source": "sales/catalog_views.py",
        "symbols": ("listed_models", "catalog"),
        "related": ("sales/services/catalog_selection.py",
                    "templates/sales/catalog.html", "templates/sales/catalog_detail.html"),
        "tests": "sales/tests/test_catalog_color_list.py",
        "patterns": ("color", "year"),
    },
    "importer": {
        "section": "Excel 匯入與識別",
        "source": "sales/services/legacy_import.py",
        "symbols": ("_sales_transaction_key",),
        "related": ("sales/services/legacy_finance.py",),
        "tests": "sales/tests/test_legacy_import.py",
        "patterns": ("duplicate", "deleted_import", "resale"),
    },
}


def lookup(topic):
    route = ROUTES[topic]
    lines = ["# 唯讀定位：" + topic, "未指定實際錯誤時，停在這份入口，不展開整個相依圖。",
             "此輸出不是已診斷原因；重大邏輯變更須先 A／B，既有批准依範圍執行。", ""]
    rules_path = "docs/context/BUSINESS_RULES.md"
    rules = (ROOT / rules_path).read_text(encoding="utf-8")
    heading = "## " + route["section"]
    section = rules.split(heading + "\n", 1)[1].split("\n## ", 1)[0].strip()
    lines += [rules_path + " — " + heading, section, ""]
    source = (ROOT / route["source"]).read_text(encoding="utf-8")
    source_lines = source.splitlines()
    tree = ast.parse(source)
    for name in route["symbols"]:
        node = next((n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                     and n.name == name), None)
        if node is None:
            raise ValueError("路由已失效，找不到：" + name)
        end = min(node.end_lineno, node.lineno + 79)
        lines += [f"{route['source']}:{node.lineno} — {name}",
                  *[f"{i + 1}: {source_lines[i]}" for i in range(node.lineno - 1, end)], ""]
        if node.end_lineno > end:
            lines.append(f"函式其餘內容未展開，必要時定位 {end + 1}–{node.end_lineno}。")
    tests = ast.parse((ROOT / route["tests"]).read_text(encoding="utf-8"))
    lines.append("候選測試（名稱／位置，未執行）：")
    count = 0
    for node in ast.walk(tests):
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_") and any(
                pattern in node.name for pattern in route["patterns"]):
            lines.append(f"- {route['tests']}:{node.lineno} {node.name}")
            count += 1
            if count == 6:
                break
    lines += ["", "需要才讀：" + "、".join(route["related"])]
    result = "\n".join(lines)
    if len(result) > 6500:
        raise ValueError("定位輸出超過 6500 字元，請維護路由，不輸出整檔")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("topic", choices=ROUTES)
    args = parser.parse_args()
    print(lookup(args.topic))


if __name__ == "__main__":
    main()
