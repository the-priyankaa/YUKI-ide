"""Tiny Vim-style example extension.

This is intentionally small: it demonstrates the extension API without
replacing the core editor. Press Ctrl-B to toggle a Vim-like status message.
"""


def setup(api):
    api.extension("vim-command-demo", "1.0", "Example Vim-style extension hook")
    state = {"enabled": False}

    def toggle(editor, _key):
        state["enabled"] = not state["enabled"]
        editor.status = "Vim mode ON" if state["enabled"] else "Vim mode OFF"
        return True

    api.bind_key("\x02", toggle)  # Ctrl-B
    api.add_status(lambda editor: "[VIM DEMO]" if state["enabled"] else "")
