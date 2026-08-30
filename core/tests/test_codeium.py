"""Tests for the Codeium AI completion client."""
import json
import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from stdedit.codeium import (
    get_api_key, set_api_key, _key_path,
    _extract_prefix, _extract_suffix, _language_id,
    Completion, get_completion,
)


class TestKeyStorage(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._orig_key_path = _key_path.__wrapped__ if hasattr(_key_path, '__wrapped__') else None

    @patch("os.path.expanduser")
    def test_set_and_get_key(self, mock_expand):
        mock_expand.return_value = self._tmpdir
        # Patch the key_path function to use our temp dir
        with patch("stdedit.codeium._key_path",
                   return_value=os.path.join(self._tmpdir, "codeium_key")):
            set_api_key("test-key-123")
            key = get_api_key()
            self.assertEqual(key, "test-key-123")

    def test_get_key_missing_file(self):
        with patch("stdedit.codeium._key_path",
                   return_value="/nonexistent/path/key"):
            self.assertEqual(get_api_key(), "")

    @patch("os.path.expanduser")
    def test_key_file_is_owner_only(self, mock_expand):
        mock_expand.return_value = self._tmpdir
        keyfile = os.path.join(self._tmpdir, "codeium_key")
        with patch("stdedit.codeium._key_path", return_value=keyfile):
            set_api_key("secret-key-xyz")
        mode = os.stat(keyfile).st_mode & 0o777
        self.assertEqual(mode, 0o600, "key file must be owner-readable only")

    def test_language_id_python(self):
        self.assertEqual(_language_id("foo.py"), "python")

    def test_language_id_javascript(self):
        self.assertEqual(_language_id("app.js"), "javascript")

    def test_language_id_typescript(self):
        self.assertEqual(_language_id("mod.ts"), "typescript")

    def test_language_id_unknown(self):
        self.assertEqual(_language_id("foo.xyz"), "plaintext")


class TestExtractContext(unittest.TestCase):
    def test_prefix_basic(self):
        lines = ["line 0", "line 1", "line 2"]
        prefix = _extract_prefix(lines, 2, 6)
        self.assertIn("line 0", prefix)
        self.assertIn("line 2", prefix)

    def test_prefix_at_start(self):
        lines = ["line 0"]
        prefix = _extract_prefix(lines, 0, 0)
        self.assertEqual(prefix, "")

    def test_prefix_truncates_at_cursor(self):
        lines = ["hello world"]
        prefix = _extract_prefix(lines, 0, 5)
        self.assertEqual(prefix, "hello")

    def test_suffix_basic(self):
        lines = ["line 0", "line 1", "line 2"]
        suffix = _extract_suffix(lines, 1, 0)
        self.assertIn("line 1", suffix)
        self.assertIn("line 2", suffix)

    def test_suffix_empty_at_end(self):
        lines = ["line 0"]
        suffix = _extract_suffix(lines, 1, 0)
        self.assertEqual(suffix, "")

    def test_suffix_truncates_at_cursor(self):
        lines = ["hello world", "next"]
        suffix = _extract_suffix(lines, 0, 5)
        self.assertEqual(suffix, " world\nnext")


class TestCompletionObject(unittest.TestCase):
    def test_basic(self):
        c = Completion("print('hi')", start_y=0, start_x=5)
        self.assertEqual(c.text, "print('hi')")
        self.assertEqual(c.range_start_y, 0)
        self.assertEqual(c.range_start_x, 5)

    def test_repr(self):
        c = Completion("short text")
        r = repr(c)
        self.assertIn("Completion", r)


class TestGetCompletion(unittest.TestCase):
    @patch("subprocess.run")
    def test_success(self, mock_run):
        response = {
            "completions": [
                {"text": "    return x + 1\n"}
            ]
        }
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps(response),
            stderr="",
        )
        result = get_completion(
            ["def add(x):", "    "],
            cursor_y=1, cursor_x=4,
            filename="test.py",
            api_key="fake-key",
        )
        self.assertIsNotNone(result)
        self.assertIn("return", result.text)

    @patch("subprocess.run")
    def test_no_completions(self, mock_run):
        response = {"completions": []}
        mock_run.return_value = MagicMock(
            returncode=0, stdout=json.dumps(response), stderr="",
        )
        result = get_completion(["x = 1"], 0, 4, api_key="fake")
        self.assertIsNone(result)

    @patch("subprocess.run")
    def test_network_error(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="fail")
        result = get_completion(["x = 1"], 0, 4, api_key="fake")
        self.assertIsNone(result)

    @patch("subprocess.run")
    def test_timeout(self, mock_run):
        import subprocess as sp
        mock_run.side_effect = sp.TimeoutExpired("curl", 8)
        result = get_completion(["x = 1"], 0, 4, api_key="fake")
        self.assertIsNone(result)

    def test_no_key_returns_none(self):
        with patch("stdedit.codeium.get_api_key", return_value=""):
            result = get_completion(["x = 1"], 0, 4)
            self.assertIsNone(result)

    @patch("subprocess.run")
    def test_different_data_format(self, mock_run):
        response = {
            "data": {
                "completions": [
                    {"completion": "print('hello')"}
                ]
            }
        }
        mock_run.return_value = MagicMock(
            returncode=0, stdout=json.dumps(response), stderr="",
        )
        result = get_completion([""], 0, 0, api_key="key")
        self.assertIsNotNone(result)


if __name__ == "__main__":
    unittest.main()
