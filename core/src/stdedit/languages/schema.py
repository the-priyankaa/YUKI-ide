r"""
schema.py — token-rule JSON schema + language detection. OWNER: Person C.

Phase 1 target: define this schema + one working language (Python).
Phase 2 target: 6+ languages (Python, JS/TS, HTML/CSS, JSON, YAML,
                 Markdown, shell) + detection by file extension.

Suggested rule shape (regex-based, `re` from stdlib only, per STDLIB.md
substitution pygments -> re):

    LANGUAGES = {
        "python": {
            "extensions": [".py"],
            "rules": [
                # (token_type, regex)
                ("comment", r"#.*$"),
                ("string",  r"(\"\"\".*?\"\"\"|'''.*?'''|\".*?\"|'.*?')"),
                ("keyword", r"\b(def|class|if|elif|else|for|while|return|import|from|as|with|try|except|finally|raise|yield|lambda|pass|break|continue|and|or|not|in|is|None|True|False)\b"),
                ("number",  r"\b\d+(\.\d+)?\b"),
            ],
        },
    }

tokenize(line, language) should return a list of (start, end, token_type)
spans so tui.py can map them to curses color pairs.
"""

from __future__ import annotations

import re
from typing import Dict, List, Tuple

TokenSpan = Tuple[int, int, str]  # start, end, token_type

LANGUAGES: Dict[str, dict] = {
    "plaintext": {
        "extensions": [],
        "keywords": [],
        "rules": [],
        "indent": {"size": 4},
    },
    "python": {
        "extensions": [".py", ".pyw"],
        "keywords": [
            "def", "class", "if", "elif", "else", "for", "while", "return",
            "import", "from", "as", "with", "try", "except", "finally",
            "raise", "yield", "lambda", "pass", "break", "continue", "and",
            "or", "not", "in", "is", "None", "True", "False", "global",
            "nonlocal", "assert", "del", "async", "await",
        ],
        "indent": {"size": 4, "increase": r":\s*$"},
        "rules": [
            # Order matters: earlier rules win at the same start position.
            ("comment", r"#.*"),
            ("string", r"(\"\"\".*?\"\"\"|'''.*?'''|\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*')"),
            (
                "keyword",
                r"\b(?:def|class|if|elif|else|for|while|return|import|from|as|"
                r"with|try|except|finally|raise|yield|lambda|pass|break|continue|"
                r"and|or|not|in|is|None|True|False|global|nonlocal|assert|del|"
                r"async|await)\b",
            ),
            ("number", r"\b\d+(?:\.\d+)?\b"),
        ],
    },
    "javascript": {
        "extensions": [".js", ".jsx", ".mjs"],
        "keywords": [
            "function", "const", "let", "var", "if", "else", "for", "while",
            "do", "switch", "case", "default", "break", "continue", "return",
            "try", "catch", "finally", "throw", "async", "await", "class",
            "extends", "import", "export", "from", "as", "new", "this",
            "super", "static", "get", "set", "typeof", "instanceof", "in",
            "of", "delete", "void", "yield", "with",
        ],
        "indent": {"size": 2, "increase": r"\{\s*$", "decrease": r"\}"},
        "rules": [
            ("comment", r"//.*|/\*.*?\*/"),
            ("string", r"(`(?:[^`\\]|\\.)*`|\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*')"),
            (
                "keyword",
                r"\b(?:function|const|let|var|if|else|for|while|do|switch|case|default|"
                r"break|continue|return|try|catch|finally|throw|async|await|class|"
                r"extends|import|export|from|as|new|this|super|static|get|set|"
                r"typeof|instanceof|in|of|delete|void|yield|with)\b",
            ),
            ("number", r"\b(?:0x[0-9a-fA-F]+|\d+\.?\d*(?:[eE][+-]?\d+)?)\b"),
            ("function", r"\b[a-zA-Z_$][a-zA-Z0-9_$]*(?=\s*\()"),
        ],
    },
    "typescript": {
        "extensions": [".ts", ".tsx"],
        "keywords": [
            "function", "const", "let", "var", "if", "else", "for", "while",
            "do", "switch", "case", "default", "break", "continue", "return",
            "try", "catch", "finally", "throw", "async", "await", "class",
            "extends", "import", "export", "from", "as", "new", "this",
            "super", "static", "get", "set", "typeof", "instanceof", "in",
            "of", "delete", "void", "yield", "with", "interface", "type",
            "enum", "namespace", "module", "declare", "abstract",
            "implements", "public", "private", "protected", "readonly",
            "override",
        ],
        "indent": {"size": 2, "increase": r"\{\s*$", "decrease": r"\}"},
        "rules": [
            ("comment", r"//.*|/\*.*?\*/"),
            ("string", r"(`(?:[^`\\]|\\.)*`|\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*')"),
            (
                "keyword",
                r"\b(?:function|const|let|var|if|else|for|while|do|switch|case|default|"
                r"break|continue|return|try|catch|finally|throw|async|await|class|"
                r"extends|import|export|from|as|new|this|super|static|get|set|"
                r"typeof|instanceof|in|of|delete|void|yield|with|interface|type|"
                r"enum|namespace|module|declare|abstract|implements|public|private|"
                r"protected|readonly|override)\b",
            ),
            ("type", r"\b(?:string|number|boolean|any|void|never|unknown|object|null|undefined)\b"),
            ("number", r"\b(?:0x[0-9a-fA-F]+|\d+\.?\d*(?:[eE][+-]?\d+)?)\b"),
            ("function", r"\b[a-zA-Z_$][a-zA-Z0-9_$]*(?=\s*[<(])"),
        ],
    },
    "html": {
        "extensions": [".html", ".htm"],
        "keywords": [
            "doctype", "html", "head", "body", "title", "meta", "link",
            "style", "script", "div", "span", "p", "a", "img", "br", "hr",
            "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "table",
            "thead", "tbody", "tr", "td", "th", "form", "input", "button",
            "select", "option", "textarea", "label", "nav", "header",
            "footer", "main", "section", "article", "aside", "figure",
            "figcaption", "video", "audio", "iframe", "canvas",
        ],
        "indent": {"size": 2, "increase": r"<[^/!-][^>]*>\s*$", "decrease": r"</"},
        "rules": [
            ("comment", r"<!--.*?-->"),
            ("tag", r"</?[a-zA-Z][a-zA-Z0-9-]*|/?>"),
            ("attribute", r"\b[a-zA-Z-]+(?==)"),
            ("string", r"\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*'"),
        ],
    },
    "css": {
        "extensions": [".css", ".scss", ".sass"],
        "keywords": [
            "media", "import", "font-face", "keyframes", "charset",
            "namespace", "supports", "page", "document",
            "color", "background", "background-color", "background-image",
            "font-size", "font-family", "font-weight", "line-height",
            "margin", "margin-top", "margin-right", "margin-bottom",
            "margin-left", "padding", "padding-top", "padding-right",
            "padding-bottom", "padding-left", "border", "border-radius",
            "display", "position", "top", "right", "bottom", "left",
            "width", "height", "min-width", "max-width", "overflow",
            "flex", "grid", "gap", "align-items", "justify-content",
            "z-index", "text-align", "text-decoration", "transform",
            "transition", "opacity", "box-shadow", "cursor",
        ],
        "indent": {"size": 2, "increase": r"\{\s*$", "decrease": r"\}"},
        "rules": [
            ("comment", r"/\*.*?\*/|//.*"),
            ("property", r"\b[a-z-]+(?=\s*:)"),
            ("keyword", r"@(?:media|import|font-face|keyframes|charset|namespace|supports|page|document)"),
            ("string", r"\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*'"),
            ("number", r"\b\d+(?:\.\d+)?(?:px|em|rem|%|vh|vw|ch|ex|cm|mm|in|pt|pc|s|ms|deg|rad|turn)?\b"),
            ("function", r"\b[a-z-]+(?=\()"),
        ],
    },
    "c": {
        "extensions": [".c", ".h"],
        "keywords": [
            "auto", "break", "case", "char", "const", "continue", "default",
            "do", "double", "else", "enum", "extern", "float", "for", "goto",
            "if", "inline", "int", "long", "register", "restrict", "return",
            "short", "signed", "sizeof", "static", "struct", "switch",
            "typedef", "union", "unsigned", "void", "volatile", "while",
            "_Bool", "_Complex", "_Imaginary",
        ],
        "indent": {"size": 4, "increase": r"\{\s*$", "decrease": r"\}"},
        "rules": [
            ("comment", r"//.*|/\*.*?\*/"),
            ("string", r"\"(?:[^\"\\]|\\.)*\""),
            (
                "keyword",
                r"\b(?:auto|break|case|char|const|continue|default|do|double|else|enum|"
                r"extern|float|for|goto|if|inline|int|long|register|restrict|return|"
                r"short|signed|sizeof|static|struct|switch|typedef|union|unsigned|void|"
                r"volatile|while|_Bool|_Complex|_Imaginary)\b",
            ),
            ("number", r"\b(?:0x[0-9a-fA-F]+|\d+\.?\d*(?:[eE][+-]?\d+)?[fFlLuU]*)\b"),
            ("function", r"\b[a-zA-Z_][a-zA-Z0-9_]*(?=\s*\()"),
        ],
    },
    "cpp": {
        "extensions": [".cpp", ".cc", ".cxx", ".hpp", ".hxx", ".h++", ".C"],
        "keywords": [
            "alignas", "alignof", "and", "and_eq", "asm", "auto", "bitand",
            "bitor", "bool", "break", "case", "catch", "char", "char8_t",
            "char16_t", "char32_t", "class", "compl", "concept", "const",
            "consteval", "constexpr", "constinit", "const_cast", "continue",
            "co_await", "co_return", "co_yield", "decltype", "default",
            "delete", "do", "double", "dynamic_cast", "else", "enum",
            "explicit", "export", "extern", "false", "float", "for", "friend",
            "goto", "if", "inline", "int", "long", "mutable", "namespace",
            "new", "noexcept", "not", "not_eq", "nullptr", "operator", "or",
            "or_eq", "private", "protected", "public", "register",
            "reinterpret_cast", "requires", "return", "short", "signed",
            "sizeof", "static", "static_assert", "static_cast", "struct",
            "switch", "template", "this", "thread_local", "throw", "true",
            "try", "typedef", "typeid", "typename", "union", "unsigned",
            "using", "virtual", "void", "volatile", "wchar_t", "while",
            "xor", "xor_eq",
        ],
        "indent": {"size": 4, "increase": r"\{\s*$", "decrease": r"\}"},
        "rules": [
            ("comment", r"//.*|/\*.*?\*/"),
            ("string", r"\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*'"),
            (
                "keyword",
                r"\b(?:alignas|alignof|and|and_eq|asm|auto|bitand|bitor|bool|break|case|"
                r"catch|char|char8_t|char16_t|char32_t|class|compl|concept|const|consteval|"
                r"constexpr|constinit|const_cast|continue|co_await|co_return|co_yield|"
                r"decltype|default|delete|do|double|dynamic_cast|else|enum|explicit|export|"
                r"extern|false|float|for|friend|goto|if|inline|int|long|mutable|namespace|"
                r"new|noexcept|not|not_eq|nullptr|operator|or|or_eq|private|protected|public|"
                r"register|reinterpret_cast|requires|return|short|signed|sizeof|static|"
                r"static_assert|static_cast|struct|switch|template|this|thread_local|throw|"
                r"true|try|typedef|typeid|typename|union|unsigned|using|virtual|void|"
                r"volatile|wchar_t|while|xor|xor_eq)\b",
            ),
            ("number", r"\b(?:0x[0-9a-fA-F]+|\d+\.?\d*(?:[eE][+-]?\d+)?[fFlLuU]*)\b"),
            ("function", r"\b[a-zA-Z_][a-zA-Z0-9_]*(?=\s*[<(])"),
        ],
    },
    "java": {
        "extensions": [".java"],
        "keywords": [
            "abstract", "assert", "boolean", "break", "byte", "case", "catch",
            "char", "class", "const", "continue", "default", "do", "double",
            "else", "enum", "extends", "final", "finally", "float", "for",
            "goto", "if", "implements", "import", "instanceof", "int",
            "interface", "long", "native", "new", "package", "private",
            "protected", "public", "return", "short", "static", "strictfp",
            "super", "switch", "synchronized", "this", "throw", "throws",
            "transient", "try", "void", "volatile", "while",
        ],
        "indent": {"size": 4, "increase": r"\{\s*$", "decrease": r"\}"},
        "rules": [
            ("comment", r"//.*|/\*.*?\*/"),
            ("string", r"\"(?:[^\"\\]|\\.)*\""),
            (
                "keyword",
                r"\b(?:abstract|assert|boolean|break|byte|case|catch|char|class|const|"
                r"continue|default|do|double|else|enum|extends|final|finally|float|for|"
                r"goto|if|implements|import|instanceof|int|interface|long|native|new|"
                r"package|private|protected|public|return|short|static|strictfp|super|"
                r"switch|synchronized|this|throw|throws|transient|try|void|volatile|while)\b",
            ),
            ("type", r"\b(?:Boolean|Byte|Character|Double|Float|Integer|Long|Short|String|Object|void)\b"),
            ("number", r"\b(?:0x[0-9a-fA-F]+|\d+\.?\d*(?:[eE][+-]?\d+)?[fFdDlL]*)\b"),
            ("function", r"\b[a-zA-Z_][a-zA-Z0-9_]*(?=\s*\()"),
        ],
    },
    "rust": {
        "extensions": [".rs"],
        "keywords": [
            "as", "async", "await", "break", "const", "continue", "crate",
            "dyn", "else", "enum", "extern", "false", "fn", "for", "if",
            "impl", "in", "let", "loop", "match", "mod", "move", "mut",
            "pub", "ref", "return", "self", "Self", "static", "struct",
            "super", "trait", "true", "type", "unsafe", "use", "where",
            "while",
        ],
        "indent": {"size": 4, "increase": r"\{\s*$", "decrease": r"\}"},
        "rules": [
            ("comment", r"//.*|/\*.*?\*/"),
            ("string", r'"(?:[^"\\]|\\.)*"'),
            (
                "keyword",
                r"\b(?:as|async|await|break|const|continue|crate|dyn|else|enum|extern|"
                r"false|fn|for|if|impl|in|let|loop|match|mod|move|mut|pub|ref|return|"
                r"self|Self|static|struct|super|trait|true|type|unsafe|use|where|while)\b",
            ),
            ("type", r"\b(?:i8|i16|i32|i64|i128|isize|u8|u16|u32|u64|u128|usize|f32|f64|bool|char|str)\b"),
            ("number", r"\b(?:0x[0-9a-fA-F_]+|0o[0-7_]+|0b[01_]+|\d[\d_]*\.?[\d_]*(?:[eE][+-]?[\d_]+)?)\b"),
            ("function", r"\b[a-z_][a-z0-9_]*!?(?=\s*[(<])"),
        ],
    },
    "go": {
        "extensions": [".go"],
        "keywords": [
            "break", "case", "chan", "const", "continue", "default", "defer",
            "else", "fallthrough", "for", "func", "go", "goto", "if",
            "import", "interface", "map", "package", "range", "return",
            "select", "struct", "switch", "type", "var",
        ],
        "indent": {"size": 4, "increase": r"\{\s*$", "decrease": r"\}"},
        "rules": [
            ("comment", r"//.*|/\*.*?\*/"),
            ("string", r"`[^`]*`|\"(?:[^\"\\]|\\.)*\""),
            (
                "keyword",
                r"\b(?:break|case|chan|const|continue|default|defer|else|fallthrough|"
                r"for|func|go|goto|if|import|interface|map|package|range|return|select|"
                r"struct|switch|type|var)\b",
            ),
            ("type", r"\b(?:bool|byte|complex64|complex128|error|float32|float64|int|int8|"
                r"int16|int32|int64|rune|string|uint|uint8|uint16|uint32|uint64|uintptr)\b"),
            ("number", r"\b(?:0x[0-9a-fA-F]+|\d+\.?\d*(?:[eE][+-]?\d+)?)\b"),
            ("function", r"\b[a-zA-Z_][a-zA-Z0-9_]*(?=\s*\()"),
        ],
    },
    "json": {
        "extensions": [".json"],
        "keywords": ["true", "false", "null"],
        "indent": {"size": 2, "increase": r"[\[\{]\s*$", "decrease": r"[\]\}]"},
        "rules": [
            ("keyword", r"\b(?:true|false|null)\b"),
            ("string", r"\"(?:[^\"\\]|\\.)*\""),
            ("number", r"-?\d+\.?\d*(?:[eE][+-]?\d+)?"),
        ],
    },
    "yaml": {
        "extensions": [".yaml", ".yml"],
        "keywords": ["true", "false", "null", "yes", "no", "on", "off"],
        "indent": {"size": 2, "increase": r":\s*$"},
        "rules": [
            ("comment", r"#.*"),
            ("keyword", r"\b(?:true|false|null|yes|no|on|off)\b"),
            ("string", r"\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*'"),
            ("number", r"\b-?\d+\.?\d*(?:[eE][+-]?\d+)?\b"),
            ("property", r"^\s*[a-zA-Z_][a-zA-Z0-9_-]*(?=\s*:)"),
        ],
    },
    "markdown": {
        "extensions": [".md", ".markdown"],
        "keywords": [],
        "indent": {"size": 4},
        "rules": [
            ("comment", r"<!--.*?-->"),
            ("keyword", r"^#{1,6}\s.*$|^\*\*.*?\*\*|^__.*?__|^\*.*?\*|^_.*?_"),
            ("string", r"`[^`]*`|```[\s\S]*?```"),
        ],
    },
    "shell": {
        "extensions": [".sh", ".bash", ".zsh"],
        "keywords": [
            "if", "then", "else", "elif", "fi", "case", "esac", "for",
            "while", "do", "done", "in", "function", "return", "break",
            "continue", "exit", "export", "declare", "local", "readonly",
            "shift", "eval", "exec", "source", "alias", "unalias", "type",
            "command",
        ],
        "indent": {"size": 4, "increase": r"(?:;\s*$|then\s*$|do\s*$|in\s*$)"},
        "rules": [
            ("comment", r"#.*"),
            ("string", r"\"(?:[^\"\\$]|\\.)*\"|'[^']*'"),
            (
                "keyword",
                r"\b(?:if|then|else|elif|fi|case|esac|for|while|do|done|in|function|"
                r"return|break|continue|exit|export|declare|local|readonly|shift|"
                r"eval|exec|source|alias|unalias|type|command)\b",
            ),
            ("function", r"\b[a-zA-Z_][a-zA-Z0-9_]*(?=\s*\(\s*\))"),
        ],
    },
    "sql": {
        "extensions": [".sql"],
        "keywords": [
            "SELECT", "FROM", "WHERE", "INSERT", "UPDATE", "DELETE",
            "CREATE", "ALTER", "DROP", "TABLE", "INDEX", "VIEW", "DATABASE",
            "SCHEMA", "PRIMARY", "FOREIGN", "KEY", "CONSTRAINT", "NULL",
            "NOT", "AND", "OR", "IN", "LIKE", "BETWEEN", "JOIN", "LEFT",
            "RIGHT", "INNER", "OUTER", "ON", "AS", "GROUP", "BY", "ORDER",
            "HAVING", "LIMIT", "OFFSET", "UNION", "ALL", "DISTINCT",
            "EXISTS", "CASE", "WHEN", "THEN", "ELSE", "END", "BEGIN",
            "COMMIT", "ROLLBACK", "TRANSACTION",
        ],
        "indent": {"size": 4},
        "rules": [
            ("comment", r"--.*|/\*.*?\*/"),
            ("string", r"'(?:[^'\\]|\\.)*'"),
            (
                "keyword",
                r"\b(?:SELECT|FROM|WHERE|INSERT|UPDATE|DELETE|CREATE|ALTER|DROP|TABLE|"
                r"INDEX|VIEW|DATABASE|SCHEMA|PRIMARY|FOREIGN|KEY|CONSTRAINT|NULL|NOT|"
                r"AND|OR|IN|LIKE|BETWEEN|JOIN|LEFT|RIGHT|INNER|OUTER|ON|AS|GROUP|BY|"
                r"ORDER|HAVING|LIMIT|OFFSET|UNION|ALL|DISTINCT|EXISTS|CASE|WHEN|THEN|"
                r"ELSE|END|BEGIN|COMMIT|ROLLBACK|TRANSACTION)\b",
            ),
            ("type", r"\b(?:INTEGER|INT|SMALLINT|BIGINT|DECIMAL|NUMERIC|FLOAT|REAL|DOUBLE|"
                r"CHAR|VARCHAR|TEXT|DATE|TIME|TIMESTAMP|BOOLEAN|BOOL)\b"),
            ("number", r"\b\d+\.?\d*\b"),
        ],
    },
    "xml": {
        "extensions": [".xml", ".svg", ".xhtml"],
        "keywords": [
            "version", "encoding", "standalone", "root", "element",
            "attribute", "value", "cdata", "schema", "transform", "template",
            "svg", "g", "path", "line", "rect", "circle", "text",
            "fill", "stroke", "xmlns", "xlink", "d",
        ],
        "indent": {"size": 2, "increase": r"<[^/!-][^>]*>\s*$", "decrease": r"</"},
        "rules": [
            ("comment", r"<!--.*?-->"),
            ("tag", r"</?[a-zA-Z][a-zA-Z0-9:-]*|/?>"),
            ("attribute", r"\b[a-zA-Z:-]+(?==)"),
            ("string", r"\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*'"),
        ],
    },
}

# Precompiled per-language matchers, built lazily from LANGUAGES so
# editing the table above is enough — no separate place to keep in sync.
_COMPILED: Dict[str, "re.Pattern"] = {}


def _compiled_pattern(language: str):
    if language not in _COMPILED:
        rules = LANGUAGES.get(language, {}).get("rules", [])
        if not rules:
            _COMPILED[language] = None
        else:
            combined = "|".join(f"(?P<{name}>{pattern})" for name, pattern in rules)
            _COMPILED[language] = re.compile(combined)
    return _COMPILED[language]


def detect_language(filename: str) -> str:
    for name, spec in LANGUAGES.items():
        if any(filename.endswith(ext) for ext in spec.get("extensions", [])):
            return name
    return "plaintext"


# Human-readable names shown in the status bar.
LANGUAGE_LABELS: Dict[str, str] = {
    "plaintext": "Text",
    "python": "Python",
    "javascript": "JavaScript",
    "typescript": "TypeScript",
    "html": "HTML",
    "css": "CSS",
    "c": "C",
    "cpp": "C++",
    "java": "Java",
    "rust": "Rust",
    "go": "Go",
    "json": "JSON",
    "yaml": "YAML",
    "markdown": "Markdown",
    "shell": "Shell",
    "sql": "SQL",
    "xml": "XML",
}


def language_label(language: str) -> str:
    """Return the display name for a language id ('python' -> 'Python')."""
    return LANGUAGE_LABELS.get(language, "Text")


def language_keywords(language: str) -> List[str]:
    """Return the suggestion keywords for *language* (possibly empty)."""
    return list(LANGUAGES.get(language, {}).get("keywords", []))


def tokenize(line: str, language: str) -> List[TokenSpan]:
    pattern = _compiled_pattern(language)
    if pattern is None:
        return []
    spans: List[TokenSpan] = []
    for match in pattern.finditer(line):
        token_type = match.lastgroup
        spans.append((match.start(), match.end(), token_type))
    return spans


def get_indent_spec(language: str) -> dict:
    """Return the indent config dict for a language.

    Always returns a dict with at least ``size`` (default 4).  The
    ``increase`` and ``decrease`` keys are optional raw regex strings
    that the Buffer will compile.
    """
    return LANGUAGES.get(language, {}).get("indent", {"size": 4})
