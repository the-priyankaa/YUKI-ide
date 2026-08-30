"""Codeium AI inline-completion client (free-tier, stdlib-only).

Uses the Codeium Public API with a personal API key.
Key is stored in ``~/.config/stdedit/codeium_key``.

If the key is missing or the API is unreachable, suggestions silently
return ``None`` so the editor is never blocked.
"""
from __future__ import annotations

import json
import os
import subprocess
from typing import Optional

_TIMEOUT = 8  # seconds


def _key_path() -> str:
    return os.path.join(os.path.expanduser("~"), ".config", "stdedit", "codeium_key")


def get_api_key() -> str:
    """Read the stored Codeium API key, or empty string."""
    path = _key_path()
    if not os.path.isfile(path):
        return ""
    try:
        with open(path, "r") as f:
            return f.read().strip()
    except OSError:
        return ""


def set_api_key(key: str) -> None:
    """Persist the Codeium API key (owner-only file: 0600)."""
    path = _key_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(key.strip())
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _extract_prefix(buffer_lines: list[str], cursor_y: int, cursor_x: int,
                    max_context: int = 50) -> str:
    """Grab up to *max_context* lines before the cursor as prefix."""
    start = max(0, cursor_y - max_context)
    lines = buffer_lines[start:cursor_y + 1]
    if not lines:
        return ""
    # Truncate last line at cursor position
    if cursor_y < len(buffer_lines):
        lines[-1] = lines[-1][:cursor_x]
    return "\n".join(lines)


def _extract_suffix(buffer_lines: list[str], cursor_y: int, cursor_x: int,
                    max_context: int = 20) -> str:
    """Grab a few lines after the cursor as suffix."""
    if cursor_y >= len(buffer_lines):
        return ""
    lines = buffer_lines[cursor_y:cursor_y + max_context]
    if lines:
        lines[0] = lines[0][cursor_x:]
    return "\n".join(lines)


def _language_id(filename: str) -> str:
    """Map file extensions to Codeium language identifiers."""
    ext_map = {
        ".py": "python", ".js": "javascript", ".ts": "typescript",
        ".jsx": "javascript", ".tsx": "typescript", ".java": "java",
        ".c": "c", ".h": "c", ".cpp": "cpp", ".hpp": "cpp",
        ".go": "go", ".rs": "rust", ".rb": "ruby",
        ".css": "css", ".html": "html", ".htm": "html",
        ".json": "json", ".yaml": "yaml", ".yml": "yaml",
        ".xml": "xml", ".sql": "sql", ".sh": "shell",
        ".md": "markdown", ".txt": "plaintext",
    }
    _, ext = os.path.splitext(filename)
    return ext_map.get(ext.lower(), "plaintext")


class Completion:
    """A single inline suggestion."""
    __slots__ = ("text", "range_start_y", "range_start_x",
                 "range_end_y", "range_end_x", "completion_type")

    def __init__(self, text: str, start_y: int = 0, start_x: int = 0,
                 end_y: int = 0, end_x: int = 0,
                 completion_type: str = "completion") -> None:
        self.text = text
        self.range_start_y = start_y
        self.range_start_x = start_x
        self.range_end_y = end_y
        self.range_end_x = end_x
        self.completion_type = completion_type

    def __repr__(self) -> str:
        preview = self.text[:40].replace("\n", "\\n")
        return f"Completion({preview!r}...)"


def get_completion(
    buffer_lines: list[str],
    cursor_y: int,
    cursor_x: int,
    filename: str = "",
    api_key: str = "",
) -> Optional[Completion]:
    """Request an inline completion from Codeium.

    Returns ``None`` if unavailable (no key, network error, etc.).
    """
    key = api_key or get_api_key()
    if not key:
        return None

    prefix = _extract_prefix(buffer_lines, cursor_y, cursor_x)
    suffix = _extract_suffix(buffer_lines, cursor_y, cursor_x)
    lang = _language_id(filename)

    payload = {
        "prompt": prefix,
        "suffix": suffix,
        "lang": lang,
        "filename": os.path.basename(filename) if filename else "",
        "cursor": {"row": cursor_y + 1, "col": cursor_x},
        "editor": {"name": "stdedit", "version": "1.0"},
        "context": {"max_length": 100},
    }

    try:
        r = subprocess.run(
            ["curl", "-s", "-X", "POST",
             "https://api.codeium.com/codeium/v1/completions/",
             "-H", "Content-Type: application/json",
             "-H", f"Authorization: Bearer {key}",
             "-d", json.dumps(payload)],
            capture_output=True, text=True, timeout=_TIMEOUT,
        )
        if r.returncode != 0:
            return None
        data = json.loads(r.stdout)
        completions = data.get("completions") or data.get("data", {}).get("completions", [])
        if not completions:
            return None
        # Pick the first suggestion
        c = completions[0]
        text = c.get("text") or c.get("completion", "")
        if not text:
            return None
        return Completion(
            text=text,
            start_y=cursor_y,
            start_x=cursor_x,
            end_y=cursor_y + text.count("\n"),
            end_x=len(text.split("\n")[-1]) if "\n" in text else cursor_x + len(text),
        )
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError, KeyError):
        return None
