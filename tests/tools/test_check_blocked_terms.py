"""tools/check_blocked_terms.py 的行為測試；只用假詞，在暫存 git repo 裡跑，不碰 Django。"""
import contextlib
import importlib.util
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("check_blocked_terms", ROOT / "tools/check_blocked_terms.py")
scanner = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = scanner
spec.loader.exec_module(scanner)

FAKE_TERMS = "# 假清單\n測試禁詞甲\nzzfakeuser\n\n"
GIT_ENV = {
    "GIT_AUTHOR_NAME": "ci", "GIT_AUTHOR_EMAIL": "ci@example.invalid",
    "GIT_COMMITTER_NAME": "ci", "GIT_COMMITTER_EMAIL": "ci@example.invalid",
}


class BlockedTermsTests(unittest.TestCase):
    def setUp(self):
        self._cwd = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        os.chdir(self._tmp.name)
        self._env = dict(os.environ)
        os.environ.update(GIT_ENV)
        self.git("init", "-q", "-b", "main")
        self.write("README.md", "一般內容\n")
        self.base = self.commit("初始")

    def tearDown(self):
        os.chdir(self._cwd)
        os.environ.clear()
        os.environ.update(self._env)
        self._tmp.cleanup()

    def git(self, *args):
        return subprocess.run(["git", *args], check=True, capture_output=True, text=True,
                              encoding="utf-8").stdout.strip()

    def write(self, name, text):
        path = Path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def commit(self, message):
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)
        return self.git("rev-parse", "HEAD")

    def run_scan(self, terms=FAKE_TERMS, missing="fail", base=None):
        if terms is None:
            os.environ.pop("BLOCKED_TERMS", None)
        else:
            os.environ["BLOCKED_TERMS"] = terms
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = scanner.main(["--base", self.base if base is None else base, "--missing", missing])
        return code, out.getvalue()

    def assert_no_term_leak(self, output):
        for term in ("測試禁詞甲", "zzfakeuser"):
            self.assertNotIn(term, output)

    def test_hit_in_added_line_reports_file_and_line_only(self):
        self.write("docs/a.md", "第一行\n客戶：測試禁詞甲先生\n")
        self.commit("新增文件")
        code, output = self.run_scan()
        self.assertEqual(code, 1)
        self.assertIn("docs/a.md:2", output)
        self.assertIn("::error file=docs/a.md,line=2", output)
        self.assert_no_term_leak(output)

    def test_hit_in_commit_message(self):
        self.write("docs/b.md", "沒有問題\n")
        self.commit("修正\n\n帳號 ZZFakeUser 回報")
        code, output = self.run_scan()
        self.assertEqual(code, 1)
        self.assertIn("訊息第 3 行", output)
        self.assert_no_term_leak(output)

    def test_fullwidth_and_case_are_normalized(self):
        self.write("c.txt", "ＺＺＦＡＫＥＵＳＥＲ\n")
        self.commit("新增")
        self.assertEqual(self.run_scan()[0], 1)

    def test_hit_in_new_file_name(self):
        self.write("docs/測試禁詞甲.md", "內容\n")
        self.commit("新增")
        code, output = self.run_scan()
        self.assertEqual(code, 1)
        self.assert_no_term_leak(output)

    def test_no_hit_passes(self):
        self.write("docs/a.md", "王小明、測試客戶乙\nzzfakeusers running\n")
        self.commit("一般修改")
        code, output = self.run_scan()
        self.assertEqual(code, 0, output)
        self.assertIn("沒有命中", output)

    def test_existing_content_and_removed_lines_are_not_scanned(self):
        self.write("old.md", "測試禁詞甲\n")
        self.base = self.commit("舊資料")
        self.write("old.md", "已改成假名\n")
        self.commit("清理")
        self.assertEqual(self.run_scan()[0], 0)

    def test_hunk_lines_that_look_like_headers(self):
        self.write("x.sql", "-- zzfakeuser\n")
        self.commit("新增")
        code, output = self.run_scan()
        self.assertEqual(code, 1)
        self.assertIn("x.sql:1", output)

    def test_missing_secret_fails_on_push(self):
        for terms in (None, "", "\n# 只有註解\n"):
            with self.subTest(terms=terms):
                code, output = self.run_scan(terms=terms, missing="fail")
                self.assertEqual(code, 2)
                self.assertIn("::error::沒有 BLOCKED_TERMS", output)

    def test_missing_secret_skips_on_fork_pr(self):
        code, output = self.run_scan(terms=None, missing="skip")
        self.assertEqual(code, 0)
        self.assertIn("::warning::", output)

    def test_without_base_checks_latest_commit(self):
        self.write("a.md", "測試禁詞甲\n")
        self.commit("新增")
        code, output = self.run_scan(base="0" * 40)
        self.assertEqual(code, 1)
        self.assertIn("a.md:1", output)


if __name__ == "__main__":
    unittest.main()
