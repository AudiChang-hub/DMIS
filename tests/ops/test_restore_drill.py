import gzip
from pathlib import Path
import sys
import tempfile
import unittest

if sys.platform != "win32":
    from scripts.restore_drill import dump_counts, file_hashes


@unittest.skipIf(sys.platform == "win32", "正式演練使用 Linux flock")
class BackupValidationTests(unittest.TestCase):
    def test_counts_rows_per_copy_table(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "dump.sql.gz"
            with gzip.open(path, "wt", encoding="utf-8") as out:
                out.write("COPY public.sales_salesorder (id, name) FROM stdin;\n1\tA\n2\tB\\nC\n\\.\n")
                out.write("COPY public.empty_table (id) FROM stdin;\n\\.\n")
            self.assertEqual(dump_counts(path), {"sales_salesorder": 2, "empty_table": 0})

    def test_invalid_and_truncated_dump_fail(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "dump.sql.gz"
            path.write_bytes(b"not gzip")
            with self.assertRaises(OSError):
                dump_counts(path)
            with gzip.open(path, "wt") as out:
                out.write("-- empty backup")
            with self.assertRaises(ValueError):
                dump_counts(path)

    def test_hashes_change_and_symlinks_fail(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "file").write_bytes(b"before")
            initial = file_hashes(root)
            (root / "file").write_bytes(b"after")
            self.assertNotEqual(initial, file_hashes(root))
            (root / "link").symlink_to(root / "file")
            with self.assertRaises(ValueError):
                file_hashes(root)
