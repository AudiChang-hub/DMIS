"""文件與開發環境規則驗證；只讀檔案，不初始化 Django 或資料庫。"""
import re
import hashlib
import json
import subprocess
import tomllib
import unittest
import importlib.util
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[2]


class ContextPolicyTests(unittest.TestCase):
    def test_lookup_is_bounded_and_uses_current_symbols(self):
        spec = importlib.util.spec_from_file_location("context_lookup", ROOT / "tools/context_lookup.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for topic, expected in [("catalog", "listed_models"), ("importer", "_sales_transaction_key")]:
            with self.subTest(topic=topic):
                result = module.lookup(topic)
                self.assertIn(expected, result)
                self.assertIn("候選測試", result)
                self.assertLessEqual(len(result), 6500)
                self.assertNotIn("archive/", result)
                self.assertNotIn("migrations/", result)

    def test_archives_preserve_original_content(self):
        manifest = json.loads((ROOT / "docs/archive/2026-09-19/manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(len(manifest["files"]), 15)
        for entry in manifest["files"]:
            text = (ROOT / entry["archive"]).read_text(encoding="utf-8").rstrip()
            self.assertEqual(hashlib.sha256(text.encode("utf-8")).hexdigest(), entry["sha256"], entry["source"])

    def test_hot_context_budget(self):
        paths = ["AGENTS.md", "docs/context/CURRENT_STATE.md"]
        self.assertLessEqual(sum((ROOT / p).stat().st_size for p in paths), 8000)
        for p in paths:
            self.assertLessEqual((ROOT / p).stat().st_size, 5000)

    def test_routing_and_current_context(self):
        agent = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        for expected in ["CURRENT_STATE.md", "legacy_import.py", "catalog_views.py", "HANDOFF.md"]:
            self.assertIn(expected, agent)
        rules = (ROOT / "docs/context/BUSINESS_RULES.md").read_text(encoding="utf-8")
        self.assertIn("不是已實作的唯一約束", rules)
        for path in ["sales/catalog_views.py", "sales/services/catalog_selection.py",
                     "sales/services/legacy_import.py", "sales/services/legacy_finance.py",
                     "sales/tests/test_catalog_color_list.py", "sales/tests/test_catalog_management.py",
                     "sales/tests/test_catalog_selection.py", "sales/tests/test_legacy_import.py",
                     "sales/tests/test_legacy_finance.py"]:
            self.assertTrue((ROOT / path).is_file(), path)

    def test_live_document_links(self):
        paths = [ROOT / name for name in ["README.md", "AGENTS.md", "GEMINI.md",
                 "docs/CONSTITUTION.md", ".github/copilot-instructions.md", "specs/README.md",
                 "docs/archive/README.md"]]
        for folder in ["docs/context", "docs/reference", "docs/architecture",
                       ".github/prompts", "specs/055-least-context"]:
            paths.extend((ROOT / folder).glob("*.md"))
        for path in paths:
            text = re.sub(r"```.*?```", "", path.read_text(encoding="utf-8"), flags=re.S)
            for link in re.findall(r"\]\(([^)]+)\)", text):
                target = link.split("#", 1)[0]
                if not target or re.match(r"[a-z]+:", target):
                    continue
                with self.subTest(path=str(path.relative_to(ROOT)), link=target):
                    self.assertTrue((path.parent / unquote(target)).exists())

    def test_config_is_scoped_and_limited(self):
        config = tomllib.loads((ROOT / ".codex/config.toml").read_text(encoding="utf-8"))
        self.assertEqual(config["tool_output_token_limit"], 4096)
        self.assertEqual(config["agents"]["max_concurrent_threads_per_session"], 2)
        for forbidden in ["model", "model_reasoning_effort", "sandbox_mode", "notify", "mcp_servers"]:
            self.assertNotIn(forbidden, config)
        for name in ["sites@openai-curated-remote", "visualize@openai-bundled",
                     "template-creator@openai-primary-runtime"]:
            self.assertFalse(config["plugins"][name]["enabled"])
        cua = config["plugins"]["unified-computer-use@openai-bundled"]["mcp_servers"]["cua_repl"]
        self.assertEqual(set(cua["enabled_tools"]), {"js", "js_reset", "turn_ended"})
        self.assertEqual(cua["tools"]["js"]["output_token_limit"], 6000)

    def test_ignore_preserves_examples_and_fixtures(self):
        for path, ignored in [
            (".env.django.example", False), ("tests/fixtures/context-sample.xlsx", False),
            ("tests/fixtures/context-sample.pdf", False), ("sales/catalog_views.py", False),
            (".codex/config.toml", False), (".env.django", True),
            (".env.local", True), (".env.example", False),
            ("backups/context.sql", True), (".pytest_cache/context", True),
            ("output/context.xlsx", True), (".codex-tmp/context-qa/result.txt", True),
        ]:
            result = subprocess.run(["git", "check-ignore", "--no-index", "-q", path], cwd=ROOT)
            self.assertIn(result.returncode, (0, 1))
            self.assertEqual(result.returncode == 0, ignored, path)

    def test_handoff_is_latest_only(self):
        text = (ROOT / "docs/context/HANDOFF.md").read_text(encoding="utf-8")
        for title in ["更新日期", "本次完成", "修改檔案", "驗證結果", "尚未完成",
                      "已知風險", "下一步", "下一位 Agent 建議先看"]:
            self.assertIn(title, text)
        self.assertLessEqual(len(text.encode("utf-8")), 6000)


if __name__ == "__main__":
    unittest.main()
