import os
import shutil
import subprocess
import tempfile
import unittest

from stdedit.git_panel import GitPanel, git_panel_key


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
    path = os.path.join(d, "hello.txt")
    with open(path, "w") as f:
        f.write("hello\n")
    subprocess.run(["git", "-C", d, "add", "hello.txt"], capture_output=True, check=True)
    subprocess.run(
        ["git", "-C", d, "commit", "-m", "init"],
        capture_output=True, check=True,
    )
    return d


class TestGitPanelInit(unittest.TestCase):
    def test_not_a_repo(self):
        p = GitPanel("/tmp")
        p.refresh()
        self.assertEqual(p.items, [])
        self.assertFalse(p.visible)
        self.assertFalse(p.active)

    def test_clean_repo(self):
        d = _init_repo()
        try:
            p = GitPanel(d)
            p.refresh()
            self.assertEqual(p.items, [])
            self.assertEqual(p.selected_idx, 0)
        finally:
            shutil.rmtree(d)


class TestGitPanelRefresh(unittest.TestCase):
    def test_modified_file(self):
        d = _init_repo()
        try:
            with open(os.path.join(d, "hello.txt"), "w") as f:
                f.write("modified\n")
            p = GitPanel(d)
            p.refresh()
            self.assertEqual(len(p.items), 1)
            self.assertEqual(p.items[0].status, "M")
            self.assertFalse(p.items[0].staged)
        finally:
            shutil.rmtree(d)

    def test_staged_file(self):
        d = _init_repo()
        try:
            with open(os.path.join(d, "hello.txt"), "w") as f:
                f.write("modified\n")
            subprocess.run(["git", "-C", d, "add", "hello.txt"], capture_output=True)
            p = GitPanel(d)
            p.refresh()
            self.assertEqual(len(p.items), 1)
            self.assertEqual(p.items[0].status, "M")
            self.assertTrue(p.items[0].staged)
        finally:
            shutil.rmtree(d)

    def test_untracked_file(self):
        d = _init_repo()
        try:
            with open(os.path.join(d, "new.txt"), "w") as f:
                f.write("new\n")
            p = GitPanel(d)
            p.refresh()
            self.assertEqual(len(p.items), 1)
            self.assertEqual(p.items[0].status, "?")
            self.assertFalse(p.items[0].staged)
        finally:
            shutil.rmtree(d)

    def test_mixed_files(self):
        d = _init_repo()
        try:
            # Modified (unstaged)
            with open(os.path.join(d, "hello.txt"), "w") as f:
                f.write("modified\n")
            # Staged
            with open(os.path.join(d, "a.txt"), "w") as f:
                f.write("a\n")
            subprocess.run(["git", "-C", d, "add", "a.txt"], capture_output=True)
            # Untracked
            with open(os.path.join(d, "b.txt"), "w") as f:
                f.write("b\n")
            p = GitPanel(d)
            p.refresh()
            self.assertEqual(len(p.items), 3)
        finally:
            shutil.rmtree(d)


class TestGitPanelNavigation(unittest.TestCase):
    def test_move_selection(self):
        d = _init_repo()
        try:
            for i in range(3):
                with open(os.path.join(d, f"f{i}.txt"), "w") as f:
                    f.write(f"content{i}\n")
            p = GitPanel(d)
            p.refresh()
            self.assertEqual(p.selected_idx, 0)
            p.move_selection(1)
            self.assertEqual(p.selected_idx, 1)
            p.move_selection(1)
            self.assertEqual(p.selected_idx, 2)
            p.move_selection(1)  # clamp at end
            self.assertEqual(p.selected_idx, 2)
            p.move_selection(-10)  # clamp at start
            self.assertEqual(p.selected_idx, 0)
        finally:
            shutil.rmtree(d)

    def test_empty_list(self):
        p = GitPanel("/tmp")
        p.refresh()
        p.move_selection(1)
        self.assertEqual(p.selected_idx, 0)


class TestGitPanelStageUnstage(unittest.TestCase):
    def test_stage_selected(self):
        d = _init_repo()
        try:
            with open(os.path.join(d, "hello.txt"), "w") as f:
                f.write("modified\n")
            p = GitPanel(d)
            p.refresh()
            self.assertEqual(len(p.items), 1)
            self.assertFalse(p.items[0].staged)
            p.stage_selected()
            p.refresh()
            # After staging, the file should be staged
            staged = [f for f in p.items if f.staged]
            self.assertEqual(len(staged), 1)
        finally:
            shutil.rmtree(d)

    def test_unstage_selected(self):
        d = _init_repo()
        try:
            with open(os.path.join(d, "hello.txt"), "w") as f:
                f.write("modified\n")
            subprocess.run(["git", "-C", d, "add", "hello.txt"], capture_output=True)
            p = GitPanel(d)
            p.refresh()
            self.assertTrue(p.items[0].staged)
            p.unstage_selected()
            p.refresh()
            unstaged = [f for f in p.items if not f.staged]
            self.assertEqual(len(unstaged), 1)
        finally:
            shutil.rmtree(d)

    def test_stage_all(self):
        d = _init_repo()
        try:
            with open(os.path.join(d, "hello.txt"), "w") as f:
                f.write("modified\n")
            with open(os.path.join(d, "new.txt"), "w") as f:
                f.write("new\n")
            p = GitPanel(d)
            p.refresh()
            p.stage_all()
            p.refresh()
            # Both should be staged now
            staged = [f for f in p.items if f.staged]
            self.assertGreaterEqual(len(staged), 1)
        finally:
            shutil.rmtree(d)


class TestGitPanelCommit(unittest.TestCase):
    def test_commit_flow(self):
        d = _init_repo()
        try:
            with open(os.path.join(d, "hello.txt"), "w") as f:
                f.write("modified\n")
            subprocess.run(["git", "-C", d, "add", "hello.txt"], capture_output=True)
            p = GitPanel(d)
            p.refresh()
            self.assertFalse(p.committing)

            # Enter commit mode
            p.begin_commit()
            self.assertTrue(p.committing)
            self.assertEqual(p.commit_message, "")

            # Type message
            p.commit_char("f")
            p.commit_char("i")
            p.commit_char("x")
            self.assertEqual(p.commit_message, "fix")

            # Commit
            result = p.do_commit()
            self.assertEqual(result, "Committed")
            self.assertFalse(p.committing)
            p.refresh()
            self.assertEqual(p.items, [])
        finally:
            shutil.rmtree(d)

    def test_empty_commit_cancelled(self):
        d = _init_repo()
        try:
            with open(os.path.join(d, "hello.txt"), "w") as f:
                f.write("modified\n")
            subprocess.run(["git", "-C", d, "add", "hello.txt"], capture_output=True)
            p = GitPanel(d)
            p.refresh()
            p.begin_commit()
            result = p.do_commit()
            self.assertEqual(result, "Empty message")
            self.assertFalse(p.committing)
        finally:
            shutil.rmtree(d)

    def test_cancel_commit(self):
        p = GitPanel("/tmp")
        p.begin_commit()
        p.commit_char("x")
        p.cancel_commit()
        self.assertFalse(p.committing)
        self.assertEqual(p.commit_message, "")

    def test_ahead_behind_populated(self):
        d = _init_repo()
        try:
            p = GitPanel(d)
            p.refresh()
            self.assertEqual(p.ahead, 0)
            self.assertEqual(p.behind, 0)
        finally:
            shutil.rmtree(d)

    def test_set_root(self):
        d = _init_repo()
        try:
            p = GitPanel(d)
            p.set_root("/tmp")
            self.assertEqual(p.root_dir, "/tmp")
            self.assertFalse(p.committing)
        finally:
            shutil.rmtree(d)


class TestGitPanelBranchSelect(unittest.TestCase):
    def test_branch_select_flow(self):
        d = _init_repo()
        try:
            # Get the default branch name (main or master)
            default = subprocess.run(
                ["git", "-C", d, "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True, text=True,
            ).stdout.strip()
            subprocess.run(
                ["git", "-C", d, "checkout", "-b", "feature"],
                capture_output=True,
            )
            p = GitPanel(d)
            p.begin_branch_select()
            self.assertEqual(p.mode, "branch_select")
            self.assertIn("feature", p.branches)
            self.assertIn(default, p.branches)

            # Switch back to default branch
            p.branch_idx = p.branches.index(default)
            result = p.do_switch_branch()
            self.assertIn("Switched", result)
            self.assertEqual(p.mode, "normal")
        finally:
            shutil.rmtree(d)

    def test_cancel_branch_select(self):
        p = GitPanel("/tmp")
        p.begin_branch_select()
        p.cancel_branch_select()
        self.assertEqual(p.mode, "normal")


class TestGitPanelDiff(unittest.TestCase):
    def test_get_selected_diff(self):
        d = _init_repo()
        try:
            with open(os.path.join(d, "hello.txt"), "w") as f:
                f.write("modified\n")
            p = GitPanel(d)
            p.refresh()
            diff = p.get_selected_diff()
            self.assertIn("modified", diff)
        finally:
            shutil.rmtree(d)

    def test_diff_mode(self):
        p = GitPanel("/tmp")
        p.begin_diff()
        self.assertEqual(p.mode, "diff")
        p.end_diff()
        self.assertEqual(p.mode, "normal")


class TestGitPanelKey(unittest.TestCase):
    def test_navigation_keys(self):
        d = _init_repo()
        try:
            for i in range(3):
                with open(os.path.join(d, f"f{i}.txt"), "w") as f:
                    f.write(f"c{i}\n")
            p = GitPanel(d)
            p.visible = True
            p.active = True
            p.refresh()
            self.assertTrue(git_panel_key(p, "down"))
            self.assertEqual(p.selected_idx, 1)
            self.assertTrue(git_panel_key(p, "up"))
            self.assertEqual(p.selected_idx, 0)
        finally:
            shutil.rmtree(d)

    def test_commit_key(self):
        p = GitPanel("/tmp")
        p.active = True
        self.assertTrue(git_panel_key(p, "c"))
        self.assertTrue(p.committing)

    def test_stage_all_key(self):
        d = _init_repo()
        try:
            with open(os.path.join(d, "hello.txt"), "w") as f:
                f.write("modified\n")
            p = GitPanel(d)
            p.visible = True
            p.active = True
            p.refresh()
            self.assertTrue(git_panel_key(p, "S"))
        finally:
            shutil.rmtree(d)

    def test_unstage_all_key(self):
        d = _init_repo()
        try:
            with open(os.path.join(d, "hello.txt"), "w") as f:
                f.write("modified\n")
            subprocess.run(["git", "-C", d, "add", "hello.txt"], capture_output=True)
            p = GitPanel(d)
            p.visible = True
            p.active = True
            p.refresh()
            self.assertTrue(git_panel_key(p, "U"))
        finally:
            shutil.rmtree(d)

    def test_refresh_key(self):
        p = GitPanel("/tmp")
        p.active = True
        self.assertTrue(git_panel_key(p, "R"))
        self.assertEqual(p.last_result, "Refreshed")

    def test_unknown_key_not_consumed(self):
        p = GitPanel("/tmp")
        self.assertFalse(git_panel_key(p, "x"))

    def test_commit_mode_keys(self):
        p = GitPanel("/tmp")
        p.begin_commit()
        self.assertTrue(git_panel_key(p, "h"))
        self.assertTrue(git_panel_key(p, "i"))
        self.assertEqual(p.commit_message, "hi")
        self.assertTrue(git_panel_key(p, "\x7f"))  # backspace
        self.assertEqual(p.commit_message, "h")
        self.assertTrue(git_panel_key(p, "\x1b"))  # escape
        self.assertFalse(p.committing)

    def test_branch_select_mode_keys(self):
        d = _init_repo()
        try:
            p = GitPanel(d)
            p.begin_branch_select()
            self.assertTrue(git_panel_key(p, "down"))
            self.assertTrue(git_panel_key(p, "up"))
            self.assertTrue(git_panel_key(p, "\x1b"))
            self.assertEqual(p.mode, "normal")
        finally:
            shutil.rmtree(d)


if __name__ == "__main__":
    unittest.main()
