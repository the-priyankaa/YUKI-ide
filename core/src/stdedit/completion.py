"""Path tab-completion — stdlib only.

Provides file-system path completion for prompts (new file, new folder,
open file).  No third-party dependencies.
"""
from __future__ import annotations

import os
from typing import List


def complete_path(partial: str) -> List[str]:
    """Return possible completions for a file path.

    Expands ``~``, resolves the directory portion, and lists entries
    matching the final component.  Directories get a trailing ``/``.
    Returns an empty list when there is nothing to complete.
    """
    if not partial:
        return []

    expanded = os.path.expanduser(partial)

    # Split into directory + partial filename.
    if expanded.endswith("/"):
        directory = expanded
        prefix = ""
    else:
        directory = os.path.dirname(expanded) or "."
        prefix = os.path.basename(expanded)

    try:
        entries = os.listdir(directory)
    except OSError:
        return []

    matches = []
    for name in entries:
        if not name.startswith(prefix):
            continue
        full = os.path.join(directory, name)
        if os.path.isdir(full):
            matches.append(full + "/")
        else:
            matches.append(full)

    matches.sort()
    return matches


def common_prefix(paths: List[str]) -> str:
    """Return the longest common directory prefix of *paths*.

    Used when Tab is pressed multiple times with ambiguous completions.
    """
    if not paths:
        return ""
    if len(paths) == 1:
        return paths[0]

    # os.path.commonprefix works on characters, not path components.
    prefix = os.path.commonprefix(paths)
    # Trim to last complete path separator.
    idx = prefix.rfind("/")
    if idx >= 0:
        return prefix[: idx + 1]
    return prefix
