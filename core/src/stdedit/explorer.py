"""
explorer.py — file tree explorer panel. stdlib only.

Features:
  - Tree rooted at any directory (set_root), normally the opened file's
    parent folder.
  - "<..>" entry to climb to the parent directory while keeping the
    expansion state of previously visited subdirectories.
  - Hidden files/dirs are filtered by default; `show_hidden` flips that.
  - Tracks the currently open file so the TUI can highlight it.
"""

from __future__ import annotations

import os
from typing import List, Optional, Set, Tuple

# Sentinel path used for the parent-directory pseudo entry.
PARENT = ".."

Item = Tuple[int, str, str, bool]  # depth, display_name, absolute_path, is_dir


class FileExplorer:
    # Never rendered, even when show_hidden is on: IDE metadata, VCS
    # internals, dependency directories, caches and build outputs.
    # Only working project files belong in the tree.
    ALWAYS_IGNORED_NAMES = {
        ".git", ".idea", ".vscode", ".DS_Store",
        "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
        ".tox", ".eggs",
        "venv", ".venv", "env",
        "node_modules",
        "build", "dist",
    }
    # Suffix-based junk: packaged metadata and compiled bytecode.
    ALWAYS_IGNORED_SUFFIXES = (".egg-info", ".pyc")

    def __init__(self, root_dir: str = ".") -> None:
        self.root_dir = os.path.abspath(root_dir)
        self.expanded_dirs: Set[str] = {self.root_dir}
        # Flattened visible items: (depth, display_name, absolute_path, is_dir).
        # The parent pseudo entry uses the literal ".." path.
        self.items: List[Item] = []
        self.selected_idx = 0
        # The tree is part of the default layout: shown and focused on
        # launch. Esc/Tab moves focus to the editor; Ctrl-E hides the panel.
        self.visible = True
        self.active = True
        self.show_hidden = False
        self.current_path: Optional[str] = None
        # Search mode state.
        self.searching = False
        self.search_query: str = ""
        self.search_results: List[Item] = []
        self.refresh()

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def set_root(self, path: str) -> None:
        """Re-root the tree (e.g. at the opened file's parent folder)."""
        path = os.path.abspath(path)
        if not os.path.isdir(path):
            return
        self.root_dir = path
        self.expanded_dirs.add(path)
        self.selected_idx = 0
        self.refresh()

    def can_go_up(self) -> bool:
        """True unless we are already at the filesystem root."""
        return os.path.dirname(self.root_dir) != self.root_dir

    def go_up(self) -> None:
        """Climb one directory level, selecting the folder we came from."""
        if not self.can_go_up():
            return
        old_root = self.root_dir
        self.root_dir = os.path.dirname(old_root)
        self.expanded_dirs.add(self.root_dir)
        self.refresh()
        # Put the cursor on the directory we just climbed out of.
        for i, (_, _, path, is_dir) in enumerate(self.items):
            if is_dir and path == old_root:
                self.selected_idx = i
                break

    def toggle_hidden(self) -> None:
        self.show_hidden = not self.show_hidden
        if not self.searching:
            self.refresh()

    # ------------------------------------------------------------------ #
    # Search
    # ------------------------------------------------------------------ #
    def enter_search(self) -> None:
        """Activate search mode with an empty query."""
        self.searching = True
        self.search_query = ""
        self.search_results = []
        self.selected_idx = 0

    def exit_search(self) -> None:
        """Deactivate search and restore the normal tree view."""
        self.searching = False
        self.search_query = ""
        self.search_results = []
        self.refresh()

    def search(self, query: str) -> None:
        """Walk the entire tree and collect items matching *query*.

        Case-insensitive substring match on file/dir names.  Results are
        shown as a flat list (depth=0) regardless of where they live in
        the tree.  Respects ``_is_visible`` and the always-ignored sets.
        """
        self.search_query = query
        if not query:
            self.search_results = []
            self.selected_idx = 0
            return
        q = query.lower()
        results: List[Item] = []
        self._search_walk(self.root_dir, q, results)
        self.search_results = results
        self.selected_idx = 0 if results else 0

    def _search_walk(self, directory: str, query: str, results: List[Item]) -> None:
        """Recursively walk *directory* collecting matches into *results*."""
        try:
            entries = os.listdir(directory)
        except OSError:
            return
        for name in sorted(entries, key=str.lower):
            if not self._is_visible(name):
                continue
            full_path = os.path.join(directory, name)
            is_dir = os.path.isdir(full_path)
            if query in name.lower():
                display = ("▶ " + name) if is_dir else ("  " + name)
                results.append((0, display, full_path, is_dir))
            if is_dir:
                self._search_walk(full_path, query, results)

    def refresh(self) -> None:
        """Walk the directory tree and rebuild the flat list of visible items."""
        if self.searching:
            return  # search results are managed by search()
        self.items = []
        if self.can_go_up():
            self.items.append((0, PARENT, PARENT, False))
        self._build_tree(self.root_dir, 0)
        if not self.items:
            self.selected_idx = 0
        else:
            self.selected_idx = min(self.selected_idx, len(self.items) - 1)

    def toggle_expand(self, idx: int) -> None:
        """Toggle expansion of the directory at the given index."""
        if 0 <= idx < len(self.items):
            _, _, path, is_dir = self.items[idx]
            if is_dir:
                if path in self.expanded_dirs:
                    self.expanded_dirs.remove(path)
                else:
                    self.expanded_dirs.add(path)
                self.refresh()

    def get_selected(self) -> Optional[Item]:
        """Return the currently selected item."""
        source = self.search_results if self.searching else self.items
        if 0 <= self.selected_idx < len(source):
            return source[self.selected_idx]
        return None

    def move_selection(self, dy: int) -> None:
        """Move the selection up or down, clamped to the list bounds."""
        source = self.search_results if self.searching else self.items
        if source:
            self.selected_idx = max(0, min(len(source) - 1, self.selected_idx + dy))

    def reveal(self, path: str) -> None:
        """Expand the tree and select *path* so it is visible and highlighted.

        Ancestors up to ``root_dir`` are expanded first (the tree only lists
        items whose parent folders are expanded), then the exact row for
        *path* is selected.  Safe when *path* is missing or outside the tree:
        the tree is just left refreshed on its current selection.
        """
        path = os.path.abspath(path)
        if not os.path.exists(path):
            return
        if self.searching:
            self.exit_search()
        parent = os.path.dirname(path)
        while parent and parent != self.root_dir and parent.startswith(self.root_dir):
            self.expanded_dirs.add(parent)
            parent = os.path.dirname(parent)
        self.refresh()
        for i, item in enumerate(self.items):
            if item[2] == path:
                self.selected_idx = i
                break

    # ------------------------------------------------------------------ #
    # Creation
    # ------------------------------------------------------------------ #
    def selected_directory(self) -> str:
        """Directory where new entries created from the tree are placed.

        A selected directory receives the entry inside itself; a selected
        file gets it as a sibling; `<..>` or an empty tree falls back to
        the tree root.
        """
        selected = self.get_selected()
        if not selected:
            return self.root_dir
        _, _, path, is_dir = selected
        if path == PARENT:
            return self.root_dir
        if is_dir:
            return path
        return os.path.dirname(path)

    @staticmethod
    def _validate_entry_name(name: str) -> Optional[str]:
        """Return an error message for an invalid entry name, else None."""
        if not name:
            return "Name cannot be empty"
        if name in (".", ".."):
            return f"Invalid name: {name}"
        seps = {os.sep}
        if os.altsep:
            seps.add(os.altsep)
        if "/" in name or any(sep in name for sep in seps):
            return "Name must be a single path component"
        return None

    def _select_path(self, path: str) -> None:
        for i, item in enumerate(self.items):
            if item[2] == path:
                self.selected_idx = i
                return

    def create_file(self, name: str) -> Tuple[str, Optional[str]]:
        """Create an empty file in the target directory.

        Returns (path, error). On success the parent folder is expanded,
        the tree refreshed and the new file selected.
        """
        name = name.strip()
        error = self._validate_entry_name(name)
        if error:
            return "", error
        base = self.selected_directory()
        path = os.path.join(base, name)
        try:
            with open(path, "x"):
                pass
        except FileExistsError:
            return path, f"'{name}' already exists"
        except OSError as exc:
            return path, f"Cannot create file: {exc}"
        self.expanded_dirs.add(base)
        self.refresh()
        self._select_path(path)
        return path, None

    def create_folder(self, name: str) -> Tuple[str, Optional[str]]:
        """Create a directory in the target directory.

        Returns (path, error). On success the new folder is expanded and
        selected.
        """
        name = name.strip()
        error = self._validate_entry_name(name)
        if error:
            return "", error
        base = self.selected_directory()
        path = os.path.join(base, name)
        try:
            os.mkdir(path)
        except FileExistsError:
            return path, f"'{name}' already exists"
        except OSError as exc:
            return path, f"Cannot create folder: {exc}"
        self.expanded_dirs.add(path)
        self.refresh()
        self._select_path(path)
        return path, None

    # ------------------------------------------------------------------ #
    # File operations (delete, rename, copy path)
    # ------------------------------------------------------------------ #

    def delete_selected(self) -> tuple[bool, str]:
        """Delete the selected file or folder.

        Returns ``(ok, message)`` where *ok* is True on success.
        """
        item = self.get_selected()
        if not item:
            return False, "No item selected"
        _, _, path, is_dir = item
        if path == PARENT:
            return False, "Cannot delete parent entry"
        try:
            if is_dir:
                import shutil
                shutil.rmtree(path)
            else:
                os.remove(path)
        except OSError as exc:
            return False, f"Delete failed: {exc}"
        self.refresh()
        return True, f"Deleted {os.path.basename(path)}"

    def rename_selected(self, new_name: str) -> tuple[bool, str]:
        """Rename the selected item to *new_name*.

        Returns ``(ok, message)`` where *ok* is True on success.
        """
        item = self.get_selected()
        if not item:
            return False, "No item selected"
        _, _, path, is_dir = item
        if path == PARENT:
            return False, "Cannot rename parent entry"
        err = self._validate_entry_name(new_name)
        if err:
            return False, err
        parent = os.path.dirname(path)
        new_path = os.path.join(parent, new_name)
        if os.path.exists(new_path):
            return False, f"'{new_name}' already exists"
        try:
            os.rename(path, new_path)
        except OSError as exc:
            return False, f"Rename failed: {exc}"
        self.refresh()
        self._select_path(new_path)
        return True, f"Renamed to {new_name}"

    def copy_path(self) -> str:
        """Return the absolute path of the selected item."""
        item = self.get_selected()
        if not item:
            return ""
        _, _, path, _ = item
        return path if path != PARENT else ""

    def copy_relative_path(self) -> str:
        """Return the path relative to the tree root."""
        item = self.get_selected()
        if not item:
            return ""
        _, _, path, _ = item
        if path == PARENT:
            return ""
        try:
            return os.path.relpath(path, self.root_dir)
        except ValueError:
            return path

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #
    def _is_visible(self, name: str) -> bool:
        if name in self.ALWAYS_IGNORED_NAMES:
            return False
        if name.endswith(self.ALWAYS_IGNORED_SUFFIXES):
            return False
        if name.startswith("."):
            return self.show_hidden
        return True

    def _build_tree(self, current_dir: str, depth: int) -> None:
        """Recursively list contents of a directory if it is expanded."""
        try:
            entries = os.listdir(current_dir)
        except OSError:
            return

        dirs, files = [], []
        for name in entries:
            if not self._is_visible(name):
                continue
            full_path = os.path.join(current_dir, name)
            if os.path.isdir(full_path):
                dirs.append((name, full_path))
            else:
                files.append((name, full_path))

        dirs.sort(key=lambda x: x[0].lower())
        files.sort(key=lambda x: x[0].lower())

        for name, path in dirs:
            is_expanded = path in self.expanded_dirs
            marker = "▼" if is_expanded else "▶"
            self.items.append((depth, f"{marker} {name}", path, True))
            if is_expanded:
                self._build_tree(path, depth + 1)

        for name, path in files:
            self.items.append((depth, f"  {name}", path, False))
