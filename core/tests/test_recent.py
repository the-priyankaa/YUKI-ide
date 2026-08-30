"""Tests for recent.py — recently opened files."""
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from stdedit import recent


class TestRecentFiles(unittest.TestCase):
    def setUp(self):
        recent._recent = []
        self._orig_file = recent.RECENT_FILE
        self._tmpdir = tempfile.mkdtemp()
        recent.RECENT_FILE = Path(os.path.join(self._tmpdir, "recent.json"))

    def tearDown(self):
        recent._recent = []
        recent.RECENT_FILE = self._orig_file
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_add_and_get(self):
        recent.add_recent("/tmp/foo.py")
        self.assertEqual(recent.get_recent(), ["/tmp/foo.py"])

    def test_deduplication(self):
        recent.add_recent("/tmp/foo.py")
        recent.add_recent("/tmp/bar.py")
        recent.add_recent("/tmp/foo.py")
        self.assertEqual(recent.get_recent(), ["/tmp/foo.py", "/tmp/bar.py"])

    def test_max_entries(self):
        for i in range(60):
            recent.add_recent(f"/tmp/file{i}.py")
        self.assertLessEqual(len(recent.get_recent()), recent.MAX_ENTRIES)

    def test_remove(self):
        recent.add_recent("/tmp/foo.py")
        recent.add_recent("/tmp/bar.py")
        recent.remove_recent("/tmp/foo.py")
        self.assertEqual(recent.get_recent(), ["/tmp/bar.py"])

    def test_persistence(self):
        recent.add_recent("/tmp/foo.py")
        # Reload from disk
        recent._recent = []
        result = recent.get_recent()
        self.assertEqual(result, ["/tmp/foo.py"])

    def test_empty_path_ignored(self):
        recent.add_recent("")
        self.assertEqual(recent.get_recent(), [])

    def test_relative_path_normalized(self):
        recent.add_recent("foo.py")
        self.assertTrue(os.path.isabs(recent.get_recent()[0]))

    def test_corrupt_json_returns_empty(self):
        recent.RECENT_FILE.write_text("{not valid json!!!")
        recent._recent = []
        self.assertEqual(recent.get_recent(), [])

    def test_non_list_json_returns_empty(self):
        recent.RECENT_FILE.write_text('{"a": 1}')
        recent._recent = []
        self.assertEqual(recent.get_recent(), [])

    def test_save_failure_is_silently_ignored(self):
        # RECENT_FILE's parent is a regular file, so mkdir/write must fail.
        blocker = os.path.join(self._tmpdir, "blocker")
        with open(blocker, "w") as f:
            f.write("not a dir")
        recent.RECENT_FILE = Path(blocker) / "recent.json"
        recent.add_recent("/tmp/survives.py")
        # The in-memory list still carries the entry even though the disk
        # write failed, and nothing raised.
        self.assertEqual(recent.get_recent(), ["/tmp/survives.py"])


if __name__ == "__main__":
    unittest.main()
