import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from stdedit.git import (
    is_git_repo,
    get_branch,
    get_ahead_behind,
    get_status_counts,
    format_status_counts,
    get_status_files,
    get_diff,
    get_staged_diff,
    stage_file,
    unstage_file,
    stage_all,
    commit,
    push,
    pull,
    stash,
    stash_pop,
    _run,
)


def _init_repo() -> str:
    """Create a temporary git repo with one initial commit."""
    d = tempfile.mkdtemp()
    subprocess.run(["git", "init", d], capture_output=True, check=True)
    subprocess.run(
        ["git", "-C", d, "config", "user.email", "test@test.com"],
        capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "-C", d, "config", "user.name", "Test"],
        capture_output=True, check=True,
    )
    # Write and commit an initial file so the repo is non-empty.
    path = os.path.join(d, "hello.txt")
    with open(path, "w") as f:
        f.write("hello\n")
    subprocess.run(["git", "-C", d, "add", "hello.txt"], capture_output=True, check=True)
    subprocess.run(
        ["git", "-C", d, "commit", "-m", "init"],
        capture_output=True, check=True,
    )
    return d


class TestIsGitRepo(unittest.TestCase):
    def test_inside_repo(self):
        d = _init_repo()
        try:
            self.assertTrue(is_git_repo(d))
        finally:
            shutil.rmtree(d)

    def test_not_a_repo(self):
        d = tempfile.mkdtemp()
        try:
            self.assertFalse(is_git_repo(d))
        finally:
            shutil.rmtree(d)

    def test_nonexistent_path(self):
        self.assertFalse(is_git_repo("/no/such/path"))


class TestGetBranch(unittest.TestCase):
    def test_main_branch(self):
        d = _init_repo()
        try:
            branch = get_branch(d)
            self.assertIn(branch, ("main", "master"))
        finally:
            shutil.rmtree(d)

    def test_not_a_repo(self):
        self.assertIsNone(get_branch("/tmp"))

    def test_detached_head(self):
        d = _init_repo()
        try:
            # Detach HEAD by checking out a commit hash.
            r = subprocess.run(
                ["git", "-C", d, "rev-parse", "HEAD"],
                capture_output=True, text=True,
            )
            commit = r.stdout.strip()
            subprocess.run(["git", "-C", d, "checkout", commit], capture_output=True)
            # After detach, rev-parse --abbrev-ref HEAD prints "HEAD"
            self.assertIsNone(get_branch(d))
        finally:
            shutil.rmtree(d)

    def test_new_branch(self):
        d = _init_repo()
        try:
            subprocess.run(
                ["git", "-C", d, "checkout", "-b", "feature-x"],
                capture_output=True,
            )
            self.assertEqual(get_branch(d), "feature-x")
        finally:
            shutil.rmtree(d)


class TestGetStatusCounts(unittest.TestCase):
    def test_clean_repo(self):
        d = _init_repo()
        try:
            counts = get_status_counts(d)
            self.assertEqual(counts, {"modified": 0, "added": 0, "deleted": 0, "untracked": 0})
        finally:
            shutil.rmtree(d)

    def test_modified_file(self):
        d = _init_repo()
        try:
            path = os.path.join(d, "hello.txt")
            with open(path, "w") as f:
                f.write("modified\n")
            counts = get_status_counts(d)
            self.assertEqual(counts["modified"], 1)
            self.assertEqual(counts["added"], 0)
            self.assertEqual(counts["deleted"], 0)
            self.assertEqual(counts["untracked"], 0)
        finally:
            shutil.rmtree(d)

    def test_untracked_file(self):
        d = _init_repo()
        try:
            path = os.path.join(d, "new.txt")
            with open(path, "w") as f:
                f.write("new\n")
            counts = get_status_counts(d)
            self.assertEqual(counts["untracked"], 1)
            self.assertEqual(counts["modified"], 0)
        finally:
            shutil.rmtree(d)

    def test_deleted_file(self):
        d = _init_repo()
        try:
            path = os.path.join(d, "hello.txt")
            os.unlink(path)
            # Need to stage the deletion for git status to see it.
            subprocess.run(["git", "-C", d, "add", "hello.txt"], capture_output=True)
            counts = get_status_counts(d)
            self.assertEqual(counts["deleted"], 1)
        finally:
            shutil.rmtree(d)

    def test_added_file(self):
        d = _init_repo()
        try:
            path = os.path.join(d, "added.txt")
            with open(path, "w") as f:
                f.write("added\n")
            subprocess.run(["git", "-C", d, "add", "added.txt"], capture_output=True)
            counts = get_status_counts(d)
            self.assertEqual(counts["added"], 1)
        finally:
            shutil.rmtree(d)

    def test_mixed_changes(self):
        d = _init_repo()
        try:
            # Modify existing file
            with open(os.path.join(d, "hello.txt"), "w") as f:
                f.write("changed\n")
            # Add new file
            with open(os.path.join(d, "new.txt"), "w") as f:
                f.write("new\n")
            # Delete existing file
            os.unlink(os.path.join(d, "hello.txt"))
            subprocess.run(["git", "-C", d, "add", "hello.txt"], capture_output=True)
            counts = get_status_counts(d)
            # hello.txt is deleted (deleted=1), new.txt is untracked (untracked=1)
            self.assertEqual(counts["deleted"], 1)
            self.assertEqual(counts["untracked"], 1)
        finally:
            shutil.rmtree(d)

    def test_not_a_repo(self):
        counts = get_status_counts("/tmp")
        self.assertEqual(counts, {"modified": 0, "added": 0, "deleted": 0, "untracked": 0})


class TestFormatStatusCounts(unittest.TestCase):
    def test_clean(self):
        self.assertEqual(
            format_status_counts({"modified": 0, "added": 0, "deleted": 0, "untracked": 0}),
            "",
        )

    def test_modified_only(self):
        self.assertEqual(
            format_status_counts({"modified": 3, "added": 0, "deleted": 0, "untracked": 0}),
            "~3",
        )

    def test_all_present(self):
        result = format_status_counts({"modified": 1, "added": 2, "deleted": 3, "untracked": 4})
        self.assertEqual(result, "+2 ~1 -3 !4")

    def test_partial(self):
        result = format_status_counts({"modified": 0, "added": 5, "deleted": 0, "untracked": 1})
        self.assertEqual(result, "+5 !1")

    def test_empty_string_for_clean(self):
        result = format_status_counts({"modified": 0, "added": 0, "deleted": 0, "untracked": 0})
        self.assertEqual(result, "")


class TestGetAheadBehind(unittest.TestCase):
    def test_no_upstream(self):
        d = _init_repo()
        try:
            result = get_ahead_behind(d)
            self.assertEqual(result, (0, 0))
        finally:
            shutil.rmtree(d)

    def test_not_a_repo(self):
        result = get_ahead_behind("/tmp")
        self.assertEqual(result, (0, 0))

    def test_with_upstream(self):
        d = _init_repo()
        try:
            # Create a bare remote and push
            bare = tempfile.mkdtemp()
            subprocess.run(["git", "init", "--bare", bare], capture_output=True, check=True)
            subprocess.run(["git", "-C", d, "remote", "add", "origin", bare],
                           capture_output=True, check=True)
            subprocess.run(["git", "-C", d, "push", "-u", "origin", "master"],
                           capture_output=True, check=True)
            # Make a new commit locally
            path = os.path.join(d, "new.txt")
            with open(path, "w") as f:
                f.write("new\n")
            subprocess.run(["git", "-C", d, "add", "new.txt"], capture_output=True, check=True)
            subprocess.run(["git", "-C", d, "commit", "-m", "second"],
                           capture_output=True, check=True)
            ahead, behind = get_ahead_behind(d)
            self.assertEqual(ahead, 1)
            self.assertEqual(behind, 0)
            shutil.rmtree(bare)
        finally:
            shutil.rmtree(d)


class TestStageAndCommit(unittest.TestCase):
    def test_stage_file_marks_modified(self):
        d = _init_repo()
        try:
            with open(os.path.join(d, "hello.txt"), "w") as f:
                f.write("changed\n")
            self.assertTrue(stage_file(d, "hello.txt"))
            self.assertEqual(get_status_counts(d)["modified"], 1)
        finally:
            shutil.rmtree(d)

    def test_unstage_file(self):
        d = _init_repo()
        try:
            with open(os.path.join(d, "hello.txt"), "w") as f:
                f.write("changed\n")
            self.assertTrue(stage_file(d, "hello.txt"))
            self.assertTrue(unstage_file(d, "hello.txt"))
            self.assertEqual(get_status_counts(d)["modified"], 1)
        finally:
            shutil.rmtree(d)

    def test_stage_all_then_commit_cleans_repo(self):
        d = _init_repo()
        try:
            for name in ("one.txt", "two.txt"):
                with open(os.path.join(d, name), "w") as f:
                    f.write(name)
            self.assertTrue(stage_all(d))
            self.assertTrue(commit(d, "add two files"))
            counts = get_status_counts(d)
            self.assertEqual(counts["modified"], 0)
            self.assertEqual(counts["untracked"], 0)
            self.assertEqual(counts["added"], 0)
        finally:
            shutil.rmtree(d)


class TestDiffs(unittest.TestCase):
    def test_clean_repo_has_empty_diffs(self):
        d = _init_repo()
        try:
            self.assertEqual(get_diff(d), "")
            self.assertEqual(get_staged_diff(d), "")
        finally:
            shutil.rmtree(d)

    def test_unstaged_change_shows_in_get_diff_only(self):
        d = _init_repo()
        try:
            with open(os.path.join(d, "hello.txt"), "w") as f:
                f.write("modified hello\n")
            self.assertIn("-hello", get_diff(d))
            self.assertIn("+modified hello", get_diff(d))
            self.assertEqual(get_staged_diff(d), "")
        finally:
            shutil.rmtree(d)

    def test_staged_change_shows_in_get_staged_diff_only(self):
        d = _init_repo()
        try:
            path = os.path.join(d, "added.txt")
            with open(path, "w") as f:
                f.write("staged content\n")
            self.assertTrue(stage_file(d, "added.txt"))
            self.assertEqual(get_diff(d), "")
            self.assertIn("added.txt", get_staged_diff(d))
            self.assertIn("+staged content", get_staged_diff(d))
        finally:
            shutil.rmtree(d)


class TestPushPull(unittest.TestCase):
    def test_push_without_remote_reports_failure(self):
        d = _init_repo()
        try:
            ok, output = push(d)
            self.assertFalse(ok)
            self.assertTrue(output.strip())
        finally:
            shutil.rmtree(d)

    def test_pull_without_remote_reports_failure(self):
        d = _init_repo()
        try:
            ok, output = pull(d)
            self.assertFalse(ok)
            self.assertTrue(output.strip())
        finally:
            shutil.rmtree(d)

    def test_push_pull_against_bare_remote(self):
        d = _init_repo()
        bare = tempfile.mkdtemp()
        try:
            subprocess.run(["git", "init", "--bare", bare], capture_output=True, check=True)
            branch = get_branch(d)
            subprocess.run(["git", "-C", d, "remote", "add", "origin", bare],
                           capture_output=True, check=True)
            ok, _ = push(d)
            self.assertFalse(ok, "no upstream yet; still must not raise")
            # Set upstream so an actual round-trip works.
            subprocess.run(["git", "-C", d, "push", "-u", "origin", "HEAD"],
                           capture_output=True)
            ok, output = push(d)
            self.assertTrue(ok, output)
            ok_pull, _ = pull(d)
            self.assertTrue(ok_pull)
        finally:
            shutil.rmtree(bare)
            shutil.rmtree(d)


class TestStash(unittest.TestCase):
    def test_stash_and_pop_roundtrip(self):
        d = _init_repo()
        try:
            with open(os.path.join(d, "hello.txt"), "w") as f:
                f.write("wip\n")
            self.assertEqual(get_status_counts(d)["modified"], 1)
            self.assertTrue(stash(d))
            self.assertEqual(get_status_counts(d)["modified"], 0)
            self.assertTrue(stash_pop(d))
            self.assertEqual(get_status_counts(d)["modified"], 1)
        finally:
            shutil.rmtree(d)


class TestGitUnavailable(unittest.TestCase):
    """When the git binary is missing every call fails gracefully (None/False)."""

    def setUp(self):
        self._d = tempfile.mkdtemp()
        patch = mock.patch("stdedit.git.subprocess.run",
                           side_effect=FileNotFoundError("git"))
        patch.start()
        self.addCleanup(patch.stop)

    def tearDown(self):
        shutil.rmtree(self._d, ignore_errors=True)

    def test_run_returns_none(self):
        self.assertIsNone(_run(["rev-parse", "--is-inside-work-tree"], cwd=self._d))

    def test_is_git_repo_false(self):
        self.assertFalse(is_git_repo(self._d))

    def test_get_branch_none(self):
        self.assertIsNone(get_branch(self._d))

    def test_get_status_counts_defaults(self):
        self.assertEqual(
            get_status_counts(self._d),
            {"modified": 0, "added": 0, "deleted": 0, "untracked": 0},
        )

    def test_get_status_files_empty(self):
        self.assertEqual(get_status_files(self._d), [])

    def test_diffs_empty(self):
        self.assertEqual(get_diff(self._d), "")
        self.assertEqual(get_staged_diff(self._d), "")

    def test_push_pull_report_git_unavailable(self):
        self.assertEqual(push(self._d), (False, "git not available"))
        self.assertEqual(pull(self._d), (False, "git not available"))

    def test_mutating_calls_return_false(self):
        self.assertFalse(stage_file(self._d, "a"))
        self.assertFalse(unstage_file(self._d, "a"))
        self.assertFalse(stage_all(self._d))
        self.assertFalse(commit(self._d, "msg"))
        self.assertFalse(stash(self._d))
        self.assertFalse(stash_pop(self._d))


if __name__ == "__main__":
    unittest.main()
