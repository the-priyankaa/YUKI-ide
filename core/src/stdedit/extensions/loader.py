"""Low-overhead external extension discovery and loading.

Extensions are *discovered* cheaply but are not imported unless explicitly
requested. This keeps the base editor's RSS low: a directory containing 50
extensions does not mean 50 Python modules are loaded at startup.

Search order:
  1. STDEDIT_EXTENSIONS (os.pathsep-separated directories)
  2. .stdedit/extensions in the current working directory
  3. ~/.config/stdedit/extensions

An extension is a normal Python file exposing ``setup(api)`` or ``register(api)``.
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from typing import List, Optional, Tuple

from .api import ExtensionAPI


def extension_dirs(cwd: Optional[str] = None) -> List[Path]:
    cwd_path = Path(cwd or os.getcwd())
    result: List[Path] = []
    env = os.environ.get("STDEDIT_EXTENSIONS", "")
    if env:
        result.extend(Path(p).expanduser() for p in env.split(os.pathsep) if p)
    result.append(cwd_path / ".stdedit" / "extensions")
    result.append(Path.home() / ".config" / "stdedit" / "extensions")
    seen = set()
    unique = []
    for path in result:
        key = str(path.resolve()) if path.exists() else str(path.absolute())
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def discover(cwd: Optional[str] = None) -> List[Path]:
    """Find extension files without importing them."""
    files: List[Path] = []
    seen = set()
    for directory in extension_dirs(cwd):
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.py")):
            if path.name.startswith("_"):
                continue
            key = str(path.resolve())
            if key not in seen:
                seen.add(key)
                files.append(path)
    return files


def _module_name(path: Path) -> str:
    # Avoid keeping a deterministic module name collision across two copies
    # of an extension with the same filename.
    return f"stdedit_ext_{abs(hash(str(path.resolve()))):x}"


def load_extension_path(api: ExtensionAPI, path: Path) -> Tuple[Optional[str], Optional[Tuple[str, str]]]:
    """Import exactly one extension file and isolate any extension failure."""
    path = Path(path).expanduser().resolve()
    try:
        if not path.is_file():
            raise FileNotFoundError(str(path))
        spec = importlib.util.spec_from_file_location(_module_name(path), path)
        if spec is None or spec.loader is None:
            raise ImportError("could not create module loader")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        setup = getattr(module, "setup", None) or getattr(module, "register", None)
        if setup is None:
            raise AttributeError("extension must define setup(api) or register(api)")
        setup(api)
        return path.stem, None
    except Exception as exc:  # external code must not kill the editor
        return None, (path.name, f"{type(exc).__name__}: {exc}")


def resolve_extension(name: str, cwd: Optional[str] = None) -> Optional[Path]:
    """Resolve an extension by filename/stem without importing it."""
    wanted = Path(name).expanduser()
    if wanted.suffix == ".py" and wanted.is_file():
        return wanted.resolve()
    if wanted.is_absolute() and wanted.is_file():
        return wanted.resolve()
    for path in discover(cwd):
        if path.stem == name or path.name == name:
            return path
    return None


def load_requested_extensions(
    api: ExtensionAPI,
    names: List[str],
    files: List[str],
    cwd: Optional[str] = None,
) -> Tuple[List[str], List[Tuple[str, str]]]:
    """Load only extensions explicitly requested by the user."""
    loaded: List[str] = []
    errors: List[Tuple[str, str]] = []
    paths: List[Path] = []
    for name in names:
        path = resolve_extension(name, cwd)
        if path is None:
            errors.append((name, "FileNotFoundError: extension not found"))
        else:
            paths.append(path)
    paths.extend(Path(p).expanduser() for p in files)

    seen = set()
    for path in paths:
        key = str(path.resolve())
        if key in seen:
            continue
        seen.add(key)
        ext_name, error = load_extension_path(api, path)
        if ext_name is not None:
            loaded.append(ext_name)
        if error is not None:
            errors.append(error)
    return loaded, errors


def load_extensions(api: ExtensionAPI, cwd: Optional[str] = None) -> Tuple[List[str], List[Tuple[str, str]]]:
    """Compatibility helper: eagerly load every discovered extension.

    Prefer ``load_requested_extensions`` for normal editor startup because it
    avoids importing unused extensions and therefore keeps RSS lower.
    """
    paths = discover(cwd)
    loaded: List[str] = []
    errors: List[Tuple[str, str]] = []
    for path in paths:
        ext_name, error = load_extension_path(api, path)
        if ext_name is not None:
            loaded.append(ext_name)
        if error is not None:
            errors.append(error)
    return loaded, errors
