"""Small zero-dependency extension API for stdedit.

Extensions are optional Python modules. A module may expose ``setup(api)`` or
``register(api)``. The API intentionally exposes only stable, useful hooks:
commands, key handlers, lifecycle callbacks, and status providers.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Any

Command = Callable[[Any], Optional[str]]
KeyHandler = Callable[[Any, Any], bool]
Callback = Callable[[Any], None]
StatusProvider = Callable[[Any], str]


@dataclass
class Extension:
    name: str
    version: str = "0.1"
    description: str = ""


class ExtensionAPI:
    def __init__(self, editor: Any):
        self.editor = editor
        self.commands: Dict[str, Command] = {}
        self.key_handlers: Dict[Any, List[KeyHandler]] = {}
        self.on_startup: List[Callback] = []
        self.on_shutdown: List[Callback] = []
        self.status_providers: List[StatusProvider] = []
        self.loaded: List[Extension] = []
        self._errors: List[str] = []

    def _safe_call(self, what: str, fn: Callable, *args: Any) -> Any:
        """Run `fn`, swallowing exceptions so extension bugs never kill
        the editor.  Failures are recorded so tests/UI can inspect them."""
        try:
            return fn(*args)
        except Exception as exc:  # noqa: BLE001 - extension boundary
            self._errors.append(f"{what}: {type(exc).__name__}: {exc}")
            return None

    def add_command(self, name: str, callback: Command) -> None:
        if not name or not callable(callback):
            raise ValueError("command name and callback are required")
        self.commands[name] = callback

    def bind_key(self, key: Any, callback: KeyHandler) -> None:
        if not callable(callback):
            raise ValueError("key callback must be callable")
        self.key_handlers.setdefault(key, []).append(callback)

    def add_status(self, callback: StatusProvider) -> None:
        self.status_providers.append(callback)

    def extension(self, name: str, version: str = "0.1", description: str = "") -> Extension:
        ext = Extension(name, version, description)
        self.loaded.append(ext)
        return ext

    def dispatch_key(self, key: Any) -> bool:
        handled = False
        for callback in self.key_handlers.get(key, ()):
            result = self._safe_call("key", callback, self.editor, key)
            handled = bool(result) or handled
        return handled

    def startup(self) -> None:
        for callback in self.on_startup:
            self._safe_call("startup", callback, self.editor)

    def shutdown(self) -> None:
        for callback in reversed(self.on_shutdown):
            self._safe_call("shutdown", callback, self.editor)

    def status(self) -> str:
        parts = []
        for callback in self.status_providers:
            value = self._safe_call("status", callback, self.editor)
            if value:
                parts.append(value)
        return "  ".join(parts)

    def runtime_errors(self) -> List[str]:
        """Callback failures since the last look, for tests and UI hints."""
        return list(self._errors)
