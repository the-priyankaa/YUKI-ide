"""Tests for completion.py — path tab completion."""
import os
import shutil
import tempfile
import unittest

from stdedit.completion import complete_path, common_prefix


class TestCompletePath(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.d, "sub"))
        with open(os.path.join(self.d, "hello.py"), "w") as f:
            f.write("x")
        with open(os.path.join(self.d, "world.py"), "w") as f:
            f.write("y")

    def tearDown(self):
        shutil.rmtree(self.d)

    def test_empty_returns_empty(self):
        self.assertEqual(complete_path(""), [])

    def test_single_match(self):
        prefix = os.path.join(self.d, "hel")
        result = complete_path(prefix)
        self.assertEqual(len(result), 1)
        self.assertTrue(result[0].endswith("hello.py"))

    def test_multiple_matches(self):
        prefix = os.path.join(self.d, "w")
        result = complete_path(prefix)
        self.assertTrue(len(result) >= 1)

    def test_no_matches(self):
        prefix = os.path.join(self.d, "zzz")
        result = complete_path(prefix)
        self.assertEqual(result, [])

    def test_directory_gets_slash(self):
        prefix = os.path.join(self.d, "sub")
        result = complete_path(prefix)
        self.assertTrue(len(result) >= 1)
        self.assertTrue(result[0].endswith("/"))

    def test_expanduser(self):
        result = complete_path("~/nonexistent_abc_xyz")
        self.assertEqual(result, [])


class TestCommonPrefix(unittest.TestCase):
    def test_single(self):
        self.assertEqual(common_prefix(["/src/tui.py"]), "/src/tui.py")

    def test_multiple(self):
        self.assertEqual(
            common_prefix(["/src/tui.py", "/src/test.py"]),
            "/src/",
        )

    def test_empty(self):
        self.assertEqual(common_prefix([]), "")


if __name__ == "__main__":
    unittest.main()
