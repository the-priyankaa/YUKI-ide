"""Tests for clipboard.py — best-effort system clipboard helpers."""
import subprocess
import unittest
from unittest.mock import patch, MagicMock

import stdedit.clipboard as cb


class ClipboardTestCase(unittest.TestCase):
    """Reset the cached tool detection before and after each test."""

    def setUp(self):
        self._orig_copy, self._orig_paste = cb._copy_cmd, cb._paste_cmd
        cb._copy_cmd = cb._paste_cmd = None

    def tearDown(self):
        cb._copy_cmd, cb._paste_cmd = self._orig_copy, self._orig_paste


class TestDetection(ClipboardTestCase):
    def test_wayland_preferred(self):
        with patch("stdedit.clipboard.shutil.which", side_effect=lambda n: f"/usr/bin/{n}") as which:
            copy, paste = cb._detect()
        self.assertEqual(copy, ["wl-copy"])
        self.assertEqual(paste, ["wl-paste", "--no-newline"])
        which.assert_any_call("wl-copy")

    def test_xclip_fallback(self):
        def fake_which(name):
            if name == "xclip":
                return "/usr/bin/xclip"
            return None
        with patch("stdedit.clipboard.shutil.which", side_effect=fake_which):
            copy, paste = cb._detect()
        self.assertEqual(copy, ["xclip", "-selection", "clipboard"])
        self.assertEqual(paste, ["xclip", "-selection", "clipboard", "-o"])

    def test_macos_pbcopy_fallback(self):
        def fake_which(name):
            if name in ("pbcopy", "pbpaste"):
                return f"/usr/bin/{name}"
            return None
        with patch("stdedit.clipboard.shutil.which", side_effect=fake_which):
            copy, paste = cb._detect()
        self.assertEqual(copy, ["pbcopy"])
        self.assertEqual(paste, ["pbpaste"])

    def test_nothing_available(self):
        with patch("stdedit.clipboard.shutil.which", return_value=None):
            self.assertEqual(cb._detect(), (None, None))


class TestSysCopy(ClipboardTestCase):
    def _detect_xclip(self):
        def fake_which(name):
            return "/usr/bin/xclip" if name == "xclip" else None
        patch("stdedit.clipboard.shutil.which", side_effect=fake_which).start()
        self.addCleanup(patch.stopall)

    def test_writes_text_and_returns_true(self):
        self._detect_xclip()
        result = MagicMock(returncode=0)
        with patch("stdedit.clipboard.subprocess.run", return_value=result) as run:
            self.assertTrue(cb.sys_copy("hello"))
            run.assert_called_once()
            self.assertEqual(run.call_args[0][0], ["xclip", "-selection", "clipboard"])
            self.assertEqual(run.call_args.kwargs["input"], b"hello")

    def test_nonzero_returncode_is_failure(self):
        self._detect_xclip()
        with patch("stdedit.clipboard.subprocess.run",
                   return_value=MagicMock(returncode=1)):
            self.assertFalse(cb.sys_copy("x"))

    def test_no_tool_is_failure(self):
        with patch("stdedit.clipboard.shutil.which", return_value=None):
            self.assertFalse(cb.sys_copy("x"))

    def test_subprocess_error_is_failure(self):
        self._detect_xclip()
        with patch("stdedit.clipboard.subprocess.run",
                   side_effect=OSError("boom")):
            self.assertFalse(cb.sys_copy("x"))

    def test_timeout_is_failure(self):
        self._detect_xclip()
        with patch("stdedit.clipboard.subprocess.run",
                   side_effect=subprocess.TimeoutExpired("xclip", 2)):
            self.assertFalse(cb.sys_copy("x"))


class TestSysPaste(ClipboardTestCase):
    def _detect_xclip(self):
        def fake_which(name):
            return "/usr/bin/xclip" if name == "xclip" else None
        patch("stdedit.clipboard.shutil.which", side_effect=fake_which).start()
        self.addCleanup(patch.stopall)

    def test_reads_stdout(self):
        self._detect_xclip()
        with patch("stdedit.clipboard.subprocess.run",
                   return_value=MagicMock(returncode=0, stdout=b"pasted")) as run:
            self.assertEqual(cb.sys_paste(), "pasted")
            self.assertIn("-o", run.call_args[0][0])

    def test_invalid_utf8_is_replaced_not_crashing(self):
        self._detect_xclip()
        with patch("stdedit.clipboard.subprocess.run",
                   return_value=MagicMock(returncode=0, stdout=b"\xff\xfe")):
            self.assertEqual(cb.sys_paste(), "\ufffd\ufffd")

    def test_nonzero_returncode_returns_empty(self):
        self._detect_xclip()
        with patch("stdedit.clipboard.subprocess.run",
                   return_value=MagicMock(returncode=1, stdout=b"ignored")):
            self.assertEqual(cb.sys_paste(), "")

    def test_no_tool_returns_empty(self):
        with patch("stdedit.clipboard.shutil.which", return_value=None):
            self.assertEqual(cb.sys_paste(), "")

    def test_timeout_returns_empty(self):
        self._detect_xclip()
        with patch("stdedit.clipboard.subprocess.run",
                   side_effect=subprocess.TimeoutExpired("xclip", 2)):
            self.assertEqual(cb.sys_paste(), "")


if __name__ == "__main__":
    unittest.main()