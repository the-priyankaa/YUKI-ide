"""System clipboard helper — stdlib only.

Detects an available clipboard tool (wl-copy/paste, xclip, pbcopy/pbpaste)
and exposes ``sys_copy()`` / ``sys_paste()`` functions.  All operations are
best-effort: they silently swallow errors so the editor never crashes due
to a missing clipboard tool.
"""

from __future__ import annotations

import shutil
import subprocess
from typing import Optional, Tuple

_copy_cmd: Optional[list[str]] = None
_paste_cmd: Optional[list[str]] = None


def _detect() -> Tuple[Optional[list[str]], Optional[list[str]]]:
    """Return ``(copy_cmd_template, paste_cmd_template)`` or ``(None, None)``."""
    if shutil.which("wl-copy") and shutil.which("wl-paste"):
        return (["wl-copy"], ["wl-paste", "--no-newline"])
    if shutil.which("xclip"):
        base = ["xclip", "-selection", "clipboard"]
        return (base, base + ["-o"])
    if shutil.which("pbcopy") and shutil.which("pbpaste"):
        return (["pbcopy"], ["pbpaste"])
    return (None, None)


def _ensure_detected() -> None:
    global _copy_cmd, _paste_cmd
    if _copy_cmd is None and _paste_cmd is None:
        _copy_cmd, _paste_cmd = _detect()


def sys_copy(text: str) -> bool:
    """Write *text* to the system clipboard.  Returns True on success."""
    _ensure_detected()
    if _copy_cmd is None:
        return False
    try:
        proc = subprocess.run(
            _copy_cmd,
            input=text.encode("utf-8"),
            timeout=2,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return proc.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def sys_paste() -> str:
    """Read text from the system clipboard.  Returns ``""`` on failure."""
    _ensure_detected()
    if _paste_cmd is None:
        return ""
    try:
        proc = subprocess.run(
            _paste_cmd,
            capture_output=True,
            timeout=2,
        )
        if proc.returncode == 0:
            return proc.stdout.decode("utf-8", errors="replace")
    except (OSError, subprocess.TimeoutExpired):
        pass
    return ""
