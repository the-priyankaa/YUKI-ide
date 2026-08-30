"""safe_render — sanitize text before handing it to curses.addstr.

curses ``addstr`` raises for embedded NUL bytes (``ValueError: embedded
null character``) and ``UnicodeEncodeError`` for lone surrogates, which can
leak into display code from latin-1-decoded binary files, ``surrogateescape``
filesystem names, or git subprocess output.  Centralising this here lets every
front-end module (tui, dashboard, newfile, extview, git_panel, diff_viewer)
share one implementation without importing the curses front end.
"""
from __future__ import annotations


def safe_render(text: str) -> str:
    """Return a curses-safe copy of *text*.

    C0 control bytes (other than tab) are replaced with a visible middle-dot
    placeholder and lone surrogates are backslash-escaped, so no render path
    can crash the editor with a null-character or encoding error.
    """
    if not text:
        return text
    out = []
    for ch in text:
        o = ord(ch)
        if 0xD800 <= o <= 0xDFFF:
            out.append("\\u%04x" % o)
        elif o < 32 and o != 9:
            out.append("\u00b7")  # middle dot placeholder for control bytes
        else:
            out.append(ch)
    return "".join(out)
