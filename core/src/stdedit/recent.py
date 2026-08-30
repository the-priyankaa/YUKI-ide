"""Recently opened files — persistent JSON-backed list.

Stores the last 50 opened file paths in ``~/.config/stdedit/recent.json``
so the editor can offer quick access across sessions.  Write failures are
silently ignored so the editor always works.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "stdedit"
RECENT_FILE = CONFIG_DIR / "recent.json"

MAX_ENTRIES = 50

_recent: list[str] = []


def _load() -> None:
    """Load recent list from disk."""
    global _recent
    _recent = []
    try:
        raw = RECENT_FILE.read_text(encoding="utf-8")
        data = json.loads(raw)
        if isinstance(data, list):
            _recent = [str(p) for p in data if isinstance(p, str)]
    except (OSError, json.JSONDecodeError, ValueError):
        pass


def _save() -> None:
    """Persist recent list to disk."""
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        RECENT_FILE.write_text(
            json.dumps(_recent, indent=2), encoding="utf-8"
        )
    except OSError:
        pass


def add_recent(path: str) -> None:
    """Add *path* to the recent list, deduplicating and capping."""
    if not path:
        return
    abspath = os.path.abspath(path)
    # Remove existing entry (if any) so we can promote to top.
    if abspath in _recent:
        _recent.remove(abspath)
    _recent.insert(0, abspath)
    # Cap length.
    del _recent[MAX_ENTRIES:]
    _save()


def get_recent() -> list[str]:
    """Return the recent file list (most recent first)."""
    if not _recent:
        _load()
    return list(_recent)


def remove_recent(path: str) -> None:
    """Remove *path* from the recent list."""
    abspath = os.path.abspath(path)
    if abspath in _recent:
        _recent.remove(abspath)
        _save()
