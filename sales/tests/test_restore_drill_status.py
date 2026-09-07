import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from django.test import SimpleTestCase, override_settings

from sales.services.restore_drill_status import restore_drill_status


class RestoreDrillStatusTests(SimpleTestCase):
    def read(self, record):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "status.json"
            path.write_text(json.dumps(record), encoding="utf-8")
            with override_settings(RESTORE_DRILL_STATUS_PATH=str(path)):
                return restore_drill_status()

    def record(self, **changes):
        return {"status": "success", "checked_at": datetime.now(timezone.utc).isoformat(),
                "tables": 2, "rows": 20, "media_files": 3, "duration_seconds": 8, **changes}

    def test_success_whitelists_only_summary(self):
        result = self.read(self.record(password="never-render"))
        self.assertTrue(result["success"])
        self.assertNotIn("password", result)

    def test_failed_stale_running_missing_and_malformed_are_not_success(self):
        for item in ({}, None, [], self.record(status="failed"), self.record(rows="bad"),
                     self.record(checked_at="invalid"), self.record(status="running"),
                     self.record(checked_at=(datetime.now(timezone.utc)-timedelta(days=9)).isoformat())):
            with self.subTest(item=item):
                self.assertFalse(self.read(item)["success"])
        with override_settings(RESTORE_DRILL_STATUS_PATH="/missing/status.json"):
            self.assertFalse(restore_drill_status()["success"])
