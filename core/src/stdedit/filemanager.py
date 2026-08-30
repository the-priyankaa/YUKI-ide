"""
filemanager.py — system file-manager integration for stdedit.

Uses whatever desktop helpers are installed (zenity/kdialog to pick a
folder, xdg-open/open to reveal one) and degrades gracefully when they
are missing. Only the Python standard library is imported, keeping the
zero-dependency pledge; the helpers themselves are optional binaries.
"""

from __future__ import annotations

import shutil
import subprocess
from typing import Callable, List, Optional, Tuple

_PICK_TIMEOUT_SECONDS = 30

# Folder-picker helpers, first installed wins.
# "{start}" is replaced with the directory the browse starts from.
_FOLDER_PICKERS: List[Tuple[str, List[str]]] = [
    ("zenity", ["zenity", "--file-selection", "--directory", "--title=Open Project"]),
    ("kdialog", ["kdialog", "--getexistingdirectory", "{start}", "--title", "Open Project"]),
]

# Folder revealers, most portable first.
_REVEALERS = ("xdg-open", "open")


def pick_folder(
    start_dir: str,
    _which: Callable[[str], Optional[str]] = shutil.which,
    _run: Callable[..., object] = subprocess.run,
) -> Tuple[Optional[str], str]:
    """Ask the desktop's file manager to choose a folder.

    Returns (path, info):
      path   -- chosen absolute path, or None on cancel/failure
      info   -- helper name on success, otherwise a short reason
                ("cancelled", "<helper> timed out",
                 "<helper> failed: ...", "no system picker available")
    """
    for name, template in _FOLDER_PICKERS:
        if not _which(name):
            continue
        cmd = [arg.replace("{start}", start_dir) for arg in template]
        try:
            result = _run(cmd, capture_output=True, text=True, timeout=_PICK_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            return None, f"{name} timed out"
        except OSError as exc:
            return None, f"{name} failed: {exc}"
        path = result.stdout.strip()  # type: ignore[union-attr]
        if not path:
            # Empty output covers an explicit dialog cancel as well as a
            # helper that failed without producing a choice.
            return None, "cancelled"
        return path, name
    return None, "no system picker available"


def reveal_in_file_manager(
    path: str,
    _which: Callable[[str], Optional[str]] = shutil.which,
    _popen: Callable[..., object] = subprocess.Popen,
) -> Tuple[bool, str]:
    """Open `path` in the desktop's file manager (non-blocking).

    Returns (ok, info): info names the launcher used or explains the
    failure ("no file manager launcher found", "could not launch ...").
    """
    for name in _REVEALERS:
        if not _which(name):
            continue
        try:
            _popen([name, path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as exc:
            return False, f"could not launch {name}: {exc}"
        return True, name
    return False, "no file manager launcher found"
