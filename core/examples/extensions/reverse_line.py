"""External extension example: Ctrl-R reverses the current line."""


def setup(api):
    api.extension("reverse-line", "1.0", "Reverse the current line")

    def reverse(editor, _key):
        buf = editor.buffer
        line = buf.current_line
        buf.lines[buf.cursor_y] = line[::-1]
        buf.cursor_x = min(len(line) - buf.cursor_x, len(buf.current_line))
        buf.modified = True
        editor.status = "Reversed current line"
        return True

    api.bind_key("\x12", reverse)  # Ctrl-R
