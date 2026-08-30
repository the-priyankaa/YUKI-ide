"""Example stdedit extension: add a live word/character count to the status bar."""


def setup(api):
    api.extension("word-count", "1.0", "Shows document word and character counts")

    def status(editor):
        text = "\n".join(editor.buffer.lines)
        return f"Words {len(text.split())}  Chars {len(text)}"

    api.add_status(status)
