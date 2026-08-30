"""
main.py — CLI entry point. argparse only (stdlib), per STDLIB.md
substitution: click/typer -> argparse.

Phase 1 gate: `python -m stdedit.main somefile.py` opens the file into a
Buffer and hands it to the TUI. This alone proves open -> move -> edit ->
save -> exit end to end.
"""

from __future__ import annotations

import argparse
import os
import sys

from .buffer import Buffer
from . import tui
from .extensions import discover, extension_dirs


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stdedit",
        description="A zero-dependency terminal text editor (stdlib only).",
    )
    parser.add_argument("file", nargs="?", default=None, help="File to open")
    parser.add_argument(
        "--project",
        default=None,
        metavar="DIR",
        help="Folder the file tree is rooted at (default: opened file's parent or cwd)",
    )
    parser.add_argument(
        "--tree",
        action="store_true",
        help="Open with the file explorer tree visible and focused on the opened file",
    )
    parser.add_argument(
        "--tab-size", type=int, default=4, help="Tab width in spaces (default: 4)"
    )
    parser.add_argument(
        "--tabs",
        action="store_true",
        help="Use literal tab characters instead of spaces",
    )
    parser.add_argument(
        "--large-file-mb",
        type=int,
        default=8,
        help="Disable undo snapshots at this file size (default: 8 MB; 0 disables the safety mode)",
    )
    parser.add_argument(
        "--extension",
        action="append",
        default=[],
        metavar="NAME",
        help="Load one external extension by name (repeatable)",
    )
    parser.add_argument(
        "--extension-file",
        action="append",
        default=[],
        metavar="PATH",
        help="Load one external extension file (repeatable)",
    )
    parser.add_argument(
        "--all-extensions",
        action="store_true",
        help="Load every discovered extension (higher startup RSS)",
    )
    parser.add_argument(
        "--list-extensions",
        action="store_true",
        help="List discovered extension files and exit",
    )
    return parser


def resolve_open_targets(file_arg, project_arg):
    """Work out what to open from the command line.

    The positional argument is smart: a directory means "open this
    project" (same as --project), anything else is the file to edit.

    Returns (buffer_file, project_dir, error):
      buffer_file  -- file argument to load (may not exist yet: new file)
      project_dir  -- absolute folder for the file tree, or None
      error        -- user-facing message when the arguments conflict
    """
    project_dir = None
    if project_arg:
        candidate = os.path.abspath(os.path.expanduser(project_arg))
        if not os.path.isdir(candidate):
            return None, None, f"--project: not a directory: {project_arg}"
        project_dir = candidate

    buffer_file = None
    if file_arg:
        candidate = os.path.abspath(os.path.expanduser(file_arg))
        if os.path.isdir(candidate):
            if project_dir:
                return (
                    None,
                    None,
                    "give the project once — positionally or via --project",
                )
            project_dir = candidate
        else:
            buffer_file = file_arg
    return buffer_file, project_dir, None


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    buffer_file, project_dir, error = resolve_open_targets(args.file, args.project)
    if error:
        print(f"stdedit: {error}", file=sys.stderr)
        return 2

    if args.list_extensions:
        dirs = extension_dirs()
        print("Extension directories:")
        for directory in dirs:
            print(f"  {directory}")
        print("Discovered extensions:")
        for path in discover():
            print(f"  {path}")
        return 0

    if not sys.stdin.isatty():
        print(
            "stdedit: an interactive terminal is required "
            "(stdin is not a TTY; run inside a terminal)",
            file=sys.stderr,
        )
        return 1
    if not os.environ.get("TERM"):
        print(
            "stdedit: TERM is unset; set TERM (e.g. xterm-256color) "
            "to use the editor",
            file=sys.stderr,
        )
        return 1

    buf = Buffer(
        tab_size=args.tab_size,
        use_spaces=not args.tabs,
        large_file_threshold=max(0, args.large_file_mb) * 1024 * 1024,
    )
    if buffer_file:
        try:
            buf.load(buffer_file)
        except FileNotFoundError:
            # New file — that's fine, just remember the intended name.
            buf.filename = buffer_file
        except OSError as exc:
            print(f"stdedit: cannot open {buffer_file}: {exc}", file=sys.stderr)
            return 1

    # Extensions are opt-in so the bare editor stays lean.
    # --all-extensions keeps the old eager behavior for power users.
    if args.all_extensions:
        extension_names = None
        extension_files = None
    else:
        extension_names = args.extension
        extension_files = args.extension_file

    # Brand line before curses takes over. It flashes away on the first
    # repaint but stays in the terminal scrollback.
    print("YUKI v0.1.0 — zero-dependency terminal editor", flush=True)

    tui.run(
        buf,
        extension_names=extension_names,
        extension_files=extension_files,
        load_all_extensions=args.all_extensions,
        project_dir=project_dir,
        tree_on_start=args.tree,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
