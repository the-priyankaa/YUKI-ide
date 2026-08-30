"""Source control panel for the git integration.

UI-agnostic panel state.  The curses drawing helper ``draw_git_panel``
lives here too since it only depends on curses (stdlib).
"""
from __future__ import annotations

import curses
import os
from typing import Optional

from . import git
from . import github_api


# ------------------------------------------------------------------ #
# Panel state (no curses dependency)
# ------------------------------------------------------------------ #

class GitPanel:
    """Source control panel — shows modified/staged/untracked files.

    Follows the same pattern as ``FileExplorer``: a flat list of items,
    a selection index, and visibility/focus flags.
    """
    # Git status letters mapped to short labels
    STATUS_LABELS = {
        "M": "M", "m": "M", "A": "A", "D": "D",
        "?": "?", "R": "R", "C": "C", "U": "!",
    }

    def __init__(self, root_dir: str) -> None:
        self.root_dir: str = os.path.abspath(root_dir)
        self.visible: bool = False
        self.active: bool = False
        self.items: list[git.GitFile] = []
        self.selected_idx: int = 0
        self.scroll_offset: int = 0
        # Mode: "normal" | "branch_select" | "diff" | "issues" | "prs"
        self.mode: str = "normal"
        # Commit message (always available — VS Code style)
        self.commit_message: str = ""
        self.committing: bool = False
        # Ahead / behind upstream
        self.ahead: int = 0
        self.behind: int = 0
        self.branches: list[str] = []
        self.branch_idx: int = 0
        self.last_result: str = ""
        # Issues / PRs
        self.issues: list[github_api.GitHubIssue] = []
        self.prs: list[github_api.GitHubPR] = []
        self.issue_idx: int = 0
        self.pr_idx: int = 0

    # -- refresh ---------------------------------------------------- #

    def refresh(self) -> None:
        """Re-read ``git status`` and rebuild the file list."""
        if not git.is_git_repo(self.root_dir):
            self.items = []
            self.ahead = 0
            self.behind = 0
            return
        self.items = git.get_status_files(self.root_dir)
        self.ahead, self.behind = git.get_ahead_behind(self.root_dir)
        # Clamp selection
        if self.items and self.selected_idx >= len(self.items):
            self.selected_idx = len(self.items) - 1
        elif not self.items:
            self.selected_idx = 0

    def set_root(self, root_dir: str) -> None:
        """Change the project root at runtime."""
        self.root_dir = os.path.abspath(root_dir)
        self.mode = "normal"
        self.committing = False
        self.commit_message = ""
        self.refresh()

    # -- navigation ------------------------------------------------- #

    def move_selection(self, dy: int) -> None:
        if not self.items:
            self.selected_idx = 0
            return
        self.selected_idx = max(0, min(self.selected_idx + dy, len(self.items) - 1))

    def selected_file(self) -> Optional[git.GitFile]:
        if 0 <= self.selected_idx < len(self.items):
            return self.items[self.selected_idx]
        return None

    # -- stage / unstage -------------------------------------------- #

    def stage_selected(self) -> None:
        f = self.selected_file()
        if f and not f.staged:
            git.stage_file(self.root_dir, f.path)
            self.refresh()

    def unstage_selected(self) -> None:
        f = self.selected_file()
        if f and f.staged:
            git.unstage_file(self.root_dir, f.path)
            self.refresh()

    def stage_all(self) -> None:
        git.stage_all(self.root_dir)
        self.refresh()

    def unstage_all(self) -> None:
        git.unstage_all(self.root_dir)
        self.refresh()

    # -- commit ----------------------------------------------------- #

    # Conventional commit templates
    COMMIT_TEMPLATES = [
        ("feat", "feat: ", "A new feature"),
        ("fix", "fix: ", "A bug fix"),
        ("docs", "docs: ", "Documentation only changes"),
        ("style", "style: ", "Changes that do not affect the meaning of the code"),
        ("refactor", "refactor: ", "A code change that neither fixes a bug nor adds a feature"),
        ("perf", "perf: ", "A code change that improves performance"),
        ("test", "test: ", "Adding missing tests or correcting existing tests"),
        ("chore", "chore: ", "Changes to the build process or auxiliary tools"),
        ("build", "build: ", "Changes that affect the build system or external dependencies"),
        ("ci", "ci: ", "Changes to CI configuration files and scripts"),
        ("revert", "revert: ", "Reverts a previous commit"),
        ("custom", "", "Custom message (no prefix)"),
    ]

    def begin_commit(self) -> None:
        """Enter commit mode (type message, Enter to commit)."""
        self.committing = True
        self.commit_message = ""
        self.commit_mode = "message"  # "message" | "template_select"
        self.template_idx = 0

    def cancel_commit(self) -> None:
        self.committing = False
        self.commit_message = ""
        self.commit_mode = "message"

    def commit_char(self, ch: str) -> None:
        if self.commit_mode == "message":
            self.commit_message += ch

    def commit_backspace(self) -> None:
        if self.commit_mode == "message":
            self.commit_message = self.commit_message[:-1]

    def commit_newline(self) -> None:
        """Add a newline to the commit message (for multi-line messages)."""
        if self.commit_mode == "message":
            self.commit_message += "\n"

    def begin_commit_template_select(self) -> None:
        """Show template selector for commit message."""
        self.commit_mode = "template_select"
        self.template_idx = 0

    def cancel_commit_template_select(self) -> None:
        self.commit_mode = "message"

    def move_template(self, dy: int) -> None:
        self.template_idx = max(0, min(self.template_idx + dy, len(self.COMMIT_TEMPLATES) - 1))

    def apply_template(self) -> None:
        """Apply the selected template to the commit message."""
        if self.commit_mode == "template_select":
            _, prefix, _ = self.COMMIT_TEMPLATES[self.template_idx]
            self.commit_message = prefix
            self.commit_mode = "message"

    def do_commit(self) -> str:
        """Commit with the current message.  Returns status text."""
        msg = self.commit_message.strip()
        if not msg:
            self.last_result = "Empty message"
            self.committing = False
            return self.last_result
        ok = git.commit(self.root_dir, msg)
        self.committing = False
        self.commit_message = ""
        self.commit_mode = "message"
        self.refresh()
        self.last_result = "Committed" if ok else "Commit failed"
        return self.last_result

    # -- push / pull ------------------------------------------------ #

    def do_push(self) -> str:
        ok, out = git.push(self.root_dir)
        self.last_result = "Pushed" if ok else f"Push: {out}"
        return self.last_result

    def do_pull(self) -> str:
        ok, out = git.pull(self.root_dir)
        self.last_result = "Pulled" if ok else f"Pull: {out}"
        self.refresh()
        return self.last_result

    # -- branches --------------------------------------------------- #

    def begin_branch_select(self) -> None:
        self.branches = git.get_branches(self.root_dir)
        current = git.get_branch(self.root_dir)
        self.branch_idx = self.branches.index(current) if current in self.branches else 0
        self.mode = "branch_select"

    def cancel_branch_select(self) -> None:
        self.mode = "normal"

    def move_branch(self, dy: int) -> None:
        if self.branches:
            self.branch_idx = max(0, min(self.branch_idx + dy, len(self.branches) - 1))

    def do_switch_branch(self) -> str:
        if not self.branches:
            self.mode = "normal"
            return "No branches"
        branch = self.branches[self.branch_idx]
        ok, out = git.switch_branch(self.root_dir, branch)
        self.mode = "normal"
        self.refresh()
        self.last_result = f"Switched to {branch}" if ok else f"Switch: {out}"
        return self.last_result

    # -- diff ------------------------------------------------------- #

    def begin_diff(self) -> None:
        self.mode = "diff"

    def end_diff(self) -> None:
        self.mode = "normal"

    def get_selected_diff(self) -> str:
        f = self.selected_file()
        if not f:
            return ""
        if f.staged:
            return git.get_staged_diff(self.root_dir, f.path)
        return git.get_diff(self.root_dir, f.path)

    # -- hunks (inline diff actions) -------------------------------- #

    def begin_hunk_mode(self) -> None:
        """Enter hunk selection mode for the selected file."""
        f = self.selected_file()
        if not f:
            return
        self.mode = "hunk_select"
        self.hunk_file = f
        self.hunks = git.get_diff_hunks(self.root_dir, f.path, staged=f.staged)
        self.hunk_idx = 0
        if self.hunks:
            self.hunk_idx = 0

    def cancel_hunk_mode(self) -> None:
        self.mode = "normal"
        self.hunks = []
        self.hunk_idx = 0
        self.hunk_file = None

    def move_hunk(self, dy: int) -> None:
        if self.hunks:
            self.hunk_idx = max(0, min(self.hunk_idx + dy, len(self.hunks) - 1))

    def selected_hunk(self) -> git.GitHunk | None:
        if 0 <= self.hunk_idx < len(self.hunks):
            return self.hunks[self.hunk_idx]
        return None

    def stage_selected_hunk(self) -> str:
        hunk = self.selected_hunk()
        if not hunk:
            return "No hunk selected"
        if hunk.staged:
            return "Hunk already staged"
        ok = git.stage_hunk(self.root_dir, hunk)
        self.last_result = "Hunk staged" if ok else "Stage hunk failed"
        self.refresh()
        self.cancel_hunk_mode()
        return self.last_result

    def unstage_selected_hunk(self) -> str:
        hunk = self.selected_hunk()
        if not hunk:
            return "No hunk selected"
        if not hunk.staged:
            return "Hunk not staged"
        ok = git.unstage_hunk(self.root_dir, hunk)
        self.last_result = "Hunk unstaged" if ok else "Unstage hunk failed"
        self.refresh()
        self.cancel_hunk_mode()
        return self.last_result

    def discard_selected_hunk(self) -> str:
        hunk = self.selected_hunk()
        if not hunk:
            return "No hunk selected"
        ok = git.discard_hunk(self.root_dir, hunk)
        self.last_result = "Hunk discarded" if ok else "Discard hunk failed"
        self.refresh()
        self.cancel_hunk_mode()
        return self.last_result

    # -- file actions ------------------------------------------------- #
    FILE_ACTIONS = [
        ("open", "Open file", "o"),
        ("diff", "Open in diff", "d"),
        ("stage", "Stage file", "s"),
        ("unstage", "Unstage file", "u"),
        ("discard", "Discard changes", "x"),
        ("copy_path", "Copy absolute path", "y"),
        ("copy_rel_path", "Copy relative path", "Y"),
    ]

    def begin_file_actions(self) -> None:
        """Show file actions menu for the selected file."""
        f = self.selected_file()
        if not f:
            return
        self.mode = "file_actions"
        self.action_file = f
        self.action_idx = 0

    def cancel_file_actions(self) -> None:
        self.mode = "normal"
        self.action_file = None
        self.action_idx = 0

    def move_action(self, dy: int) -> None:
        if hasattr(self, 'action_idx'):
            self.action_idx = max(0, min(self.action_idx + dy, len(self.FILE_ACTIONS) - 1))

    def selected_action(self) -> tuple[str, str, str] | None:
        """Return (action_id, label, key) for selected action."""
        if 0 <= self.action_idx < len(self.FILE_ACTIONS):
            return self.FILE_ACTIONS[self.action_idx]
        return None

    def execute_action(self) -> str:
        """Execute the selected file action."""
        action = self.selected_action()
        if not action or not self.action_file:
            return "No action selected"
        action_id, label, _ = action
        f = self.action_file

        if action_id == "open":
            self.last_result = f"Open {f.path} (not implemented in panel)"
        elif action_id == "diff":
            self.begin_diff()
            self.last_result = f"Showing diff for {f.path}"
        elif action_id == "stage":
            if not f.staged:
                ok = git.stage_file(self.root_dir, f.path)
                self.last_result = f"Staged {f.path}" if ok else f"Stage failed"
                self.refresh()
            else:
                self.last_result = "Already staged"
        elif action_id == "unstage":
            if f.staged:
                ok = git.unstage_file(self.root_dir, f.path)
                self.last_result = f"Unstaged {f.path}" if ok else f"Unstage failed"
                self.refresh()
            else:
                self.last_result = "Not staged"
        elif action_id == "discard":
            ok = git.discard_file(self.root_dir, f.path)
            self.last_result = f"Discarded {f.path}" if ok else "Discard failed"
            self.refresh()
        elif action_id == "copy_path":
            import os
            abs_path = os.path.join(self.root_dir, f.path)
            try:
                import subprocess
                subprocess.run(["wl-copy"], input=abs_path.encode(), check=False, timeout=1)
                self.last_result = f"Copied absolute path"
            except Exception:
                self.last_result = "Copy failed (wl-copy not available)"
        elif action_id == "copy_rel_path":
            try:
                import subprocess
                subprocess.run(["wl-copy"], input=f.path.encode(), check=False, timeout=1)
                self.last_result = f"Copied relative path"
            except Exception:
                self.last_result = "Copy failed (wl-copy not available)"
        else:
            self.last_result = f"Unknown action: {action_id}"

        self.cancel_file_actions()
        return self.last_result

    # -- stash ------------------------------------------------------ #

    def do_stash(self) -> str:
        ok = git.stash(self.root_dir)
        self.last_result = "Stashed" if ok else "Stash failed"
        self.refresh()
        return self.last_result

    def do_stash_pop(self) -> str:
        ok = git.stash_pop(self.root_dir)
        self.last_result = "Stash popped" if ok else "Stash pop failed"
        self.refresh()
        return self.last_result

    # -- branch management -------------------------------------------- #

    def begin_branch_management(self) -> None:
        """Enter branch management mode."""
        self.mode = "branch_manage"
        self.branches = git.get_branches(self.root_dir)
        self.remote_branches = git.get_remote_branches(self.root_dir)
        current = git.get_branch(self.root_dir)
        self.branch_mgmt_idx = 0
        self.branch_mgmt_action = 0  # 0=switch, 1=create, 2=delete, 3=rename, 4=publish
        if current in self.branches:
            self.branch_mgmt_idx = self.branches.index(current)

    def cancel_branch_management(self) -> None:
        self.mode = "normal"
        self.branch_mgmt_action = 0
        self.branch_mgmt_new_name = ""
        self.branch_mgmt_creating = False

    def move_branch_mgmt(self, dy: int) -> None:
        if self.branches:
            self.branch_mgmt_idx = max(0, min(self.branch_mgmt_idx + dy, len(self.branches) - 1))

    def move_branch_mgmt_action(self, dx: int) -> None:
        self.branch_mgmt_action = max(0, min(self.branch_mgmt_action + dx, 4))

    def begin_create_branch(self) -> None:
        self.branch_mgmt_creating = True
        self.branch_mgmt_new_name = ""

    def cancel_create_branch(self) -> None:
        self.branch_mgmt_creating = False
        self.branch_mgmt_new_name = ""

    def create_branch_char(self, ch: str) -> None:
        if self.branch_mgmt_creating:
            self.branch_mgmt_new_name += ch

    def create_branch_backspace(self) -> None:
        if self.branch_mgmt_creating:
            self.branch_mgmt_new_name = self.branch_mgmt_new_name[:-1]

    def do_create_branch(self) -> str:
        name = self.branch_mgmt_new_name.strip()
        if not name:
            return "Branch name cannot be empty"
        ok, out = git.create_branch(self.root_dir, name)
        self.branch_mgmt_creating = False
        self.branch_mgmt_new_name = ""
        self.last_result = f"Created branch {name}" if ok else f"Create failed: {out}"
        self.begin_branch_management()  # Refresh
        return self.last_result

    def do_delete_branch(self) -> str:
        if not self.branches:
            return "No branches"
        branch = self.branches[self.branch_mgmt_idx]
        current = git.get_branch(self.root_dir)
        if branch == current:
            return "Cannot delete current branch"
        # Ask for confirmation - use force delete for now
        ok, out = git.delete_branch(self.root_dir, branch, force=True)
        self.last_result = f"Deleted branch {branch}" if ok else f"Delete failed: {out}"
        self.begin_branch_management()  # Refresh
        return self.last_result

    def begin_rename_branch(self) -> None:
        if not self.branches:
            return
        self.branch_mgmt_creating = True
        self.branch_mgmt_new_name = self.branches[self.branch_mgmt_idx]

    def do_rename_branch(self) -> str:
        if not self.branches:
            return "No branches"
        old_name = self.branches[self.branch_mgmt_idx]
        new_name = self.branch_mgmt_new_name.strip()
        if not new_name or new_name == old_name:
            self.branch_mgmt_creating = False
            return "Invalid name"
        ok, out = git.rename_branch(self.root_dir, old_name, new_name)
        self.branch_mgmt_creating = False
        self.branch_mgmt_new_name = ""
        self.last_result = f"Renamed {old_name} to {new_name}" if ok else f"Rename failed: {out}"
        self.begin_branch_management()  # Refresh
        return self.last_result

    def do_publish_branch(self) -> str:
        if not self.branches:
            return "No branches"
        branch = self.branches[self.branch_mgmt_idx]
        ok, out = git.publish_branch(self.root_dir, branch)
        self.last_result = f"Published {branch}" if ok else f"Publish failed: {out}"
        return self.last_result

    def do_fetch_all(self) -> str:
        ok, out = git.fetch_all(self.root_dir)
        self.last_result = "Fetched all remotes" if ok else f"Fetch failed: {out}"
        self.refresh()
        return self.last_result

    # -- remote operations -------------------------------------------- #

    def begin_remote_ops(self) -> None:
        """Enter remote operations mode."""
        self.mode = "remote_ops"
        self.remote_idx = 0
        self.remote_action = 0  # 0=pull, 1=pull(rebase), 2=pull(ff-only), 3=push, 4=push(force-lease), 5=fetch
        self.remote_action_labels = [
            ("Pull", "pull", False),
            ("Pull (rebase)", "pull_rebase", False),
            ("Pull (ff-only)", "pull_ff", False),
            ("Push", "push", False),
            ("Push (--force-with-lease)", "push_fl", False),
            ("Fetch all (prune)", "fetch", True),
        ]

    def cancel_remote_ops(self) -> None:
        self.mode = "normal"

    def move_remote(self, dy: int) -> None:
        self.remote_idx = max(0, min(self.remote_idx + dy, len(self.remote_action_labels) - 1))

    def execute_remote_op(self) -> str:
        action = self.remote_action_labels[self.remote_idx]
        action_id = action[1]
        if action_id == "pull":
            ok, out = git.pull(self.root_dir)
            self.last_result = "Pulled" if ok else f"Pull failed: {out}"
        elif action_id == "pull_rebase":
            ok, out = git.pull(self.root_dir, rebase=True)
            self.last_result = "Pulled (rebase)" if ok else f"Pull (rebase) failed: {out}"
        elif action_id == "pull_ff":
            ok, out = git.pull(self.root_dir, ff_only=True)
            self.last_result = "Pulled (ff-only)" if ok else f"Pull (ff-only) failed: {out}"
        elif action_id == "push":
            ok, out = git.push(self.root_dir)
            self.last_result = "Pushed" if ok else f"Push failed: {out}"
        elif action_id == "push_fl":
            ok, out = git.push(self.root_dir, force_with_lease=True)
            self.last_result = "Pushed (--force-with-lease)" if ok else f"Push (--force-with-lease) failed: {out}"
        elif action_id == "fetch":
            ok, out = git.fetch_all(self.root_dir)
            self.last_result = "Fetched all" if ok else f"Fetch failed: {out}"
        else:
            self.last_result = "Unknown action"
        self.refresh()
        return self.last_result

    # -- issues ----------------------------------------------------- #

    def begin_issues(self) -> None:
        self.issues = github_api.list_issues(cwd=self.root_dir)
        self.issue_idx = 0
        self.mode = "issues"

    def cancel_issues(self) -> None:
        self.mode = "normal"

    def move_issue(self, dy: int) -> None:
        if self.issues:
            self.issue_idx = max(0, min(self.issue_idx + dy, len(self.issues) - 1))

    def selected_issue(self) -> github_api.GitHubIssue | None:
        if 0 <= self.issue_idx < len(self.issues):
            return self.issues[self.issue_idx]
        return None

    def do_close_issue(self) -> str:
        issue = self.selected_issue()
        if not issue:
            return "No issue selected"
        ok, out = github_api.close_issue(issue.number, cwd=self.root_dir)
        self.last_result = f"Closed #{issue.number}" if ok else f"Close: {out}"
        self.issues = github_api.list_issues(cwd=self.root_dir)
        if self.issue_idx >= len(self.issues):
            self.issue_idx = max(0, len(self.issues) - 1)
        return self.last_result

    def do_reopen_issue(self) -> str:
        issue = self.selected_issue()
        if not issue:
            return "No issue selected"
        ok, out = github_api.reopen_issue(issue.number, cwd=self.root_dir)
        self.last_result = f"Reopened #{issue.number}" if ok else f"Reopen: {out}"
        self.issues = github_api.list_issues(cwd=self.root_dir)
        return self.last_result

    # -- pull requests ----------------------------------------------- #

    def begin_prs(self) -> None:
        self.prs = github_api.list_prs(cwd=self.root_dir)
        self.pr_idx = 0
        self.mode = "prs"

    def cancel_prs(self) -> None:
        self.mode = "normal"

    def move_pr(self, dy: int) -> None:
        if self.prs:
            self.pr_idx = max(0, min(self.pr_idx + dy, len(self.prs) - 1))

    def selected_pr(self) -> github_api.GitHubPR | None:
        if 0 <= self.pr_idx < len(self.prs):
            return self.prs[self.pr_idx]
        return None

    def do_checkout_pr(self) -> str:
        pr = self.selected_pr()
        if not pr:
            return "No PR selected"
        ok, out = github_api.checkout_pr(pr.number, cwd=self.root_dir)
        self.last_result = f"Checked out PR #{pr.number}" if ok else f"Checkout: {out}"
        self.refresh()
        return self.last_result

    def do_merge_pr(self) -> str:
        pr = self.selected_pr()
        if not pr:
            return "No PR selected"
        ok, out = github_api.merge_pr(pr.number, cwd=self.root_dir)
        self.last_result = f"Merged PR #{pr.number}" if ok else f"Merge: {out}"
        self.prs = github_api.list_prs(cwd=self.root_dir)
        if self.pr_idx >= len(self.prs):
            self.pr_idx = max(0, len(self.prs) - 1)
        return self.last_result

    def do_close_pr(self) -> str:
        pr = self.selected_pr()
        if not pr:
            return "No PR selected"
        ok, out = github_api.close_pr(pr.number, cwd=self.root_dir)
        self.last_result = f"Closed PR #{pr.number}" if ok else f"Close: {out}"
        self.prs = github_api.list_prs(cwd=self.root_dir)
        if self.pr_idx >= len(self.prs):
            self.pr_idx = max(0, len(self.prs) - 1)
        return self.last_result


# ------------------------------------------------------------------ #
# Curses drawing
# ------------------------------------------------------------------ #

_STATUS_COLORS = {
    "M": curses.COLOR_YELLOW,
    "A": curses.COLOR_GREEN,
    "D": curses.COLOR_RED,
    "?": curses.COLOR_WHITE,
    "R": curses.COLOR_CYAN,
    "C": curses.COLOR_CYAN,
    "U": curses.COLOR_RED,
}

# Will be initialized once the curses color pair is set up
_PAIR_STAGED = 11
_PAIR_UNSTAGED = 12
_PAIR_HEADER = 13


def init_panel_colors() -> None:
    """Register color pairs for the git panel."""
    if not curses.has_colors():
        return
    try:
        from . import settings
        from . import themes
        name = settings.get_active_theme_name()
        if name:
            git = themes.THEMES[themes.resolve_theme_id(name)].get("git", {})
            fg, bg = themes._resolve(*git.get("staged", (3, -1)))
            curses.init_pair(_PAIR_STAGED, fg, bg)
            fg, bg = themes._resolve(*git.get("unstaged", (7, -1)))
            curses.init_pair(_PAIR_UNSTAGED, fg, bg)
            fg, bg = themes._resolve(*git.get("header", (6, -1)))
            curses.init_pair(_PAIR_HEADER, fg, bg)
            return
    except Exception:
        pass
    curses.init_pair(_PAIR_STAGED, curses.COLOR_YELLOW, -1)
    curses.init_pair(_PAIR_UNSTAGED, curses.COLOR_WHITE, -1)
    curses.init_pair(_PAIR_HEADER, curses.COLOR_CYAN, -1)


def draw_git_panel(stdscr, panel: GitPanel, height: int, width: int,
                   x_offset: int = 0) -> None:
    """Draw the source control panel at *x_offset* columns from the left."""
    if panel.mode == "diff":
        return  # diff is drawn as an overlay elsewhere

    # Draw vertical separator on the left edge
    for row in range(height):
        try:
            stdscr.addstr(row, x_offset, "\u2502", curses.A_DIM)
        except curses.error:
            pass

    col = x_offset + 1  # content starts after separator
    inner_w = width - 1  # usable width after separator
    row = 0

    # -- Header ----------------------------------------------------- #
    header = " SOURCE CONTROL "
    try:
        stdscr.addstr(row, col, header.center(inner_w)[:inner_w],
                      curses.A_REVERSE | curses.A_BOLD)
    except curses.error:
        pass
    row += 1

    # -- Branch info + ahead/behind --------------------------------- #
    branch = git.get_branch(panel.root_dir)
    if branch:
        branch_text = f" \u25b6 {branch}"
        if panel.ahead or panel.behind:
            parts = []
            if panel.ahead:
                parts.append(f"{panel.ahead} ahead")
            if panel.behind:
                parts.append(f"{panel.behind} behind")
            branch_text += f"  ({', '.join(parts)})"
        try:
            stdscr.addstr(row, col, branch_text[:inner_w],
                          curses.color_pair(_PAIR_HEADER) | curses.A_BOLD)
        except curses.error:
            pass
        row += 1

    # -- Separator -------------------------------------------------- #
    try:
        stdscr.addstr(row, col, "\u2500" * inner_w, curses.A_DIM)
    except curses.error:
        pass
    row += 1

    # -- Commit message box (always visible) ------------------------ #
    if panel.committing:
        if panel.commit_mode == "template_select":
            try:
                stdscr.addstr(row, col, " Commit template (Tab to close):", curses.A_BOLD)
            except curses.error:
                pass
            row += 1
            visible_templates = panel.COMMIT_TEMPLATES[:max(0, height - row - 3)]
            for i, (name, prefix, desc) in enumerate(visible_templates):
                if row >= height - 1:
                    break
                marker = "\u25b6 " if i == panel.template_idx else "  "
                label = f"{prefix}{desc}"
                try:
                    attr = curses.A_REVERSE if i == panel.template_idx else 0
                    stdscr.addstr(row, col, f"{marker}{label}"[:inner_w], attr)
                except curses.error:
                    pass
                row += 1
            try:
                stdscr.addstr(row, col, " Enter=apply  Esc=back  Tab=close", curses.A_DIM)
            except curses.error:
                pass
            row += 1
        else:
            try:
                stdscr.addstr(row, col, " Message (Tab=templates, Ctrl-Enter=newline):", curses.A_BOLD)
            except curses.error:
                pass
            row += 1
            try:
                msg_display = panel.commit_message[:inner_w - 2]
                placeholder = msg_display + "_" if len(msg_display) < len(panel.commit_message) else msg_display + "_"
                stdscr.addstr(row, col, f" {placeholder}"[:inner_w], curses.A_UNDERLINE)
            except curses.error:
                pass
            row += 1
            try:
                stdscr.addstr(row, col, " Enter=commit  Esc=cancel  Tab=templates", curses.A_DIM)
            except curses.error:
                pass
            row += 1
    else:
        try:
            msg_text = panel.commit_message if panel.commit_message else "Message..."
            display = f" {msg_text}"
            stdscr.addstr(row, col, display[:inner_w], curses.A_DIM)
        except curses.error:
            pass
        row += 1

    # -- Separator -------------------------------------------------- #
    try:
        stdscr.addstr(row, col, "\u2500" * inner_w, curses.A_DIM)
    except curses.error:
        pass
    row += 1

    # -- Branch select mode ----------------------------------------- #
    if panel.mode == "branch_select":
        try:
            stdscr.addstr(row, col, " Switch branch:", curses.A_BOLD)
        except curses.error:
            pass
        row += 1
        visible_branches = panel.branches[:max(0, height - row - 3)]
        for i, b in enumerate(visible_branches):
            if row >= height - 1:
                break
            marker = "\u25b6 " if i == panel.branch_idx else "  "
            try:
                attr = curses.A_REVERSE if i == panel.branch_idx else 0
                stdscr.addstr(row, col, f"{marker}{b}"[:inner_w], attr)
            except curses.error:
                pass
            row += 1
        try:
            stdscr.addstr(row, col, " Enter=switch  Esc=cancel", curses.A_DIM)
        except curses.error:
            pass
        row += 1

    # -- Hunk select mode ----------------------------------------------- #
    if panel.mode == "hunk_select":
        try:
            stdscr.addstr(row, col, " Hunks:", curses.A_BOLD)
        except curses.error:
            pass
        row += 1
        if not panel.hunks:
            try:
                stdscr.addstr(row, col, " No hunks", curses.A_DIM)
            except curses.error:
                pass
            row += 1
        else:
            f = panel.hunk_file
            if f:
                try:
                    stdscr.addstr(row, col, f" {f.path}"[:inner_w], curses.A_DIM)
                except curses.error:
                    pass
                row += 1
            for i, hunk in enumerate(panel.hunks):
                if row >= height - 1:
                    break
                start, end = hunk.line_range()
                status = "staged" if hunk.staged else "unstaged"
                label = f"  lines {start}-{end} ({status})"
                marker = " \u25cf " if i == panel.hunk_idx else "   "
                display = f"{marker}{label}"
                try:
                    attr = curses.A_REVERSE if i == panel.hunk_idx else 0
                    stdscr.addstr(row, col, display[:inner_w], attr)
                except curses.error:
                    pass
                row += 1
        try:
            stdscr.addstr(row, col, " s:stage  u:unstage  x:discard  Esc:back", curses.A_DIM)
        except curses.error:
            pass
        row += 1

    # -- Branch management mode ----------------------------------------- #
    if panel.mode == "branch_manage":
        if panel.branch_mgmt_creating:
            action_name = "Create" if panel.branch_mgmt_action == 1 else "Rename"
            try:
                stdscr.addstr(row, col, f" {action_name} branch:", curses.A_BOLD)
            except curses.error:
                pass
            row += 1
            try:
                prompt = panel.branch_mgmt_new_name + "_"
                stdscr.addstr(row, col, f" {prompt}"[:inner_w], curses.A_UNDERLINE)
            except curses.error:
                pass
            row += 1
            try:
                stdscr.addstr(row, col, " Enter=confirm  Esc=cancel", curses.A_DIM)
            except curses.error:
                pass
            row += 1
        else:
            try:
                stdscr.addstr(row, col, " Branch management (←→ actions, ↑↓ branches):", curses.A_BOLD)
            except curses.error:
                pass
            row += 1
            # Action tabs
            actions = ["Switch", "Create", "Delete", "Rename", "Publish"]
            action_labels = []
            for i, act in enumerate(actions):
                marker = f"[{act}]" if i == panel.branch_mgmt_action else f" {act} "
                action_labels.append(marker)
            try:
                stdscr.addstr(row, col, " ".join(action_labels)[:inner_w], curses.A_BOLD)
            except curses.error:
                pass
            row += 1
            # Branch list
            for i, b in enumerate(panel.branches):
                if row >= height - 1:
                    break
                current = git.get_branch(panel.root_dir)
                is_current = (b == current)
                prefix = "* " if is_current else "  "
                marker = "\u25b6 " if i == panel.branch_mgmt_idx else "  "
                display = f"{marker}{prefix}{b}"
                try:
                    attr = curses.A_REVERSE if i == panel.branch_mgmt_idx else (curses.A_BOLD if is_current else 0)
                    stdscr.addstr(row, col, display[:inner_w], attr)
                except curses.error:
                    pass
                row += 1
            # Remote branches
            if panel.remote_branches:
                try:
                    stdscr.addstr(row, col, " Remote branches:", curses.A_DIM)
                except curses.error:
                    pass
                row += 1
                for b in panel.remote_branches[:5]:  # Show first 5
                    if row >= height - 1:
                        break
                    try:
                        stdscr.addstr(row, col, f"  {b}"[:inner_w], curses.A_DIM)
                    except curses.error:
                        pass
                    row += 1
            try:
                stdscr.addstr(row, col, " Enter=act  ←→=action  ↑↓=branch  f=fetch  Esc=back", curses.A_DIM)
            except curses.error:
                pass
            row += 1

    # -- Remote operations mode ------------------------------------------ #
    if panel.mode == "remote_ops":
        try:
            stdscr.addstr(row, col, " Remote operations (↑↓ select, Enter=execute):", curses.A_BOLD)
        except curses.error:
            pass
        row += 1
        for i, (label, action_id, refreshes) in enumerate(panel.remote_action_labels):
            if row >= height - 1:
                break
            marker = " \u25cf " if i == panel.remote_idx else "   "
            display = f"{marker}{label}"
            try:
                attr = curses.A_REVERSE if i == panel.remote_idx else 0
                stdscr.addstr(row, col, display[:inner_w], attr)
            except curses.error:
                pass
            row += 1
        try:
            stdscr.addstr(row, col, " Enter=execute  Esc=back", curses.A_DIM)
        except curses.error:
            pass
        row += 1

    # -- File actions mode ---------------------------------------------- #
    if panel.mode == "file_actions":
        f = panel.action_file
        if f:
            try:
                stdscr.addstr(row, col, f" Actions for {f.path}:", curses.A_BOLD)
            except curses.error:
                pass
            row += 1
            for i, (action_id, label, key) in enumerate(panel.FILE_ACTIONS):
                if row >= height - 1:
                    break
                # Skip actions that don't apply
                if action_id == "stage" and f.staged:
                    continue
                if action_id == "unstage" and not f.staged:
                    continue
                if action_id == "discard" and f.status == "?":
                    continue  # Can't discard untracked
                marker = " \u25cf " if i == panel.action_idx else "   "
                display = f"{marker}{label} ({key})"
                try:
                    attr = curses.A_REVERSE if i == panel.action_idx else 0
                    stdscr.addstr(row, col, display[:inner_w], attr)
                except curses.error:
                    pass
                row += 1
        try:
            stdscr.addstr(row, col, " Enter=execute  Esc=back", curses.A_DIM)
        except curses.error:
            pass
        row += 1

    # -- Issues mode ------------------------------------------------ #
    if panel.mode == "issues":
        try:
            stdscr.addstr(row, col, " Issues:", curses.A_BOLD)
        except curses.error:
            pass
        row += 1
        if not panel.issues:
            try:
                stdscr.addstr(row, col, " No open issues", curses.A_DIM)
            except curses.error:
                pass
            row += 1
        else:
            for i, issue in enumerate(panel.issues):
                if row >= height - 1:
                    break
                label = f"#{issue.number} {issue.title}"
                marker = " \u25cf " if i == panel.issue_idx else "   "
                display = f"{marker}{label}"
                try:
                    attr = curses.A_REVERSE if i == panel.issue_idx else 0
                    stdscr.addstr(row, col, display[:inner_w], attr)
                except curses.error:
                    pass
                row += 1
        try:
            stdscr.addstr(row, col, " o:close  r:reopen  Esc:back", curses.A_DIM)
        except curses.error:
            pass
        row += 1

    # -- PRs mode --------------------------------------------------- #
    if panel.mode == "prs":
        try:
            stdscr.addstr(row, col, " Pull Requests:", curses.A_BOLD)
        except curses.error:
            pass
        row += 1
        if not panel.prs:
            try:
                stdscr.addstr(row, col, " No open PRs", curses.A_DIM)
            except curses.error:
                pass
            row += 1
        else:
            for i, pr in enumerate(panel.prs):
                if row >= height - 1:
                    break
                label = f"PR #{pr.number} {pr.title}"
                marker = " \u25cf " if i == panel.pr_idx else "   "
                display = f"{marker}{label}"
                try:
                    attr = curses.A_REVERSE if i == panel.pr_idx else 0
                    stdscr.addstr(row, col, display[:inner_w], attr)
                except curses.error:
                    pass
                row += 1
        try:
            stdscr.addstr(row, col, " c:checkout  m:merge  Esc:back", curses.A_DIM)
        except curses.error:
            pass
        row += 1

    # -- File list (Changes on top, Staged below — VS Code order) --- #
    staged = [f for f in panel.items if f.staged]
    unstaged = [f for f in panel.items if not f.staged]

    def _status_color(status: str) -> int:
        """Return curses color index for a status char (theme-aware)."""
        c = _STATUS_COLORS.get(status, curses.COLOR_WHITE)
        try:
            from . import settings
            from . import themes
            name = settings.get_active_theme_name()
            if name:
                c = themes.git_color(name, status)
            if getattr(curses, "COLORS", 256) < 256 and c >= 16:
                from .themes import _16_COLOR_MAP
                c = _16_COLOR_MAP.get(c, curses.COLOR_WHITE)
        except Exception:
            pass
        return c

    def _draw_section(label: str, count: int, can_stage_all: bool = False,
                      can_unstage_all: bool = False) -> None:
        nonlocal row
        if row >= height - 1:
            return
        count_str = f" ({count})" if count else ""
        header_text = f" {label}{count_str}"
        # Right-align stage/unstage icons
        icons = ""
        if can_stage_all and count == 0:
            pass
        elif can_unstage_all and count == 0:
            pass
        else:
            if can_stage_all:
                icons += " [+]"
            if can_unstage_all:
                icons += " [-]"
        padding = inner_w - len(header_text) - len(icons)
        full = header_text + " " * max(0, padding) + icons
        try:
            stdscr.addstr(row, col, full[:inner_w],
                          curses.color_pair(_PAIR_HEADER) | curses.A_BOLD)
        except curses.error:
            pass
        row += 1

    def _draw_file(f: git.GitFile, is_selected: bool) -> None:
        nonlocal row
        if row >= height - 1:
            return
        status_char = panel.STATUS_LABELS.get(f.status, f.status)
        prefix = " \u25cf " if is_selected else "   "
        # Truncate path to fit
        avail = inner_w - len(prefix) - 4  # status + space
        display_path = f.path
        if len(display_path) > avail:
            display_path = "..." + display_path[-(avail - 3):]
        text = f"{prefix}{status_char} {display_path}"
        try:
            attr = curses.A_REVERSE if is_selected else 0
            stdscr.addstr(row, col, text[:inner_w], attr)
        except curses.error:
            pass
        row += 1

    _draw_section("Staged Changes", len(staged), can_unstage_all=bool(staged))
    for f in staged:
        if row >= height - 1:
            break
        _draw_file(f, panel.items.index(f) == panel.selected_idx)

    _draw_section("Changes", len(unstaged), can_stage_all=bool(unstaged))
    for f in unstaged:
        if row >= height - 1:
            break
        _draw_file(f, panel.items.index(f) == panel.selected_idx)

    if not panel.items:
        try:
            stdscr.addstr(row, col, " No changes", curses.A_DIM)
        except curses.error:
            pass
        row += 1

    # -- Bottom separator + action bar + hints ---------------------- #
    bottom = height - 1
    try:
        stdscr.addstr(bottom - 2, col, "\u2500" * inner_w, curses.A_DIM)
    except curses.error:
        pass
    # Action buttons row
    actions = []
    if panel.committing:
        actions.append("\u2713 Commit")
    else:
        actions.append("c:Commit")
    actions.append("R:Refresh")
    if panel.ahead or panel.behind:
        actions.append("P:Pull")
    else:
        actions.append("P:Pull")
    actions.append("p:Push")
    action_text = " \u2502 ".join(actions)
    try:
        stdscr.addstr(bottom - 1, col, action_text[:inner_w], curses.A_DIM)
    except curses.error:
        pass
    # Key hints row
    hints = "s:stage u:unstage S:stage all U:unstage all d:diff h:hunks b:branch B:branches r:remote"
    try:
        stdscr.addstr(bottom, col, hints[:inner_w], curses.A_DIM)
    except curses.error:
        pass


# ------------------------------------------------------------------ #
# Key dispatch (returns True if the key was consumed)
# ------------------------------------------------------------------ #

def _is_up(key: str | int) -> bool:
    return key == "up" or key == curses.KEY_UP


def _is_down(key: str | int) -> bool:
    return key == "down" or key == curses.KEY_DOWN


def git_panel_key(panel: GitPanel, key: str | int) -> bool:
    """Handle a keypress when the git panel is active.

    Returns True if the key was consumed.
    """
    # Commit mode — any key
    if panel.committing:
        if panel.commit_mode == "template_select":
            if key == "\n":
                panel.apply_template()
            elif key == "\x1b":
                panel.cancel_commit_template_select()
            elif _is_up(key):
                panel.move_template(-1)
            elif _is_down(key):
                panel.move_template(1)
            return True

        if key == "\n":
            panel.do_commit()
        elif key == "\x1b":
            panel.cancel_commit()
        elif key == curses.KEY_BACKSPACE or key == "\x7f":
            panel.commit_backspace()
        elif key == "\t":  # Tab to show templates
            panel.begin_commit_template_select()
        elif key == "\x0a" or key == curses.KEY_ENTER:  # Ctrl-Enter for newline
            panel.commit_newline()
        elif isinstance(key, str) and len(key) == 1 and key.isprintable():
            panel.commit_char(key)
        return True

    # Branch select mode
    if panel.mode == "branch_select":
        if key == "\n":
            panel.do_switch_branch()
        elif key == "\x1b":
            panel.cancel_branch_select()
        elif _is_up(key):
            panel.move_branch(-1)
        elif _is_down(key):
            panel.move_branch(1)
        return True

    # Diff mode
    if panel.mode == "diff":
        if key == "\x1b" or key == "q":
            panel.end_diff()
            return True
        return False  # let scroll keys pass through to diff viewer

    # Hunk select mode
    if panel.mode == "hunk_select":
        if key == "\x1b" or key == "q":
            panel.cancel_hunk_mode()
        elif _is_up(key):
            panel.move_hunk(-1)
        elif _is_down(key):
            panel.move_hunk(1)
        elif key == "s":
            panel.stage_selected_hunk()
        elif key == "u":
            panel.unstage_selected_hunk()
        elif key == "x":
            panel.discard_selected_hunk()
        else:
            return True
        return True

    # Issues mode
    if panel.mode == "issues":
        if key == "\x1b":
            panel.cancel_issues()
        elif _is_up(key):
            panel.move_issue(-1)
        elif _is_down(key):
            panel.move_issue(1)
        elif key == "o":
            panel.do_close_issue()
        elif key == "r":
            panel.do_reopen_issue()
        else:
            return True
        return True

    # PRs mode
    if panel.mode == "prs":
        if key == "\x1b":
            panel.cancel_prs()
        elif _is_up(key):
            panel.move_pr(-1)
        elif _is_down(key):
            panel.move_pr(1)
        elif key == "c":
            panel.do_checkout_pr()
        elif key == "m":
            panel.do_merge_pr()
        else:
            return True
        return True

    # Branch management mode
    if panel.mode == "branch_manage":
        if panel.branch_mgmt_creating:
            if key == "\n":
                if panel.branch_mgmt_action == 1:  # create
                    panel.do_create_branch()
                elif panel.branch_mgmt_action == 3:  # rename
                    panel.do_rename_branch()
            elif key == "\x1b":
                panel.cancel_create_branch()
            elif key == curses.KEY_BACKSPACE or key == "\x7f":
                panel.create_branch_backspace()
            elif isinstance(key, str) and len(key) == 1 and key.isprintable():
                panel.create_branch_char(key)
            return True

        if key == "\x1b" or key == "q":
            panel.cancel_branch_management()
        elif _is_up(key):
            panel.move_branch_mgmt(-1)
        elif _is_down(key):
            panel.move_branch_mgmt(1)
        elif key == "\x1b[C" or key == curses.KEY_RIGHT:
            panel.move_branch_mgmt_action(1)
        elif key == "\x1b[D" or key == curses.KEY_LEFT:
            panel.move_branch_mgmt_action(-1)
        elif key == "\n":
            if panel.branch_mgmt_action == 0:  # switch
                panel.do_switch_branch()
            elif panel.branch_mgmt_action == 1:  # create
                panel.begin_create_branch()
            elif panel.branch_mgmt_action == 2:  # delete
                panel.do_delete_branch()
            elif panel.branch_mgmt_action == 3:  # rename
                panel.begin_rename_branch()
            elif panel.branch_mgmt_action == 4:  # publish
                panel.do_publish_branch()
        elif key == "f":
            panel.do_fetch_all()
        else:
            return True
        return True

    # Remote operations mode
    if panel.mode == "remote_ops":
        if key == "\x1b" or key == "q":
            panel.cancel_remote_ops()
        elif _is_up(key):
            panel.move_remote(-1)
        elif _is_down(key):
            panel.move_remote(1)
        elif key == "\n":
            panel.execute_remote_op()
        else:
            return True
        return True

    # File actions mode
    if panel.mode == "file_actions":
        if key == "\x1b" or key == "q":
            panel.cancel_file_actions()
        elif _is_up(key):
            panel.move_action(-1)
        elif _is_down(key):
            panel.move_action(1)
        elif key == "\n":
            panel.execute_action()
        else:
            return True
        return True

    # Normal mode
    if _is_up(key):
        panel.move_selection(-1)
    elif _is_down(key):
        panel.move_selection(1)
    elif key == "\n":
        panel.begin_file_actions()
    elif key == "c":
        panel.begin_commit()
    elif key == "s":
        panel.stage_selected()
    elif key == "u":
        panel.unstage_selected()
    elif key == "S":
        panel.stage_all()
    elif key == "U":
        panel.unstage_all()
    elif key == "d":
        panel.begin_diff()
    elif key == "h":
        panel.begin_hunk_mode()
    elif key == "p":
        panel.do_push()
    elif key == "P":
        panel.do_pull()
    elif key == "b":
        panel.begin_branch_select()
    elif key == "B":
        panel.begin_branch_management()
    elif key == "r":
        panel.begin_remote_ops()
    elif key == "R":
        panel.refresh()
        panel.last_result = "Refreshed"
    elif key == "I":
        panel.begin_issues()
    elif key == "M":
        panel.begin_prs()
    else:
        return False
    return True
