"""runner.py — run the current file in an external terminal.

``run_file()`` picks a terminal emulator the way ``filemanager.py`` picks a
folder picker (first installed wins), builds a language-appropriate command
from the file extension, and launches a detached ``bash -c`` script in that
terminal.  Only the Python standard library is imported (shutil, subprocess,
shlex, tempfile); the runtimes and the terminal are optional binaries that
must already be on the system.

The spawned terminal is decorated: the window title is set to
``YUKI — run <file>``, a small indented header names the file and
interpreter, and the program output flows through unchanged (plain
passthrough, no framing, no wrapping), so lines and ANSI colors appear
exactly as the program writes them.  A blank line separates the start of
execution from the header.  Each run finishes on a plain summary line
showing the exit code plus further actions (``r`` rerun, ``Enter`` close);
``r`` reruns in place while any other key closes the window.  When
util-linux ``script`` is available the program runs on a pseudo-terminal, so
``print`` output streams live for every language instead of collecting in a
block buffer.  Web sources (``.html``, ``.htm``, ``.xhtml``, ``.svg``,
``.md``, ``.markdown``) are served instead of executed: a local dev server
starts in the terminal and the default browser opens the page.  Images
(``.png``, ``.jpg``, ``.gif``, and friends) are handed straight to the
default browser via ``open_in_browser()`` — no terminal or server involved.
Decoration
can be tuned per run:

  ``STDEDIT_RUN_RAW=1``  plain script, no title/header/colors (test hook)
  ``NO_COLOR``           keep the header and title, drop ANSI colors
  ``STDEDIT_ICONS=0``    omit the file icon (matches the editor)

``STDEDIT_TERMINAL`` overrides terminal detection (a command name),
mirroring the ``STDEDIT_FAKE_GHOST`` / ``STDEDIT_PICK_FOLDER`` test hooks:
point it at a script that records argv for end-to-end checks.
"""

from __future__ import annotations

import os
import shlex
import shutil
import socket
import subprocess
import tempfile
import urllib.parse
from typing import Callable, List, Optional, Tuple

from . import icons

# Width knob for the header/summary layout.  The passthrough output is not
# wrapped or framed, so this only reserves headroom for future boxed layouts.
_STDEDIT_RUN_WIDTH = 70

_STDEDIT_TERMINAL_ENV = "STDEDIT_TERMINAL"
_STDEDIT_RUN_RAW_ENV = "STDEDIT_RUN_RAW"
_NO_COLOR_ENV = "NO_COLOR"

_TERMINAL_LAUNCHERS: List[Tuple[str, List[str]]] = [
    ("kitty", ["kitty", "-e"]),
    ("gnome-terminal", ["gnome-terminal", "--"]),
    ("konsole", ["konsole", "-e"]),
    ("xfce4-terminal", ["xfce4-terminal", "-x"]),
    ("alacritty", ["alacritty", "-e"]),
    ("foot", ["foot", "-e"]),
    ("wezterm", ["wezterm", "start", "--"]),
    ("mate-terminal", ["mate-terminal", "-x"]),
    ("tilix", ["tilix", "-e"]),
    ("terminator", ["terminator", "-x"]),
    ("xterm", ["xterm", "-e"]),
    ("uxterm", ["uxterm", "-e"]),
    ("urxvt", ["urxvt", "-e"]),
    ("x-terminal-emulator", ["x-terminal-emulator", "-e"]),
]

# Extension -> (runtime executable, command template).
# "{path}" is the quoted absolute file path; "{out}" is a per-run temp binary
# (used by compiled languages, removed by the wrapper script).
_RUNTIMES = {
    ".py":    ("python3", "python3 -u {path}"),
    ".pyw":   ("python3", "python3 -u {path}"),
    ".js":    ("node", "node {path}"),
    ".mjs":   ("node", "node {path}"),
    ".jsx":   ("npx", "npx --yes tsx {path}"),
    ".ts":    ("npx", "npx --yes tsx {path}"),
    ".tsx":   ("npx", "npx --yes tsx {path}"),
    ".java":  ("java", "java {path}"),
    ".c":     ("gcc", "gcc {path} -o {out} && {out}"),
    ".h":     ("gcc", "gcc {path} -o {out} && {out}"),
    ".cpp":   ("g++", "g++ {path} -o {out} && {out}"),
    ".cc":    ("g++", "g++ {path} -o {out} && {out}"),
    ".cxx":   ("g++", "g++ {path} -o {out} && {out}"),
    ".C":     ("g++", "g++ {path} -o {out} && {out}"),
    ".rs":    ("rustc", "rustc {path} -o {out} && {out}"),
    ".go":    ("go", "go run {path}"),
    ".sh":    ("bash", "bash {path}"),
    ".bash":  ("bash", "bash {path}"),
    ".zsh":   ("zsh", "zsh {path}"),
    ".pl":    ("perl", "PERLIO=:unix perl {path}"),
    ".rb":    ("ruby", "ruby {path}"),
    ".php":   ("php", "php {path}"),
    ".lua":   ("lua", "lua {path}"),
    ".r":     ("Rscript", "Rscript {path}"),
    ".R":     ("Rscript", "Rscript {path}"),
}

# Fallback: run with whatever POSIX shell is available.
_SHELL_FALLBACKS = ("bash", "zsh", "sh")

# Extensions with no executable to run (web sources are served instead).
_NON_RUNNABLE = frozenset({".css", ".scss", ".sass", ".json", ".yaml",
                           ".yml", ".sql", ".xml", ".txt"})

# Web sources: running one starts a local dev server and opens the default
# browser instead of executing it in a terminal.
_WEB_EXT = frozenset({".html", ".htm", ".xhtml", ".svg", ".md", ".markdown"})

# Images: running (or opening) one just hands the file to the default
# browser via the platform opener — no terminal, no dev server.
_IMAGE_EXT = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp",
                        ".ico", ".tif", ".tiff", ".heic", ".heif", ".avif",
                        ".ppm", ".pgm", ".pbm"})

# Browser openers, most portable first (mirrors filemanager._REVEALERS).
_BROWSER_OPENERS = ("xdg-open", "open")

# Display names for the run header, keyed by the runtime executable.
_RUNTIME_LABELS = {
    "python": "Python",
    "python3": "Python 3",
    "node": "Node.js",
    "npx": "TypeScript (tsx)",
    "java": "Java",
    "gcc": "C (gcc)",
    "g++": "C++ (g++)",
    "rustc": "Rust",
    "go": "Go",
    "bash": "Shell (bash)",
    "sh": "Shell (sh)",
    "zsh": "Shell (zsh)",
    "perl": "Perl",
    "ruby": "Ruby",
    "php": "PHP",
    "lua": "Lua",
    "luajit": "Lua (luajit)",
    "Rscript": "R",
    "dotnet": ".NET",
    "mono": "C# (mono)",
    "kotlin": "Kotlin",
    "swift": "Swift",
}


def terminal_launcher(
    _which: Callable[[str], Optional[str]] = shutil.which,
    env: dict | None = None,
) -> Optional[List[str]]:
    """Return the argv prefix for the best available terminal, or None."""
    environ = env if env is not None else os.environ
    forced = environ.get(_STDEDIT_TERMINAL_ENV)
    if forced:
        name = forced.split()[0]
        rest = forced.split()[1:]
        candidate = [name] + rest
        if _which(name):
            return candidate
        return None
    for name, prefix in _TERMINAL_LAUNCHERS:
        if _which(name):
            return list(prefix)
    return None


def _runtime_for(ext: str) -> Optional[Tuple[str, str]]:
    return _RUNTIMES.get(ext)


def run_command_for(
    path: str,
    _which: Callable[[str], Optional[str]] = shutil.which,
) -> Tuple[Optional[str], str]:
    """Return (shell_command, display) or (None, reason) for *path*."""
    ext = _os_ext(path)
    if not ext:
        return None, f"No runner for {ext_label(path)}"
    if ext in _WEB_EXT:
        return None, f"Opens {ext} in a browser via a local server"
    if ext in _IMAGE_EXT:
        return None, f"Opens {ext} in the default browser"
    if ext in _NON_RUNNABLE:
        return None, f"No run command for {ext}"
    spec = _runtime_for(ext)
    if spec is None:
        return None, f"No runner for {ext}"
    runtime, template = spec
    if runtime == "bash" and not _which("bash"):
        chosen = next((s for s in _SHELL_FALLBACKS if _which(s)), None)
        if chosen is None:
            return None, f"Runtime '{runtime}' not found for {ext}"
        runtime = chosen
        spec = (runtime, f"{runtime} {{path}}")
        template = spec[1]
    if not _which(runtime):
        return None, f"Runtime '{runtime}' not found for {ext}"
    quoted = shlex.quote(os.path.abspath(path))
    return (template.format(path=quoted, out=_temp_out()),
            f"{runtime} {path}")


def _pick_free_port() -> int:
    """Pick an ephemeral TCP port on loopback that is free right now."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _web_command(
    path: str,
    port: int,
    _which: Callable[[str], Optional[str]] = shutil.which,
) -> Tuple[Optional[str], str]:
    """Build the bash *command* that serves *path* on a local dev server.

    The command starts ``python3 -m http.server`` (stdlib) in the background
    serving the file's directory, polls the port until it accepts
    connections, opens the page in the default browser (``xdg-open`` or
    ``open``), then waits on the server so the terminal stays alive showing
    its access log.  Ctrl-C stops the server and returns 130 instead of
    killing the whole script, so the usual summary line still appears.  The
    whole flow is one bash line so the run loop can append its own ``; }``
    terminator.  Returns ``(command, opener)`` or ``(None, reason)`` when no
    browser opener is installed.
    """
    opener = next((name for name in _BROWSER_OPENERS if _which(name)), None)
    if opener is None:
        return None, "no browser opener found"
    directory = os.path.dirname(os.path.abspath(path))
    base = os.path.basename(path)
    url = f"http://127.0.0.1:{port}/{urllib.parse.quote(base)}"
    server = shlex.quote(directory)
    return (
        "trap 'kill $server_pid 2>/dev/null' INT; "
        f"python3 -m http.server --bind 127.0.0.1 {port} "
        f"--directory {server} & server_pid=$!; "
        f"for _ in $(seq 1 100); do "
        f"if : >/dev/tcp/127.0.0.1/{port} 2>/dev/null; then break; fi; "
        f"sleep 0.05; done; "
        f"{opener} {shlex.quote(url)}; "
        f"wait $server_pid; trap - INT"
    ), opener


def run_file(
    path: str,
    _which: Callable[[str], Optional[str]] = shutil.which,
    _popen: Callable[..., object] = subprocess.Popen,
    env: dict | None = None,
    pty: Optional[bool] = None,
) -> Tuple[bool, str]:
    """Open *path* in an external terminal and run it.

    Web sources (``.html``, ``.htm``, ``.xhtml``, ``.svg``, ``.md``,
    ``.markdown``) are served instead: a local dev server starts in the
    terminal and the default browser opens the page.  Returns (ok, status):
    on success status names the interpreter and the terminal used; on failure
    it explains why (no terminal, no runtime, no runner, launch error).
    ``pty`` (True/False/None) pins whether the run gets a pseudo-terminal;
    None auto-detects util-linux ``script``.
    """
    if not path:
        return False, "Nothing to run"
    ext = _os_ext(path)
    if ext in _IMAGE_EXT:
        return open_in_browser(path, _which=_which, _popen=_popen)
    launcher = terminal_launcher(_which=_which, env=env)
    if launcher is None:
        return False, "No terminal emulator found (install kitty, gnome-terminal, ...)"
    environ = env if env is not None else os.environ
    raw = environ.get(_STDEDIT_RUN_RAW_ENV) == "1"
    colors = not raw and _NO_COLOR_ENV not in environ
    glyph = icons.icon_for_file(path, icons.enabled_from_env(environ))
    if ext in _WEB_EXT:
        base = os.path.basename(path) or path
        port = _pick_free_port()
        command, opener = _web_command(path, port, _which=_which)
        if command is None:
            return False, opener
        display = f"http://127.0.0.1:{port}/{urllib.parse.quote(base)}"
        script = _build_script(path, command, runtime="", icon=glyph,
                               raw=raw, colors=colors, pty=False)
        return _launch(display, launcher, script, _popen=_popen)
    command, display = run_command_for(path, _which=_which)
    if command is None:
        return False, display
    runtime = display.split(None, 1)[0] if display else ""
    script = _build_script(path, command, runtime=runtime, icon=glyph,
                           raw=raw, colors=colors, pty=pty)
    return _launch(display, launcher, script, _popen=_popen)


def _launch(
    display: str,
    launcher: List[str],
    script: str,
    _popen: Callable[..., object] = subprocess.Popen,
) -> Tuple[bool, str]:
    """Launch *script* in the *launcher* terminal; return (ok, status)."""
    argv = launcher + ["bash", "-c", script]
    try:
        _popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
               start_new_session=True)
    except OSError as exc:
        return False, f"Could not launch terminal: {exc}"
    emulator = launcher[0].split("/")[-1]
    return True, f"Running: {display} ({emulator})"


def open_in_browser(
    path: str,
    _which: Callable[[str], Optional[str]] = shutil.which,
    _popen: Callable[..., object] = subprocess.Popen,
) -> Tuple[bool, str]:
    """Open *path* in the default browser without blocking.

    The file is handed to the platform opener (``xdg-open`` or ``open``) so
    the browser renders it directly; a static asset doesn't need a terminal
    or a dev server.  Returns (ok, status): on success status names the
    opener used; on failure it explains why (no opener, launch error).
    """
    opener = next((name for name in _BROWSER_OPENERS if _which(name)), None)
    if opener is None:
        return False, "no browser opener found"
    try:
        _popen([opener, os.path.abspath(path)],
               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
               start_new_session=True)
    except OSError as exc:
        return False, f"Could not open in browser: {exc}"
    return True, f"Opening: {os.path.basename(path) or path} ({opener})"


def _runtime_label(runtime: str) -> str:
    return _RUNTIME_LABELS.get(runtime, runtime)


def _sanitize(text: str) -> str:
    """Strip control characters from a window title."""
    return "".join(ch for ch in text if ch >= " " and ch != "\x7f")


def _bash_squote(text: str) -> str:
    return "'" + text.replace("'", "'\\''") + "'"


SCRIPT_SUPPORTED: Optional[bool] = None


def _script_supported(
    _which: Callable[[str], Optional[str]] = shutil.which,
    _run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> bool:
    """True when a util-linux ``script`` is available for pty runs.

    The result is cached: running under a fake pty makes every language's
    stdout a real tty, so ``print`` output streams line-by-line instead of
    disappearing in a block buffer until exit.  Busybox variants are rejected
    because they lack ``-q``/``-e``.
    """
    global SCRIPT_SUPPORTED
    if SCRIPT_SUPPORTED is not None:
        return SCRIPT_SUPPORTED
    exe = _which("script")
    if exe is None:
        SCRIPT_SUPPORTED = False
        return False
    try:
        result = _run([exe, "--version"], capture_output=True,
                      text=True, timeout=2)
        SCRIPT_SUPPORTED = "util-linux" in (result.stdout or "").lower()
    except (OSError, ValueError):
        SCRIPT_SUPPORTED = False
    return SCRIPT_SUPPORTED


def _pty_wrap(command: str) -> str:
    """Prefix *command* so it runs on a pseudo-terminal (``script -qec``)."""
    return f"script -qec {_bash_squote(command)} /dev/null"


def _run_loop_block(colors: bool, run_elem: str) -> str:
    """Bash lines for the run loop (header already printed once).

    Each iteration begins on a blank line, so the program output always
    starts on a fresh row underneath the header.  The program streams
    verbatim (stderr merged), then the loop closes on a plain summary line
    showing the exit code and the further actions (``r`` rerun, Enter/any
    key closes).  Pressing ``r`` selects the rerun branch; any other key
    breaks out of the loop and the window closes.  ``run_elem`` is the
    pty-wrapped or plain command.
    """
    def _summary(mark: str) -> str:
        return ("_line "
                + _bash_squote(f"  stdedit — {mark} finished (exit ")
                + '"$rc"'
                + _bash_squote(") — [r] rerun · [Enter] close")
                + "\n")
    if colors:
        ok = ("printf '\\x1b[32m'; " + _summary("✔") + "printf '\\x1b[0m'\n")
        fail = ("printf '\\x1b[31m'; " + _summary("✖") + "printf '\\x1b[0m'\n")
    else:
        ok = _summary("✔")
        fail = _summary("✖")
    status = (
        "  if [ \"$rc\" -eq 0 ]; then\n"
        f"    {ok}"
        "  else\n"
        f"    {fail}"
        "  fi\n"
    )
    return (
        "_line() { printf '%s\\n' \"$1\"; }\n"
        "while true; do\n"
        "  echo\n"
        f"  {{ {run_elem}; }} 2>&1\n"
        "  rc=$?\n"
        "  echo\n"
        + status
        + "  read -n 1 -s -r k || break\n"
        + '  case "$k" in\n'
        + "    r|R) continue ;;\n"
        + "    *) break ;;\n"
        + "  esac\n"
        + "done\n"
    )


def _build_script(path: str, command: str, runtime: str = "", icon: str = "",
                  raw: bool = False, colors: bool = True,
                  width: int = _STDEDIT_RUN_WIDTH,
                  pty: Optional[bool] = None) -> str:
    """Build the ``bash -c`` payload for *path* and *command*.

    With ``raw=False`` the script sets the terminal window title, prints a
    small indented header naming the file and interpreter, and streams the
    program output through unchanged (plain passthrough — no framing, no
    wrapping).  Each run starts on a blank line and closes on a plain summary
    line showing the exit code and further actions (``r`` rerun, Enter/any
    key closes).  When ``pty`` is unset the program runs on a
    pseudo-terminal when util-linux ``script`` is present (live output for
    every language); ``pty=False`` forces the plain run (with unbuffered
    runtimes), ``pty=True`` forces the pty wrapper.  ``raw=True`` returns
    the plain script (no decoration); ``colors=False`` keeps the header and
    title but emits no ANSI SGR colors.
    """
    quoted = shlex.quote(os.path.abspath(path))
    out = _temp_out()
    plain = (
        f'cd "$(dirname -- {quoted})" 2>/dev/null\n'
        f"{command}\n"
        "rc=$?\n"
        f"trap 'rm -f {out} 2>/dev/null' EXIT\n"
        "echo\n"
        'echo "[YUKI] finished (exit $rc) — press Enter to close"\n'
        "read -r _\n"
    )
    if raw:
        return plain
    use_pty = _script_supported() if pty is None else bool(pty)
    run_elem = _pty_wrap(command) if use_pty else command
    label = _runtime_label(runtime)
    base = _sanitize(os.path.basename(path) or path)
    title_text = f"YUKI — run {base}"
    if runtime:
        title_text += f" ({label})"
    title = ("printf '\\033]0;%s\\007' '"
             + title_text.replace("'", "'\\''") + "'\n")
    head = f"  stdedit · run {base}"
    if icon:
        head = f"  stdedit · run {icon} {base}"
    if runtime:
        head += f" ({label})"
    return (
        title
        + f'cd "$(dirname -- {quoted})" 2>/dev/null\n'
        + f"trap 'rm -f {out} 2>/dev/null' EXIT\n"
        + f"printf '%s\\n' {_bash_squote(head)}\n"
        + _run_loop_block(colors, run_elem)
    )


def _temp_out() -> str:
    return os.path.join(tempfile.gettempdir(), f"stdedit-run-{os.getpid()}")


def _os_ext(path: str) -> str:
    base = os.path.basename(path)
    dot = base.rfind(".")
    if dot <= 0:
        return ""
    return base[dot:]


def ext_label(path: str) -> str:
    ext = _os_ext(path)
    return ext if ext else path