"""Tests for the native folder-picker helper (pickdir)."""

import os
import subprocess
import unittest
from unittest import mock

from stdedit import pickdir


class PickDirTest(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("STDEDIT_PICK_FOLDER", None)

    def test_env_pick_returns_ok(self):
        d = os.path.dirname(os.path.abspath(__file__))
        os.environ["STDEDIT_PICK_FOLDER"] = d
        self.assertEqual(pickdir.choose_directory(), ("ok", d))

    def test_env_cancel(self):
        os.environ["STDEDIT_PICK_FOLDER"] = "cancel"
        self.assertEqual(pickdir.choose_directory(), ("cancelled",))

    def test_env_bad_path_is_unavailable(self):
        os.environ["STDEDIT_PICK_FOLDER"] = "/no/such/dir-xyz"
        self.assertEqual(pickdir.choose_directory(), ("unavailable",))

    @mock.patch.object(pickdir, "_find_tool", return_value=(None, []))
    def test_env_missing_is_unavailable(self, _):
        self.assertEqual(pickdir.choose_directory(), ("unavailable",))

    @mock.patch.object(pickdir.shutil, "which", side_effect=lambda _: None)
    def test_no_tool_is_unavailable(self, _):
        self.assertEqual(pickdir.choose_directory(), ("unavailable",))

    @mock.patch.object(pickdir.shutil, "which")
    def test_zenity_priority_over_kdialog(self, which):
        which.side_effect = lambda name: "/usr/bin/zenity" if name == "zenity" else "/usr/bin/kdialog"
        d = os.path.dirname(os.path.abspath(__file__))
        with mock.patch.object(
            pickdir.subprocess, "run",
            return_value=mock.Mock(
                returncode=0, stdout=d + "\n", stderr="")):
            self.assertEqual(
                pickdir.choose_directory(),
                ("ok", d))
        which.assert_any_call("zenity")

    @mock.patch.object(pickdir.shutil, "which")
    def test_zenity_cancel_rc1(self, which):
        which.side_effect = lambda name: "/usr/bin/zenity" if name == "zenity" else None
        with mock.patch.object(
            pickdir.subprocess, "run",
            return_value=mock.Mock(returncode=1, stdout="", stderr="")):
            self.assertEqual(pickdir.choose_directory(), ("cancelled",))

    @mock.patch.object(pickdir.shutil, "which")
    def test_zenity_error_stderr_is_unavailable(self, which):
        which.side_effect = lambda name: "/usr/bin/zenity" if name == "zenity" else None
        with mock.patch.object(
            pickdir.subprocess, "run",
            return_value=mock.Mock(
                returncode=1, stdout="", stderr="Cannot open display")):
            self.assertEqual(pickdir.choose_directory(), ("unavailable",))

    @mock.patch.object(pickdir.shutil, "which")
    def test_zenity_timeout(self, which):
        which.side_effect = lambda name: "/usr/bin/zenity" if name == "zenity" else None
        with mock.patch.object(
            pickdir.subprocess, "run",
            side_effect=subprocess.TimeoutExpired("zenity", 60)):
            self.assertEqual(pickdir.choose_directory(), ("unavailable",))

    @mock.patch.object(pickdir.shutil, "which")
    def test_zenity_output_not_a_dir(self, which):
        which.side_effect = lambda name: "/usr/bin/zenity" if name == "zenity" else None
        with mock.patch.object(
            pickdir.subprocess, "run",
            return_value=mock.Mock(returncode=0, stdout="/no/such/dir-xyz\n", stderr="")):
            self.assertEqual(pickdir.choose_directory(), ("unavailable",))


if __name__ == "__main__":
    unittest.main()