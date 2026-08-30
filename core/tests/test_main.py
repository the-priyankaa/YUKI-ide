import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest import mock

import stdedit.main as app
from stdedit.main import build_parser, resolve_open_targets


class TestProjectFlag(unittest.TestCase):
    def test_project_defaults_to_none(self):
        args = build_parser().parse_args(["a.py"])
        self.assertIsNone(args.project)

    def test_project_is_parsed_with_optional_file(self):
        args = build_parser().parse_args(["--project", "/tmp", "a.py"])
        self.assertEqual(args.project, "/tmp")

    def test_project_works_without_file(self):
        args = build_parser().parse_args(["--project", "~/myapp"])
        self.assertEqual(args.project, "~/myapp")


class TestTreeFlag(unittest.TestCase):
    def test_tree_defaults_to_false(self):
        args = build_parser().parse_args(["a.py"])
        self.assertFalse(args.tree)

    def test_tree_flag_parsed(self):
        args = build_parser().parse_args(["--tree", "a.py"])
        self.assertTrue(args.tree)

    def test_tree_flag_without_file(self):
        args = build_parser().parse_args(["--tree"])
        self.assertTrue(args.tree)
        self.assertIsNone(args.file)


class TestResolveOpenTargets(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def test_no_arguments(self):
        self.assertEqual(resolve_open_targets(None, None), (None, None, None))

    def test_plain_file_opens_in_buffer(self):
        target = os.path.join(self.tmp, "x.py")
        with open(target, "w") as f:
            f.write("1\n")
        buf_file, project_dir, error = resolve_open_targets(target, None)
        self.assertIsNone(error)
        self.assertEqual(buf_file, target)
        # No explicit project: tui.resolve_tree_root() later falls back to
        # the opened file's parent folder.
        self.assertIsNone(project_dir)

    def test_directory_positional_means_project(self):
        buf_file, project_dir, error = resolve_open_targets(self.tmp, None)
        self.assertIsNone(error)
        self.assertIsNone(buf_file)
        self.assertEqual(project_dir, os.path.abspath(self.tmp))

    def test_tilde_expands_for_both_arguments(self):
        home = os.path.expanduser("~")
        _, project_dir, _ = resolve_open_targets(None, "~")
        self.assertEqual(project_dir, home)
        # A path under ~ that does not exist is treated as a new file.
        buf_file, _, error = resolve_open_targets("~/no_such_file_xyz.py", None)
        self.assertIsNone(error)
        self.assertEqual(buf_file, "~/no_such_file_xyz.py")

    def test_project_flag_validated(self):
        buf_file, project_dir, error = resolve_open_targets(None, "/no/such/dir")
        self.assertIsNotNone(error)
        self.assertIn("not a directory", error)
        self.assertIsNone(buf_file)

    def test_positional_dir_and_project_conflict(self):
        buf_file, project_dir, error = resolve_open_targets(self.tmp, self.tmp)
        self.assertIsNotNone(error)
        self.assertIn("once", error)
        self.assertIsNone(buf_file)
        self.assertIsNone(project_dir)

    def test_nonexistent_path_stays_a_new_file(self):
        missing = "/definitely/not/here.py"
        buf_file, project_dir, error = resolve_open_targets(missing, None)
        self.assertIsNone(error)
        self.assertEqual(buf_file, missing)


def _fake_tty():
    """Replace sys.stdin with an object that reports being a terminal."""
    return mock.patch.object(
        sys, "stdin", SimpleNamespace(isatty=lambda: True))


def _fake_pipe():
    """Replace sys.stdin with an object that is explicitly not a terminal."""
    return mock.patch.object(
        sys, "stdin", SimpleNamespace(isatty=lambda: False))


class TestMainExitCodes(unittest.TestCase):
    """main() must give friendly exits instead of raw curses tracebacks."""

    def _env(self, term):
        return mock.patch.dict(os.environ, {"TERM": term})

    def test_piped_stdin_exits_1_without_launching_tui(self):
        with _fake_pipe(), \
             self._env("xterm-256color"), \
             mock.patch.object(app.tui, "run") as run, \
             redirect_stderr(io.StringIO()) as err:
            rc = app.main(["a.py"])
        self.assertEqual(rc, 1)
        self.assertIn("interactive terminal", err.getvalue())
        run.assert_not_called()

    def test_missing_term_exits_1_without_launching_tui(self):
        with _fake_tty(), \
             mock.patch.dict(os.environ, {}), \
             mock.patch.object(app.tui, "run") as run, \
             redirect_stderr(io.StringIO()) as err:
            os.environ.pop("TERM", None)
            rc = app.main(["a.py"])
        self.assertEqual(rc, 1)
        self.assertIn("TERM", err.getvalue())
        run.assert_not_called()

    def test_unreadable_file_exits_1_with_friendly_message(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "locked.txt")
            with open(path, "w") as f:
                f.write("data")
            os.chmod(path, 0o000)
            try:
                with _fake_tty(), self._env("xterm-256color"), \
                     mock.patch.object(app.tui, "run") as run, \
                     redirect_stderr(io.StringIO()) as err:
                    rc = app.main([path])
                self.assertEqual(rc, 1)
                self.assertIn("cannot open", err.getvalue())
                run.assert_not_called()
            finally:
                os.chmod(path, 0o644)

    def test_opens_file_and_launches_tui(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "doc.txt")
            with open(path, "w") as f:
                f.write("hello world\n")
            with _fake_tty(), self._env("xterm-256color"), \
                 mock.patch.object(app.tui, "run") as run:
                rc = app.main([path])
            self.assertEqual(rc, 0)
            run.assert_called_once()
            buf = run.call_args.args[0]
            self.assertEqual(buf.filename, path)
            self.assertEqual(buf.lines[0], "hello world")

    def test_launch_prints_yuki_banner(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "doc.txt")
            with open(path, "w") as f:
                f.write("hello\n")
            with _fake_tty(), self._env("xterm-256color"), \
                 mock.patch.object(app.tui, "run") as run, \
                 redirect_stdout(io.StringIO()) as out:
                rc = app.main([path])
            self.assertEqual(rc, 0)
            run.assert_called_once()
            self.assertIn("YUKI", out.getvalue())

    def test_directory_positional_becomes_project(self):
        with tempfile.TemporaryDirectory() as d:
            with _fake_tty(), self._env("xterm-256color"), \
                 mock.patch.object(app.tui, "run") as run:
                rc = app.main([d])
            self.assertEqual(rc, 0)
            run.assert_called_once()
            self.assertEqual(run.call_args.kwargs["project_dir"],
                             os.path.abspath(d))

    def test_list_extensions_needs_no_tty(self):
        with _fake_pipe():
            rc = app.main(["--list-extensions"])
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
