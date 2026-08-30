"""Tests for the GitHub API wrapper (gh CLI)."""
import unittest
from unittest.mock import patch, MagicMock

from stdedit.github_api import (
    is_gh_authenticated, get_authenticated_user, get_current_repo,
    GitHubIssue, GitHubPR,
    list_issues, create_issue, close_issue, reopen_issue,
    list_prs, create_pr, merge_pr, close_pr, checkout_pr,
    get_pr_checks,
    format_issue_line, format_pr_line,
    _gh, _gh_json,
)


class TestGhHelper(unittest.TestCase):
    @patch("subprocess.run")
    def test_gh_success(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="ok\n", stderr="")
        ok, out = _gh(["auth", "status"])
        self.assertTrue(ok)
        self.assertEqual(out, "ok")

    @patch("subprocess.run")
    def test_gh_failure(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="not found")
        ok, out = _gh(["auth", "status"])
        self.assertFalse(ok)
        self.assertEqual(out, "not found")

    @patch("subprocess.run", side_effect=FileNotFoundError)
    def test_gh_not_installed(self, _):
        ok, out = _gh(["auth", "status"])
        self.assertFalse(ok)
        self.assertIn("not installed", out)

    @patch("subprocess.run")
    def test_gh_json_success(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout='[{"x":1}]', stderr="")
        ok, items = _gh_json(["issue", "list"])
        self.assertTrue(ok)
        self.assertEqual(items, [{"x": 1}])

    @patch("subprocess.run")
    def test_gh_json_bad_output(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="not json", stderr="")
        ok, items = _gh_json(["issue", "list"])
        self.assertFalse(ok)
        self.assertEqual(items, [])


class TestAuth(unittest.TestCase):
    @patch("subprocess.run")
    def test_authenticated(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        self.assertTrue(is_gh_authenticated())

    @patch("subprocess.run")
    def test_not_authenticated(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="not logged in")
        self.assertFalse(is_gh_authenticated())

    @patch("subprocess.run")
    def test_get_user(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="cat\n", stderr="")
        self.assertEqual(get_authenticated_user(), "cat")

    @patch("subprocess.run")
    def test_get_repo(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout='{"nameWithOwner":"a/b"}', stderr="")
        # get_current_repo uses --jq so raw output
        mock_run.return_value = MagicMock(returncode=0, stdout="a/b\n", stderr="")
        self.assertEqual(get_current_repo(), "a/b")


class TestIssues(unittest.TestCase):
    @patch("subprocess.run")
    def test_list_issues(self, mock_run):
        data = [{"number": 1, "title": "bug", "state": "OPEN",
                 "author": {"login": "u"}, "labels": [{"name": "bug"}], "url": ""}]
        mock_run.return_value = MagicMock(returncode=0, stdout=str(data).replace("'", '"'), stderr="")
        # _gh_json uses json.loads, so mock valid JSON
        import json
        mock_run.return_value = MagicMock(returncode=0, stdout=json.dumps(data), stderr="")
        issues = list_issues()
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].number, 1)
        self.assertEqual(issues[0].title, "bug")
        self.assertEqual(issues[0].state, "OPEN")
        self.assertEqual(issues[0].labels, ["bug"])

    @patch("subprocess.run")
    def test_list_issues_failure(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="error")
        issues = list_issues()
        self.assertEqual(issues, [])

    @patch("subprocess.run")
    def test_create_issue(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="https://github.com/a/b/issues/1\n", stderr="")
        ok, out = create_issue("title", body="body")
        self.assertTrue(ok)

    @patch("subprocess.run")
    def test_close_issue(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        ok, _ = close_issue(1)
        self.assertTrue(ok)

    @patch("subprocess.run")
    def test_reopen_issue(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        ok, _ = reopen_issue(1)
        self.assertTrue(ok)


class TestPRs(unittest.TestCase):
    @patch("subprocess.run")
    def test_list_prs(self, mock_run):
        import json
        data = [{"number": 5, "title": "feat", "state": "OPEN",
                 "author": {"login": "u"}, "headRefName": "feat", "baseRefName": "main", "url": ""}]
        mock_run.return_value = MagicMock(returncode=0, stdout=json.dumps(data), stderr="")
        prs = list_prs()
        self.assertEqual(len(prs), 1)
        self.assertEqual(prs[0].number, 5)
        self.assertEqual(prs[0].head, "feat")

    @patch("subprocess.run")
    def test_list_prs_failure(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="error")
        prs = list_prs()
        self.assertEqual(prs, [])

    @patch("subprocess.run")
    def test_create_pr(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="https://github.com/a/b/pull/1\n", stderr="")
        ok, _ = create_pr("title", body="body", head="feat", base="main")
        self.assertTrue(ok)

    @patch("subprocess.run")
    def test_merge_pr(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        ok, _ = merge_pr(1)
        self.assertTrue(ok)

    @patch("subprocess.run")
    def test_close_pr(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        ok, _ = close_pr(1)
        self.assertTrue(ok)

    @patch("subprocess.run")
    def test_checkout_pr(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        ok, _ = checkout_pr(1)
        self.assertTrue(ok)

    @patch("subprocess.run")
    def test_get_pr_checks_empty(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="[]", stderr="")
        checks = get_pr_checks(1)
        self.assertEqual(checks, [])


class TestFormat(unittest.TestCase):
    def test_format_issue_line(self):
        issue = GitHubIssue(42, "fix bug", "OPEN", labels=["bug", "p1"])
        line = format_issue_line(issue)
        self.assertIn("#42", line)
        self.assertIn("fix bug", line)
        self.assertIn("[bug]", line)

    def test_format_issue_line_no_labels(self):
        issue = GitHubIssue(1, "title", "CLOSED")
        line = format_issue_line(issue)
        self.assertEqual(line, "#1 title")

    def test_format_pr_line(self):
        pr = GitHubPR(7, "new feature", "OPEN")
        line = format_pr_line(pr)
        self.assertIn("PR #7", line)
        self.assertIn("new feature", line)

    def test_issue_repr(self):
        issue = GitHubIssue(1, "t", "OPEN")
        self.assertIn("#1", repr(issue))

    def test_pr_repr(self):
        pr = GitHubPR(1, "t", "OPEN")
        self.assertIn("PR #1", repr(pr))


if __name__ == "__main__":
    unittest.main()
