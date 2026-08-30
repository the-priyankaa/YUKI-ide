"""install.py - 'carl' installer for the stdedit code editor.

Usage:
    carl                  install/update the editor (default command)
    carl install          same thing, idempotent
    carl uninstall [--purge]
                          remove global launchers; --purge also deletes .venv
    carl deps [--fix]     check optional OS helpers; --fix installs them
                          through the detected system package manager
    carl status           report installation health

What 'carl' does on this machine:
    1. checks Python >= 3.9
    2. creates .venv in the project root if missing
    3. pip-installs the package editable inside it
    4. symlinks every launcher (stdedit, yuki, carl) into ~/.local/bin
    5. self-checks each launcher

Standard library only.  Filesystem locations and the subprocess runner are
injectable so the whole flow can be exercised in tests without touching
the real system.
"""

import argparse
import os
import platform
import shutil
import subprocess
import sys

LAUNCHER_NAMES = ("stdedit", "yuki", "carl")
MIN_PYTHON = (3, 9)

# Cheap flag each launcher accepts, used for post-install self-checks.
PROBE_ARGS = {
    "stdedit": ("--list-extensions",),
    "yuki": ("--list-extensions",),
    "carl": ("status",),
}

# System package managers we can drive, in probe order.  Each entry is
# (manager binary, argv prefix that installs packages non-interactively).
PACKAGE_MANAGERS = (
    ("apt-get", ("sudo", "apt-get", "install", "-y")),
    ("dnf", ("sudo", "dnf", "install", "-y")),
    ("yum", ("sudo", "yum", "install", "-y")),
    ("pacman", ("sudo", "pacman", "-S", "--noconfirm")),
    ("zypper", ("sudo", "zypper", "install", "-y")),
    ("apk", ("sudo", "apk", "add")),
    ("brew", ("brew", "install")),  # macOS: never needs sudo
)


# ------------------------------------------------------------------ paths --
def project_root_from(module_file):
    """Project root lives three levels above any src/stdedit/*.py file."""
    stdedit_dir = os.path.dirname(os.path.abspath(module_file))
    return os.path.abspath(os.path.join(stdedit_dir, "..", ".."))


def get_project_root():
    return project_root_from(__file__)


def get_venv_dir(root):
    return os.path.join(root, ".venv")


def get_venv_bin(root):
    return os.path.join(get_venv_dir(root), "bin")


def get_bin_dir(home=None):
    base = home if home is not None else os.path.expanduser("~")
    return os.path.join(base, ".local", "bin")


# ----------------------------------------------------------------- checks --
def python_version_error():
    """Return a human-readable error when the interpreter is too old."""
    if sys.version_info[:2] < MIN_PYTHON:
        want = ".".join(str(n) for n in MIN_PYTHON)
        have = ".".join(str(n) for n in sys.version_info[:2])
        return f"Python {want}+ required, found {have}"
    return None


def plan_links(root, bin_dir):
    """(global_link_path, venv_target) pairs for launchers that exist."""
    links = []
    for name in LAUNCHER_NAMES:
        target = os.path.join(get_venv_bin(root), name)
        if os.path.exists(target):
            links.append((os.path.join(bin_dir, name), target))
    return links


def is_owned_link(link_path, venv_bin):
    """True when link_path is a symlink resolving inside venv_bin."""
    if not os.path.islink(link_path):
        return False
    resolved = os.path.realpath(link_path)
    return resolved == venv_bin or resolved.startswith(venv_bin + os.sep)


def self_check_ok(runner, link_path, probe=("--help",)):
    try:
        result = runner([link_path, *probe], capture_output=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return getattr(result, "returncode", 1) == 0


# ------------------------------------------------- optional OS dependencies --
def helper_specs(system=None):
    """(binary, purpose, {manager: package}) for each optional OS helper.

    The editor itself needs no packages beyond Python; these only enable
    nicer system integration and are probed with graceful fallbacks.
    """
    system = system or platform.system()
    specs = [
        ("zenity", "native folder picker for tree key O",
         {"apt-get": "zenity", "dnf": "zenity", "yum": "zenity",
          "pacman": "zenity", "zypper": "zenity", "apk": "zenity",
          "brew": "zenity"}),
        ("kdialog", "KDE folder picker for tree key O",
         {"apt-get": "kdialog", "dnf": "kdialog", "yum": "kdialog",
          "pacman": "kdialog", "zypper": "kdialog", "apk": "kdialog",
          "brew": "kdialog"}),
    ]
    if system == "Darwin":
        specs.append(("open", "reveal tree root in Finder", {}))
    else:
        specs.append(("xdg-open", "reveal tree root in the desktop's file manager",
                      {manager: "xdg-utils" for manager, _ in PACKAGE_MANAGERS
                       if manager != "brew"}))
    return specs


def detect_package_manager(_which=shutil.which):
    """First available (name, install-prefix), or None."""
    for name, prefix in PACKAGE_MANAGERS:
        if _which(name):
            return name, prefix
    return None


def cmd_deps(args, root, bin_dir, _which=shutil.which,
             _run=subprocess.run):
    error = python_version_error()
    if error:
        print(f"carl: {error}")
        return 1

    print("Python packages: none required - stdedit is standard-library "
          "only.")
    missing = []
    for binary, why, packages in helper_specs():
        if _which(binary):
            print(f"[ok]   {binary:<9} {why}")
        else:
            print(f"[miss] {binary:<9} {why}")
            missing.append((binary, why, packages))

    if not missing:
        print("all optional helpers present.")
        return 0
    if not getattr(args, "fix", False):
        print(f"{len(missing)} optional helper(s) missing - the editor "
              f"still runs.  Rerun 'carl deps --fix' to install them.")
        return 1

    manager = detect_package_manager(_which)
    if manager is None:
        print("no supported package manager found; install manually:")
        names = sorted({pkg for _, _, pkgs in missing
                        for pkg in pkgs.values()})
        print(f"  {' / '.join(names)}")
        return 1
    name, prefix = manager
    for binary, _, packages in missing:
        package = packages.get(name)
        if package is None:
            print(f"[skip] {binary}: preinstalled on this platform")
            continue
        command = [*prefix, package]
        print(f"$ {' '.join(command)}")
        try:
            result = _run(command, timeout=120)
        except (OSError, subprocess.TimeoutExpired) as exc:
            print(f"       failed: {exc}")
            continue
        rc = getattr(result, "returncode", 0)
        print(f"       {'ok' if rc == 0 else f'failed (exit {rc})'}")

    still_missing = [binary for binary, _, _ in missing if not _which(binary)]
    if still_missing:
        print(f"still missing after fix attempt: "
              f"{', '.join(still_missing)}")
        return 1
    print("all optional helpers present now.")
    return 0


# ---------------------------------------------------------------- actions --
def place_links(root, bin_dir):
    """Create/refresh global launcher symlinks; returns report lines."""
    os.makedirs(bin_dir, exist_ok=True)
    notes = []
    for link_path, target in plan_links(root, bin_dir):
        if os.path.islink(link_path):
            os.remove(link_path)
            verb = "refreshed"
        elif os.path.exists(link_path):
            notes.append(f"skip    {link_path} (regular file, left untouched)")
            continue
        else:
            verb = "created"
        os.symlink(target, link_path)
        notes.append(f"{verb} {link_path} -> {target}")
    return notes


def remove_links(root, bin_dir):
    """Delete global symlinks owned by this project; returns (removed, kept)."""
    removed, kept = [], []
    venv_bin = os.path.realpath(get_venv_bin(root))
    for name in LAUNCHER_NAMES:
        link_path = os.path.join(bin_dir, name)
        if is_owned_link(link_path, venv_bin):
            os.remove(link_path)
            removed.append(link_path)
        elif os.path.lexists(link_path):
            kept.append(f"left    {link_path} (not owned by this project)")
    return removed, kept


def cmd_install(args, root, bin_dir, runner=subprocess.run):
    error = python_version_error()
    if error:
        print(f"carl: {error}")
        return 1

    venv = get_venv_dir(root)
    if os.path.isdir(venv):
        print(f"[1/5] venv already present: {venv}")
    else:
        print(f"[1/5] creating venv: {venv}")
        try:
            result = runner([sys.executable, "-m", "venv", venv], timeout=300)
        except (OSError, subprocess.TimeoutExpired) as exc:
            print(f"carl: venv creation failed: {exc}")
            return 1
        if getattr(result, "returncode", 0) != 0:
            print(f"carl: venv creation failed "
                  f"(exit {getattr(result, 'returncode', '?')})")
            return 1

    venv_python = os.path.join(get_venv_bin(root), "python")
    print("[2/5] installing editor into venv (editable)")
    try:
        result = runner([venv_python, "-m", "pip", "install", "-e", root,
                         "--quiet"], timeout=600)
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"carl: pip install failed: {exc}")
        return 1
    if getattr(result, "returncode", 0) != 0:
        print(f"carl: pip install failed "
              f"(exit {getattr(result, 'returncode', '?')})")
        return 1

    print(f"[3/5] linking launchers into {bin_dir}")
    notes = place_links(root, bin_dir)
    if not notes or all(note.startswith("skip") for note in notes):
        print("carl: no launcher scripts found in the venv - "
              "was step 2 successful?")
        return 1
    for note in notes:
        print(f"      {note}")

    print("[4/5] self-check")
    failures = []
    for name in LAUNCHER_NAMES:
        link_path = os.path.join(bin_dir, name)
        if not os.path.exists(link_path):
            continue
        ok = self_check_ok(runner, link_path,
                           PROBE_ARGS.get(name, ("--help",)))
        print(f"      [{'ok' if ok else 'FAIL'}] {link_path}")
        if not ok:
            failures.append(link_path)
    if failures:
        print(f"carl: {len(failures)} launcher(s) failed self-check")
        return 1

    print("[5/5] done.  Launch the editor with any of:")
    for name in LAUNCHER_NAMES:
        print(f"      {name} path/to/project_or_file")
    return 0


def cmd_uninstall(args, root, bin_dir):
    removed, kept = remove_links(root, bin_dir)
    for path in removed:
        print(f"removed {path}")
    for note in kept:
        print(note)
    if getattr(args, "purge", False) and os.path.isdir(get_venv_dir(root)):
        shutil.rmtree(get_venv_dir(root))
        print(f"purged  {get_venv_dir(root)}")
    print(f"done ({len(removed)} launcher(s) removed)")
    return 0


def cmd_status(args, root, bin_dir):
    error = python_version_error()
    version = ".".join(str(n) for n in sys.version_info[:3])
    print(f"python : {'OK' if not error else error} ({version})")

    venv = get_venv_dir(root)
    venv_bin = get_venv_bin(root)
    print(f"venv   : {'present' if os.path.isdir(venv) else 'missing'} "
          f"({venv})")

    present = [n for n in LAUNCHER_NAMES
               if os.path.exists(os.path.join(venv_bin, n))]
    print(f"scripts: {', '.join(present) if present else '(none found)'}")

    resolved_venv_bin = os.path.realpath(venv_bin)
    for name in LAUNCHER_NAMES:
        link_path = os.path.join(bin_dir, name)
        if is_owned_link(link_path, resolved_venv_bin):
            state = f"linked -> {os.readlink(link_path)}"
        elif os.path.islink(link_path):
            state = ("foreign -> " + os.readlink(link_path))
        elif os.path.exists(link_path):
            state = "regular file"
        else:
            state = "missing"
        print(f"{name:7s}: {state}")
    return 0


# ------------------------------------------------------------------- cli --
def build_parser():
    parser = argparse.ArgumentParser(
        prog="carl",
        description="Install or remove the stdedit code editor.")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("install", help="install/update the editor (default)")
    uninstall = sub.add_parser("uninstall",
                               help="remove global launcher symlinks")
    uninstall.add_argument("--purge", action="store_true",
                           help="also delete the project's .venv")
    deps = sub.add_parser(
        "deps", help="check/install optional OS helpers "
                     "(zenity, kdialog, xdg-open)")
    deps.add_argument("--fix", action="store_true",
                      help="install missing helpers via the system "
                           "package manager")
    sub.add_parser("status", help="show installation status")
    return parser


def main(argv=None, _root=None, _bin_dir=None, _run=subprocess.run,
         _which=shutil.which):
    args = build_parser().parse_args(argv)
    root = os.path.abspath(_root or get_project_root())
    bin_dir = _bin_dir or get_bin_dir()
    command = args.command or "install"
    if command == "install":
        return cmd_install(args, root, bin_dir, runner=_run)
    if command == "uninstall":
        return cmd_uninstall(args, root, bin_dir)
    if command == "deps":
        return cmd_deps(args, root, bin_dir, _which=_which, _run=_run)
    return cmd_status(args, root, bin_dir)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
