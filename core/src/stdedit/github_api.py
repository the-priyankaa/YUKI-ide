"""GitHub integration via the ``gh`` CLI (stdlib-only).

All functions use ``subprocess.run`` with a timeout.  If ``gh`` is not
installed or the command fails, safe defaults are returned so the editor
never crashes.
"""
from __future__ import annotations

import json
import subprocess


_TIMEOUT = 5  # seconds


def _gh(args: list[str], cwd: str | None = None) -> tuple[bool, str]:
    """Run ``gh <args>`` and return (success, stdout-or-error)."""
    try:
        r = subprocess.run(
            ["gh"] + args,
            capture_output=True, text=True, timeout=_TIMEOUT, cwd=cwd,
        )
        if r.returncode == 0:
            return True, r.stdout.strip()
        return False, r.stderr.strip() or "unknown error"
    except FileNotFoundError:
        return False, "gh CLI not installed"
    except subprocess.TimeoutExpired:
        return False, "timeout"


def _gh_json(args: list[str], cwd: str | None = None) -> tuple[bool, list[dict]]:
    """Run ``gh <args> --json ...`` and parse JSON output."""
    ok, out = _gh(args, cwd=cwd)
    if not ok:
        return False, []
    try:
        return True, json.loads(out)
    except (json.JSONDecodeError, TypeError):
        return False, []


# ------------------------------------------------------------------ #
# Auth
# ------------------------------------------------------------------ #

def is_gh_authenticated() -> bool:
    ok, _ = _gh(["auth", "status"])
    return ok


def get_authenticated_user() -> str:
    ok, out = _gh(["api", "user", "--jq", ".login"])
    return out if ok else ""


# ------------------------------------------------------------------ #
# Repositories
# ------------------------------------------------------------------ #

def get_current_repo() -> str:
    ok, out = _gh(["repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"])
    return out if ok else ""


# ------------------------------------------------------------------ #
# Issues
# ------------------------------------------------------------------ #

class GitHubIssue:
    __slots__ = ("number", "title", "state", "author", "labels", "url")

    def __init__(self, number: int, title: str, state: str,
                 author: str = "", labels: list[str] | None = None,
                 url: str = "") -> None:
        self.number = number
        self.title = title
        self.state = state
        self.author = author
        self.labels = labels or []
        self.url = url

    def __repr__(self) -> str:
        return f"#{self.number} {self.title} [{self.state}]"


def list_issues(state: str = "open", limit: int = 20, cwd: str | None = None) -> list[GitHubIssue]:
    ok, items = _gh_json(
        ["issue", "list", "--state", state, "--limit", str(limit),
         "--json", "number,title,state,author,labels,url"],
        cwd=cwd,
    )
    if not ok:
        return []
    result = []
    for item in items:
        labels = [lb.get("name", "") for lb in item.get("labels", [])]
        author = ""
        a = item.get("author")
        if isinstance(a, dict):
            author = a.get("login", "")
        result.append(GitHubIssue(
            number=item["number"],
            title=item["title"],
            state=item.get("state", "open"),
            author=author,
            labels=labels,
            url=item.get("url", ""),
        ))
    return result


def create_issue(title: str, body: str = "", cwd: str | None = None) -> tuple[bool, str]:
    args = ["issue", "create", "--title", title]
    if body:
        args += ["--body", body]
    ok, out = _gh(args, cwd=cwd)
    return ok, out


def close_issue(number: int, cwd: str | None = None) -> tuple[bool, str]:
    return _gh(["issue", "close", str(number)], cwd=cwd)


def reopen_issue(number: int, cwd: str | None = None) -> tuple[bool, str]:
    return _gh(["issue", "reopen", str(number)], cwd=cwd)


# ------------------------------------------------------------------ #
# Pull requests
# ------------------------------------------------------------------ #

class GitHubPR:
    __slots__ = ("number", "title", "state", "author", "head", "base", "url")

    def __init__(self, number: int, title: str, state: str,
                 author: str = "", head: str = "", base: str = "",
                 url: str = "") -> None:
        self.number = number
        self.title = title
        self.state = state
        self.author = author
        self.head = head
        self.base = base
        self.url = url

    def __repr__(self) -> str:
        return f"PR #{self.number} {self.title} [{self.state}]"


def list_prs(state: str = "open", limit: int = 20, cwd: str | None = None) -> list[GitHubPR]:
    ok, items = _gh_json(
        ["pr", "list", "--state", state, "--limit", str(limit),
         "--json", "number,title,state,author,headRefName,baseRefName,url"],
        cwd=cwd,
    )
    if not ok:
        return []
    result = []
    for item in items:
        author = ""
        a = item.get("author")
        if isinstance(a, dict):
            author = a.get("login", "")
        result.append(GitHubPR(
            number=item["number"],
            title=item["title"],
            state=item.get("state", "open"),
            author=author,
            head=item.get("headRefName", ""),
            base=item.get("baseRefName", ""),
            url=item.get("url", ""),
        ))
    return result


def create_pr(title: str, body: str = "", head: str = "HEAD",
              base: str = "", draft: bool = False,
              cwd: str | None = None) -> tuple[bool, str]:
    args = ["pr", "create", "--title", title]
    if body:
        args += ["--body", body]
    if head:
        args += ["--head", head]
    if base:
        args += ["--base", base]
    if draft:
        args.append("--draft")
    ok, out = _gh(args, cwd=cwd)
    return ok, out


def merge_pr(number: int, method: str = "merge",
             cwd: str | None = None) -> tuple[bool, str]:
    return _gh(["pr", "merge", str(number), "--" + method], cwd=cwd)


def close_pr(number: int, cwd: str | None = None) -> tuple[bool, str]:
    return _gh(["pr", "close", str(number)], cwd=cwd)


def checkout_pr(number: int, cwd: str | None = None) -> tuple[bool, str]:
    return _gh(["pr", "checkout", str(number)], cwd=cwd)


# ------------------------------------------------------------------ #
# Checks / CI
# ------------------------------------------------------------------ #

def get_pr_checks(pr_number: int, cwd: str | None = None) -> list[dict]:
    ok, items = _gh_json(
        ["pr", "checks", str(pr_number), "--json", "name,state,conclusion,detailsUrl"],
        cwd=cwd,
    )
    return items if ok else []


# ------------------------------------------------------------------ #
# Formatting
# ------------------------------------------------------------------ #

def format_issue_line(issue: GitHubIssue) -> str:
    label_str = " ".join(f"[{l}]" for l in issue.labels) if issue.labels else ""
    return f"#{issue.number} {issue.title} {label_str}".strip()


def format_pr_line(pr: GitHubPR) -> str:
    return f"PR #{pr.number} {pr.title}"
