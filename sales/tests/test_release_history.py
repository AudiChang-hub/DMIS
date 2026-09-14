from copy import deepcopy
from datetime import date
from unittest.mock import patch

from django.test import SimpleTestCase

from config.release_notes import CURRENT_VERSION, LEGACY_UPDATES, RELEASE as CURRENT_RELEASE, RELEASES
from config.release_validation import is_runtime_path, read_literal, validate_releases, validate_transition, version_tuple
from scripts import check_release

RELEASE = {"version": "1.0.0", "date": "2026-09-14", "title": "測試版本",
           "changes": ({"kind": "新增", "items": ("測試內容",)},)}


class ReleaseHistoryTests(SimpleTestCase):
    def test_current_release_has_one_source(self):
        validate_releases(RELEASES, LEGACY_UPDATES)
        self.assertIs(CURRENT_RELEASE, RELEASES[0])
        self.assertEqual(CURRENT_VERSION, CURRENT_RELEASE["version"])

    def test_semver_numeric_order_and_rejected_formats(self):
        self.assertGreater(version_tuple("1.10.0"), version_tuple("1.9.0"))
        for value in ("01.0.0", "1.0", "v1.0.0", "1.0.0-rc.1", "1.0.0+hash", "-1.0.0", "1.0.0\n", "1.1２.0", None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                version_tuple(value)

    def test_invalid_dates_titles_and_categories(self):
        for changes in ({"date": "2099-01-01"}, {"date": "2026-02-30"}, {"date": "20260914"},
                        {"title": " "}, {"changes": ()}, {"version": "0.9.0"},
                        {"changes": ({"kind": "未知", "items": ("內容",)},)},
                        {"changes": ({"kind": "新增", "items": (" ",)},)}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_releases(({**RELEASE, **changes},), today=date(2026, 9, 14))

    def test_duplicate_and_out_of_order_releases_fail(self):
        for entries in ((RELEASE, RELEASE), (RELEASE, {**RELEASE, "version": "1.1.0"}),
                        ({**RELEASE, "version": "1.1.0", "date": "2026-09-13"}, RELEASE)):
            with self.assertRaises(ValueError):
                validate_releases(entries, today=date(2026, 9, 14))

    def test_same_day_versions_and_valid_increments(self):
        for version in ("1.0.1", "1.1.0", "2.0.0"):
            current = ({**RELEASE, "version": version}, RELEASE)
            validate_releases(current)
            validate_transition(current, (RELEASE,), True)

    def test_old_release_cannot_be_modified_or_deleted(self):
        changed = deepcopy(RELEASE)
        changed["title"] = "覆寫舊版"
        for current in ((changed,), ({**RELEASE, "version": "1.1.0"},)):
            with self.assertRaisesMessage(ValueError, "不可刪除或覆寫"):
                validate_transition(current, (RELEASE,), True)

    def test_runtime_requires_version_bump_but_docs_do_not(self):
        validate_transition(RELEASES, RELEASES, False)
        validate_transition(RELEASES, (), True)
        with self.assertRaisesMessage(ValueError, "必須新增正式版號"):
            validate_transition(RELEASES, RELEASES, True)
        for path in ("sales/views.py", "templates/base.html", "static/css/ui-comfort.css", "static/images/logo.png", "config/release_notes.py", "scripts/deploy_django.sh", "requirements-django.txt"):
            self.assertTrue(is_runtime_path(path))
        for path in ("README.md", "docs/RELEASE_POLICY.md", "sales/tests/test_release_history.py"):
            self.assertFalse(is_runtime_path(path))

    def test_skipped_increment_and_nonzero_lower_digits_fail(self):
        for version in ("1.0.3", "1.2.0", "2.1.0", "3.0.0"):
            with self.assertRaises(ValueError):
                validate_transition(({**RELEASE, "version": version}, RELEASE), (RELEASE,), True)

    def test_historical_records_require_sources(self):
        with self.assertRaises(ValueError):
            validate_releases(RELEASES, ({**LEGACY_UPDATES[0], "commits": ()},))

    def test_literal_parser_does_not_execute_code(self):
        self.assertEqual(read_literal("raise RuntimeError('不可執行')\nRELEASES = ({'version': '1.0.0'},)", "RELEASES"), ({"version": "1.0.0"},))
        self.assertEqual(read_literal("RELEASE = {}", "RELEASES"), ())
        with self.assertRaises(ValueError):
            read_literal("RELEASES = tuple()", "RELEASES")

    def test_wrong_tag_is_rejected(self):
        with patch.object(check_release, "LEGACY_UPDATES", ()), patch("sys.argv", ["check_release", "--tag", "v9.9.9"]):
            with self.assertRaisesMessage(ValueError, "標籤與目前正式版號不符"):
                check_release.main()

    def test_tag_requires_annotated_exact_commit_and_clean_tree(self):
        for results in (("commit",), ("tag", "old", "new"), ("tag", "same", "same", " M changed")):
            with self.subTest(results=results), patch.object(check_release, "LEGACY_UPDATES", ()), patch.object(check_release, "git", side_effect=results), patch("sys.argv", ["check_release", "--tag", f"v{CURRENT_VERSION}"]):
                with self.assertRaises(ValueError):
                    check_release.main()

    def test_published_tag_is_baseline_not_unreleased_commits(self):
        with patch.object(check_release, "LEGACY_UPDATES", ()), patch.object(check_release, "git", side_effect=("v1.0.0", f"RELEASES = {RELEASES!r}", "sales/views.py")), patch("sys.argv", ["check_release", "--base", "a" * 40]):
            with self.assertRaisesMessage(ValueError, "必須新增正式版號"):
                check_release.main()
