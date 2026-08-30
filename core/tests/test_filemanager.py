import os
import tempfile
import unittest
from types import SimpleNamespace

from stdedit.filemanager import pick_folder, reveal_in_file_manager


def fake_which(found):
    """Build a shutil.which replacement for the given set of binaries."""
    return lambda name: name if name in found else None


class FakeRun:
    def __init__(self, stdout="", error=None):
        self.calls = []
        self.stdout = stdout
        self.error = error

    def __call__(self, cmd, **kwargs):
        self.calls.append((cmd, kwargs))
        if self.error:
            raise self.error
        return SimpleNamespace(stdout=self.stdout)

    @property
    def last_cmd(self):
        return self.calls[-1][0]


class TestPickFolder(unittest.TestCase):
    def test_uses_first_installed_helper(self):
        run = FakeRun(stdout="/home/cat/projects\n")
        path, info = pick_folder("/start", _which=fake_which({"zenity", "kdialog"}), _run=run)
        self.assertEqual(path, "/home/cat/projects")
        self.assertEqual(info, "zenity")
        self.assertEqual(run.last_cmd[0], "zenity")

    def test_falls_through_to_second_helper_when_first_missing(self):
        run = FakeRun(stdout="/picked/dir")
        path, info = pick_folder("/start", _which=fake_which({"kdialog"}), _run=run)
        self.assertEqual(path, "/picked/dir")
        self.assertEqual(info, "kdialog")
        # The {start} placeholder is substituted for kdialog.
        self.assertIn("/start", run.last_cmd)

    def test_cancel_returns_none_with_reason(self):
        run = FakeRun(stdout="")  # dialog dismissed
        path, info = pick_folder("/start", _which=fake_which({"zenity"}), _run=run)
        self.assertIsNone(path)
        self.assertEqual(info, "cancelled")

    def test_no_helpers_installed(self):
        run = FakeRun()
        path, info = pick_folder("/start", _which=fake_which(set()), _run=run)
        self.assertIsNone(path)
        self.assertEqual(info, "no system picker available")
        self.assertEqual(run.calls, [])

    def test_timeout_reported_not_raised(self):
        import subprocess

        run = FakeRun(error=subprocess.TimeoutExpired(cmd="zenity", timeout=30))
        path, info = pick_folder("/start", _which=fake_which({"zenity"}), _run=run)
        self.assertIsNone(path)
        self.assertIn("timed out", info)

    def test_os_error_reported_not_raised(self):
        run = FakeRun(error=OSError("no display"))
        path, info = pick_folder("/start", _which=fake_which({"zenity"}), _run=run)
        self.assertIsNone(path)
        self.assertIn("failed", info)


class FakePopen:
    def __init__(self, error=None):
        self.calls = []
        self.error = error

    def __call__(self, cmd, **kwargs):
        self.calls.append((cmd, kwargs))
        if self.error:
            raise self.error
        return SimpleNamespace(pid=1)


class TestReveal(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def test_prefers_xdg_open(self):
        popen = FakePopen()
        ok, info = reveal_in_file_manager(self.dir, _which=fake_which({"xdg-open", "open"}), _popen=popen)
        self.assertTrue(ok)
        self.assertEqual(info, "xdg-open")
        self.assertEqual(popen.calls[0][0], ["xdg-open", self.dir])

    def test_falls_back_to_open(self):
        popen = FakePopen()
        ok, info = reveal_in_file_manager(self.dir, _which=fake_which({"open"}), _popen=popen)
        self.assertTrue(ok)
        self.assertEqual(info, "open")

    def test_no_launcher_found(self):
        ok, info = reveal_in_file_manager(self.dir, _which=fake_which(set()), _popen=FakePopen())
        self.assertFalse(ok)
        self.assertEqual(info, "no file manager launcher found")

    def test_launch_failure_reported(self):
        popen = FakePopen(error=OSError("display problem"))
        ok, info = reveal_in_file_manager(self.dir, _which=fake_which({"xdg-open"}), _popen=popen)
        self.assertFalse(ok)
        self.assertIn("could not launch xdg-open", info)

    def test_popen_is_non_blocking_kwargs(self):
        popen = FakePopen()
        reveal_in_file_manager(self.dir, _which=fake_which({"xdg-open"}), _popen=popen)
        _, kwargs = popen.calls[0]
        self.assertIn("stdout", kwargs)  # output redirected, never piped back


if __name__ == "__main__":
    unittest.main()
