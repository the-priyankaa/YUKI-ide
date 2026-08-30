"""Pick a directory using the native system folder dialog.

Tries ``zenity`` then ``kdialog``. Returns a tagged result so the caller
can distinguish a picked path from a dialog cancel from "no dialog tool".

For automated/pty testing the ``STDEDIT_PICK_FOLDER`` env var fakes the
result: ``a/path`` → that path, ``cancel`` → cancelled, anything else
(missing too) → unavailable.
"""

from __future__ import annotations

import os
import shutil
import subprocess

_TIMEOUT = 60


def choose_directory() -> tuple:
    env = os.environ.get("STDEDIT_PICK_FOLDER")
    if env is not None:
        if env == "cancel":
            return ("cancelled",)
        if os.path.isdir(env):
            return ("ok", env)
        return ("unavailable",)

    tool, args = _find_tool()
    if tool is None:
        return ("unavailable",)
    try:
        result = subprocess.run(
            args,
            capture_output=True, text=True, timeout=_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ("unavailable",)
    if result.returncode != 0:
        if result.stderr.strip():
            return ("unavailable",)
        return ("cancelled",)
    path = result.stdout.strip()
    if not os.path.isdir(path):
        return ("unavailable",)
    return ("ok", path)


def _find_tool() -> tuple[str | None, list[str]]:
    if shutil.which("zenity"):
        return "zenity", [
            "zenity", "--file-selection", "--directory",
            "--title=stdedit — Open Folder",
        ]
    if shutil.which("kdialog"):
        return "kdialog", ["kdialog", "--getexistingdirectory", "Open Folder"]
    return None, []