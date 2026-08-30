"""Git operations via subprocess (no Python git library).

All functions shell out to the ``git`` CLI with a short timeout and
return safe defaults when git is unavailable or the directory is not
a repository.  No third-party dependencies — stdlib only.
"""
from __future__ import annotations

import subprocess
import tempfile
import os
from typing import Optional

_TIMEOUT = 2  # seconds


def _run(args: list[str], cwd: str | None = None) -> subprocess.CompletedProcess | None:
    """Run a git command with a timeout.  Returns None on any failure."""
    try:
        return subprocess.run(
            ["git"] + args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None


def is_git_repo(path: str) -> bool:
    """Return True if *path* is inside a git working tree."""
    r = _run(["rev-parse", "--is-inside-work-tree"], cwd=path)
    return r is not None and r.returncode == 0 and "true" in r.stdout.lower()


def get_branch(path: str) -> Optional[str]:
    """Return the current branch name, or None on failure.

    Detached HEAD returns ``None`` rather than a raw hash so the status
    bar can fall back cleanly.
    """
    r = _run(["rev-parse", "--abbrev-ref", "HEAD"], cwd=path)
    if r is None or r.returncode != 0:
        return None
    branch = r.stdout.strip()
    return branch if branch and branch != "HEAD" else None


def get_ahead_behind(path: str) -> tuple[int, int]:
    """Return ``(ahead, behind)`` counts vs upstream, or ``(0, 0)``."""
    r = _run(["rev-list", "--left-right", "--count", "HEAD...@{upstream}"],
             cwd=path)
    if r is None or r.returncode != 0:
        return (0, 0)
    parts = r.stdout.strip().split()
    if len(parts) >= 2:
        try:
            return (int(parts[0]), int(parts[1]))
        except ValueError:
            pass
    return (0, 0)


def get_status_counts(path: str) -> dict[str, int]:
    """Return counts of modified, added, deleted, and untracked files.

    Returns ``{"modified": 0, "added": 0, "deleted": 0, "untracked": 0}``
    on any failure or when *path* is not a git repo.
    """
    defaults = {"modified": 0, "added": 0, "deleted": 0, "untracked": 0}
    r = _run(["status", "--porcelain"], cwd=path)
    if r is None or r.returncode != 0:
        return defaults
    counts = dict(defaults)
    for line in r.stdout.splitlines():
        if not line:
            continue
        code = line[:2].strip()
        if code in ("M", " m"):
            counts["modified"] += 1
        elif code in ("A", "A "):
            counts["added"] += 1
        elif code in ("D", " D"):
            counts["deleted"] += 1
        elif code == "??":
            counts["untracked"] += 1
        elif code in ("R", "C"):
            counts["modified"] += 1
        elif code in ("U", "UU", "AA", "DD"):
            counts["modified"] += 1
    return counts


def format_status_counts(counts: dict[str, int]) -> str:
    """Format status counts into a compact string like ``+3 ~1 -0 !2``.

    Zero-count segments are omitted for brevity.  Empty string when
    everything is clean.
    """
    parts = []
    if counts.get("added"):
        parts.append(f"+{counts['added']}")
    if counts.get("modified"):
        parts.append(f"~{counts['modified']}")
    if counts.get("deleted"):
        parts.append(f"-{counts['deleted']}")
    if counts.get("untracked"):
        parts.append(f"!{counts['untracked']}")
    return " ".join(parts)


# ------------------------------------------------------------------ #
# Status file list (for the source control panel)
# ------------------------------------------------------------------ #

class GitFile:
    """A single file entry from ``git status --porcelain``."""
    __slots__ = ("status", "path", "staged")

    def __init__(self, status: str, path: str, staged: bool) -> None:
        self.status = status   # "M", "A", "D", "?", "R", "C", "U", etc.
        self.path = path
        self.staged = staged

    def display_status(self) -> str:
        """Human-readable short status for the panel."""
        return self.status


def get_status_files(path: str) -> list[GitFile]:
    """Return the list of changed files from ``git status --porcelain``.

    Each entry carries a status letter, path, and whether it is staged
    (index) vs. unstaged (worktree).
    """
    r = _run(["status", "--porcelain"], cwd=path)
    if r is None or r.returncode != 0:
        return []
    files: list[GitFile] = []
    for line in r.stdout.splitlines():
        if not line:
            continue
        index_code = line[0]
        work_code = line[1]
        filepath = line[3:]
        # Index (staged) changes
        if index_code != " " and index_code != "?":
            files.append(GitFile(index_code, filepath, staged=True))
        # Worktree (unstaged) changes
        if work_code != " " and work_code != "?":
            files.append(GitFile(work_code, filepath, staged=False))
        # Untracked
        if index_code == "?" and work_code == "?":
            files.append(GitFile("?", filepath, staged=False))
    return files


# ------------------------------------------------------------------ #
# Diff
# ------------------------------------------------------------------ #

def get_diff(path: str, filepath: str | None = None) -> str:
    """Return unified diff of unstaged changes."""
    args = ["diff"]
    if filepath:
        args += ["--", filepath]
    r = _run(args, cwd=path)
    return r.stdout if r is not None else ""


def get_staged_diff(path: str, filepath: str | None = None) -> str:
    """Return unified diff of staged changes."""
    args = ["diff", "--cached"]
    if filepath:
        args += ["--", filepath]
    r = _run(args, cwd=path)
    return r.stdout if r is not None else ""


# ------------------------------------------------------------------ #
# Stage / unstage
# ------------------------------------------------------------------ #

def stage_file(path: str, filepath: str) -> bool:
    """Stage a single file (``git add <file>``)."""
    r = _run(["add", filepath], cwd=path)
    return r is not None and r.returncode == 0


def unstage_file(path: str, filepath: str) -> bool:
    """Unstage a single file (``git reset HEAD <file>``)."""
    r = _run(["reset", "HEAD", "--", filepath], cwd=path)
    return r is not None and r.returncode == 0


def stage_all(path: str) -> bool:
    """Stage all changes (``git add -A``)."""
    r = _run(["add", "-A"], cwd=path)
    return r is not None and r.returncode == 0


def unstage_all(path: str) -> bool:
    """Unstage all files (``git reset HEAD``)."""
    r = _run(["reset", "HEAD"], cwd=path)
    return r is not None and r.returncode == 0


# ------------------------------------------------------------------ #
# Commit / push / pull
# ------------------------------------------------------------------ #

def commit(path: str, message: str) -> bool:
    """Commit all staged changes."""
    r = _run(["commit", "-m", message], cwd=path)
    return r is not None and r.returncode == 0


def push(path: str, force_with_lease: bool = False, set_upstream: bool = False) -> tuple[bool, str]:
    """Push current branch. Returns (success, output)."""
    args = ["push"]
    if force_with_lease:
        args.append("--force-with-lease")
    if set_upstream:
        args.extend(["-u", "origin"])
    r = _run(args, cwd=path)
    if r is None:
        return False, "git not available"
    ok = r.returncode == 0
    output = r.stdout.strip() if ok else r.stderr.strip()
    return ok, output


def pull(path: str, rebase: bool = False, ff_only: bool = False) -> tuple[bool, str]:
    """Pull from remote. Returns (success, output)."""
    args = ["pull"]
    if rebase:
        args.append("--rebase")
    if ff_only:
        args.append("--ff-only")
    r = _run(args, cwd=path)
    if r is None:
        return False, "git not available"
    ok = r.returncode == 0
    output = r.stdout.strip() if ok else r.stderr.strip()
    return ok, output


# ------------------------------------------------------------------ #
# Branches
# ------------------------------------------------------------------ #

def get_branches(path: str) -> list[str]:
    """Return list of local branch names."""
    r = _run(["branch", "--format=%(refname:short)"], cwd=path)
    if r is None or r.returncode != 0:
        return []
    return [b.strip() for b in r.stdout.splitlines() if b.strip()]


def switch_branch(path: str, branch: str) -> tuple[bool, str]:
    """Switch to a branch. Returns (success, output)."""
    r = _run(["checkout", branch], cwd=path)
    if r is None:
        return False, "git not available"
    ok = r.returncode == 0
    output = r.stdout.strip() if ok else r.stderr.strip()
    return ok, output





# ------------------------------------------------------------------ #
# Stash
# ------------------------------------------------------------------ #

def stash(path: str) -> bool:
    """Stash all changes."""
    r = _run(["stash"], cwd=path)
    return r is not None and r.returncode == 0


def stash_pop(path: str) -> bool:
    """Pop the most recent stash."""
    r = _run(["stash", "pop"], cwd=path)
    return r is not None and r.returncode == 0


# ------------------------------------------------------------------ #
# Branch management
# ------------------------------------------------------------------ #

def create_branch(path: str, branch_name: str, start_point: str | None = None) -> tuple[bool, str]:
    """Create a new branch. Returns (success, output)."""
    args = ["branch", branch_name]
    if start_point:
        args.append(start_point)
    r = _run(args, cwd=path)
    if r is None:
        return False, "git not available"
    ok = r.returncode == 0
    output = r.stdout.strip() if ok else r.stderr.strip()
    return ok, output


def delete_branch(path: str, branch_name: str, force: bool = False) -> tuple[bool, str]:
    """Delete a branch. Returns (success, output)."""
    args = ["branch", "-d" if not force else "-D", branch_name]
    r = _run(args, cwd=path)
    if r is None:
        return False, "git not available"
    ok = r.returncode == 0
    output = r.stdout.strip() if ok else r.stderr.strip()
    return ok, output


def rename_branch(path: str, old_name: str, new_name: str) -> tuple[bool, str]:
    """Rename a branch. Returns (success, output)."""
    r = _run(["branch", "-m", old_name, new_name], cwd=path)
    if r is None:
        return False, "git not available"
    ok = r.returncode == 0
    output = r.stdout.strip() if ok else r.stderr.strip()
    return ok, output


def publish_branch(path: str, branch_name: str | None = None) -> tuple[bool, str]:
    """Push a branch to remote with upstream tracking (git push -u origin <branch>).
    If branch_name is None, uses current branch.
    Returns (success, output)."""
    current = get_branch(path)
    branch = branch_name or current
    if not branch:
        return False, "No branch to publish"
    r = _run(["push", "-u", "origin", branch], cwd=path)
    if r is None:
        return False, "git not available"
    ok = r.returncode == 0
    output = r.stdout.strip() if ok else r.stderr.strip()
    return ok, output


def fetch_all(path: str, prune: bool = True) -> tuple[bool, str]:
    """Fetch all remotes. Returns (success, output)."""
    args = ["fetch", "--all"]
    if prune:
        args.append("--prune")
    r = _run(args, cwd=path)
    if r is None:
        return False, "git not available"
    ok = r.returncode == 0
    output = r.stdout.strip() if ok else r.stderr.strip()
    return ok, output


def get_remote_branches(path: str) -> list[str]:
    """Return list of remote branch names."""
    r = _run(["branch", "-r", "--format=%(refname:short)"], cwd=path)
    if r is None or r.returncode != 0:
        return []
    return [b.strip() for b in r.stdout.splitlines() if b.strip()]


# ------------------------------------------------------------------ #
# Hunks (for inline diff markers and hunk-level staging)
# ------------------------------------------------------------------ #

class GitHunk:
    """A single diff hunk with line range information."""
    __slots__ = ("old_start", "old_count", "new_start", "new_count",
                 "lines", "header", "filepath", "staged")

    def __init__(self, old_start: int, old_count: int, new_start: int, new_count: int,
                 lines: list[str], header: str, filepath: str, staged: bool = False) -> None:
        self.old_start = old_start          # Starting line in original file
        self.old_count = old_count          # Number of lines in original
        self.new_start = new_start          # Starting line in new file
        self.new_count = new_count          # Number of lines in new
        self.lines = lines                  # Diff lines (starting with +, -, or space)
        self.header = header                # The @@ header line
        self.filepath = filepath            # Path of the file
        self.staged = staged                # Whether this hunk is from staged diff

    def line_range(self) -> tuple[int, int]:
        """Return (start_line, end_line) in the NEW file (1-indexed)."""
        return (self.new_start, self.new_start + self.new_count - 1)

    def contains_line(self, line_num: int) -> bool:
        """Check if a line number (1-indexed in new file) falls in this hunk."""
        start, end = self.line_range()
        return start <= line_num <= end

    def is_addition_only(self) -> bool:
        """True if hunk only adds lines (no deletions)."""
        return all(not l.startswith("-") for l in self.lines if l)

    def is_deletion_only(self) -> bool:
        """True if hunk only deletes lines (no additions)."""
        return all(not l.startswith("+") for l in self.lines if l)


def _parse_diff_hunks(diff_text: str, filepath: str, staged: bool = False) -> list[GitHunk]:
    """Parse unified diff into GitHunk objects with line numbers."""
    hunks: list[GitHunk] = []
    lines = diff_text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("@@"):
            # Parse hunk header: @@ -old_start,old_count +new_start,new_count @@
            import re
            match = re.match(r"@@\s+-(\d+),?(\d*)\s+\+(\d+),?(\d*)\s+@@", line)
            if not match:
                i += 1
                continue
            old_start = int(match.group(1))
            old_count = int(match.group(2)) if match.group(2) else 1
            new_start = int(match.group(3))
            new_count = int(match.group(4)) if match.group(4) else 1

            # Collect hunk lines
            hunk_lines = [line]
            i += 1
            while i < len(lines) and not lines[i].startswith("@@"):
                hunk_lines.append(lines[i])
                i += 1

            hunks.append(GitHunk(old_start, old_count, new_start, new_count,
                                 hunk_lines[1:], line, filepath, staged))
        else:
            i += 1
    return hunks


def get_diff_hunks(path: str, filepath: str | None = None, staged: bool = False) -> list[GitHunk]:
    """Return parsed hunks for a file (staged or unstaged)."""
    diff_text = get_staged_diff(path, filepath) if staged else get_diff(path, filepath)
    if not diff_text:
        return []
    return _parse_diff_hunks(diff_text, filepath or "", staged)


def _apply_hunk(path: str, hunk: GitHunk, reverse: bool = False, cached: bool = False) -> bool:
    """Apply or reverse a single hunk using git apply."""
    # Create a minimal diff containing only this hunk
    diff_lines = ["diff --git a/" + hunk.filepath + " b/" + hunk.filepath]
    diff_lines.append("index 000000..111111 100644")
    diff_lines.append("--- a/" + hunk.filepath)
    diff_lines.append("+++ b/" + hunk.filepath)
    diff_lines.append(hunk.header)
    diff_lines.extend(hunk.lines)
    diff_text = "\n".join(diff_lines) + "\n"

    # Write to temp file and apply
    with tempfile.NamedTemporaryFile(mode="w", suffix=".patch", delete=False) as f:
        f.write(diff_text)
        patch_file = f.name

    try:
        args = ["apply"]
        if reverse:
            args.append("--reverse")
        if cached:
            args.append("--cached")
        args.append(patch_file)
        r = _run(args, cwd=path)
        return r is not None and r.returncode == 0
    finally:
        try:
            os.unlink(patch_file)
        except OSError:
            pass


def stage_hunk(path: str, hunk: GitHunk) -> bool:
    """Stage a single hunk (apply to index)."""
    if hunk.staged:
        return True  # Already staged
    return _apply_hunk(path, hunk, reverse=False, cached=True)


def unstage_hunk(path: str, hunk: GitHunk) -> bool:
    """Unstage a single hunk (reverse apply from index)."""
    if not hunk.staged:
        return True  # Not staged
    return _apply_hunk(path, hunk, reverse=True, cached=True)


def discard_hunk(path: str, hunk: GitHunk) -> bool:
    """Discard a hunk from worktree (reverse apply)."""
    if hunk.staged:
        # If staged, we need to unstage first, then discard from worktree
        if not _apply_hunk(path, hunk, reverse=True, cached=True):
            return False
    return _apply_hunk(path, hunk, reverse=True, cached=False)


def discard_file(path: str, filepath: str) -> bool:
    """Discard all changes to a file in worktree (git checkout -- <file>)."""
    r = _run(["checkout", "--", filepath], cwd=path)
    return r is not None and r.returncode == 0
