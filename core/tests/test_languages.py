import unittest

from stdedit.languages.schema import (
    detect_language,
    language_keywords,
    language_label,
    tokenize,
)


class TestLanguageDetection(unittest.TestCase):
    def test_detects_python_by_extension(self):
        self.assertEqual(detect_language("main.py"), "python")
        self.assertEqual(detect_language("script.pyw"), "python")

    def test_detects_javascript_by_extension(self):
        self.assertEqual(detect_language("app.js"), "javascript")
        self.assertEqual(detect_language("component.jsx"), "javascript")
        self.assertEqual(detect_language("module.mjs"), "javascript")

    def test_detects_typescript_by_extension(self):
        self.assertEqual(detect_language("app.ts"), "typescript")
        self.assertEqual(detect_language("component.tsx"), "typescript")

    def test_detects_html_by_extension(self):
        self.assertEqual(detect_language("index.html"), "html")
        self.assertEqual(detect_language("page.htm"), "html")

    def test_detects_css_by_extension(self):
        self.assertEqual(detect_language("style.css"), "css")
        self.assertEqual(detect_language("style.scss"), "css")

    def test_detects_c_by_extension(self):
        self.assertEqual(detect_language("main.c"), "c")
        self.assertEqual(detect_language("header.h"), "c")

    def test_detects_cpp_by_extension(self):
        self.assertEqual(detect_language("main.cpp"), "cpp")
        self.assertEqual(detect_language("header.hpp"), "cpp")

    def test_detects_java_by_extension(self):
        self.assertEqual(detect_language("Main.java"), "java")

    def test_detects_rust_by_extension(self):
        self.assertEqual(detect_language("main.rs"), "rust")

    def test_detects_go_by_extension(self):
        self.assertEqual(detect_language("main.go"), "go")

    def test_detects_json_by_extension(self):
        self.assertEqual(detect_language("config.json"), "json")

    def test_detects_yaml_by_extension(self):
        self.assertEqual(detect_language("config.yaml"), "yaml")
        self.assertEqual(detect_language("config.yml"), "yaml")

    def test_detects_markdown_by_extension(self):
        self.assertEqual(detect_language("README.md"), "markdown")

    def test_detects_shell_by_extension(self):
        self.assertEqual(detect_language("script.sh"), "shell")
        self.assertEqual(detect_language("script.bash"), "shell")

    def test_detects_sql_by_extension(self):
        self.assertEqual(detect_language("query.sql"), "sql")

    def test_detects_xml_by_extension(self):
        self.assertEqual(detect_language("config.xml"), "xml")

    def test_unknown_extension_is_plaintext(self):
        self.assertEqual(detect_language("notes.txt"), "plaintext")
        self.assertEqual(detect_language("no_extension"), "plaintext")


class TestLanguageKeywords(unittest.TestCase):
    """Suggestion keyword pools differ per file type."""
    def test_detected_language_fall_backs_to_plaintext(self):
        self.assertEqual(detect_language(""), "plaintext")
        self.assertEqual(detect_language("untitled"), "plaintext")

    def test_main_languages_have_distinct_keyword_sets(self):
        langs = ["python", "javascript", "typescript", "c", "cpp", "java",
                 "rust", "go", "sql", "shell"]
        pools = [language_keywords(lg) for lg in langs]
        for lg, pool in zip(langs, pools):
            self.assertTrue(pool, f"{lg} keyword pool is empty")
        for i in range(len(langs)):
            for j in range(i + 1, len(langs)):
                self.assertNotEqual(
                    set(pools[i]), set(pools[j]),
                    f"{langs[i]} and {langs[j]} share identical keyword pools")

    def test_html_xml_css_have_distinct_keyword_sets(self):
        pools = [language_keywords(lg) for lg in ("html", "xml", "css")]
        for pool in pools:
            self.assertTrue(pool)
        self.assertNotEqual(set(pools[0]), set(pools[1]))
        self.assertNotEqual(set(pools[0]), set(pools[2]))
        self.assertNotEqual(set(pools[1]), set(pools[2]))

    def test_html_suggests_tags_and_css_suggests_properties(self):
        html_kw = set(language_keywords("html"))
        css_kw = set(language_keywords("css"))
        self.assertIn("div", html_kw)
        self.assertIn("form", html_kw)
        self.assertIn("color", css_kw)
        self.assertIn("justify-content", css_kw)

    def test_markdown_and_plaintext_have_no_keywords(self):
        self.assertFalse(language_keywords("markdown"))
        self.assertFalse(language_keywords("plaintext"))


class TestPythonTokenizer(unittest.TestCase):
    def test_keyword_detected(self):
        spans = tokenize("def foo():", "python")
        kinds = [s[2] for s in spans]
        self.assertIn("keyword", kinds)

    def test_string_detected(self):
        spans = tokenize('x = "hello"', "python")
        text_spans = [("string", "hello")]
        found = [s for s in spans if s[2] == "string"]
        self.assertTrue(found)
        start, end, _ = found[0]
        self.assertEqual('x = "hello"'[start:end], '"hello"')

    def test_comment_detected(self):
        spans = tokenize("x = 1  # a comment", "python")
        found = [s for s in spans if s[2] == "comment"]
        self.assertTrue(found)
        start, end, _ = found[0]
        self.assertEqual("x = 1  # a comment"[start:end], "# a comment")

    def test_number_detected(self):
        spans = tokenize("x = 42", "python")
        found = [s for s in spans if s[2] == "number"]
        self.assertEqual(len(found), 1)

    def test_comment_wins_over_keyword_inside_it(self):
        # 'if' appears inside the comment text but should stay tagged
        # as part of the comment, not split out as a keyword.
        line = "y = 2  # if this breaks, oops"
        spans = tokenize(line, "python")
        comment_spans = [s for s in spans if s[2] == "comment"]
        self.assertEqual(len(comment_spans), 1)
        start, end, _ = comment_spans[0]
        self.assertEqual(line[start:end], "# if this breaks, oops")

    def test_plaintext_returns_no_tokens(self):
        self.assertEqual(tokenize("anything at all", "plaintext"), [])

    def test_unknown_language_returns_no_tokens(self):
        self.assertEqual(tokenize("anything at all", "made_up_lang"), [])


class TestJavaScriptTokenizer(unittest.TestCase):
    def test_keyword_detected(self):
        spans = tokenize("function test() {}", "javascript")
        kinds = [s[2] for s in spans]
        self.assertIn("keyword", kinds)

    def test_string_detected(self):
        spans = tokenize('const x = "hello"', "javascript")
        found = [s for s in spans if s[2] == "string"]
        self.assertTrue(found)

    def test_comment_detected(self):
        spans = tokenize("let x = 1; // comment", "javascript")
        found = [s for s in spans if s[2] == "comment"]
        self.assertTrue(found)

    def test_function_detected(self):
        spans = tokenize("myFunc()", "javascript")
        found = [s for s in spans if s[2] == "function"]
        self.assertTrue(found)


class TestTypeScriptTokenizer(unittest.TestCase):
    def test_type_keyword_detected(self):
        spans = tokenize("let x: string = 'hello'", "typescript")
        found = [s for s in spans if s[2] == "type"]
        self.assertTrue(found)

    def test_interface_keyword_detected(self):
        spans = tokenize("interface User {}", "typescript")
        kinds = [s[2] for s in spans]
        self.assertIn("keyword", kinds)


class TestHTMLTokenizer(unittest.TestCase):
    def test_tag_detected(self):
        spans = tokenize('<div class="container">', "html")
        found = [s for s in spans if s[2] == "tag"]
        self.assertTrue(found)

    def test_attribute_detected(self):
        spans = tokenize('<div class="test">', "html")
        found = [s for s in spans if s[2] == "attribute"]
        self.assertTrue(found)


class TestCSSTokenizer(unittest.TestCase):
    def test_property_detected(self):
        spans = tokenize("color: red;", "css")
        found = [s for s in spans if s[2] == "property"]
        self.assertTrue(found)

    def test_comment_detected(self):
        spans = tokenize("/* comment */", "css")
        found = [s for s in spans if s[2] == "comment"]
        self.assertTrue(found)


class TestCTokenizer(unittest.TestCase):
    def test_keyword_detected(self):
        spans = tokenize("int main() {", "c")
        kinds = [s[2] for s in spans]
        self.assertIn("keyword", kinds)

    def test_function_detected(self):
        spans = tokenize("printf()", "c")
        found = [s for s in spans if s[2] == "function"]
        self.assertTrue(found)


class TestRustTokenizer(unittest.TestCase):
    def test_keyword_detected(self):
        spans = tokenize("fn main() {", "rust")
        kinds = [s[2] for s in spans]
        self.assertIn("keyword", kinds)

    def test_type_detected(self):
        spans = tokenize("let x: i32 = 5;", "rust")
        found = [s for s in spans if s[2] == "type"]
        self.assertTrue(found)


class TestJavaTokenizer(unittest.TestCase):
    def test_keyword_detected(self):
        spans = tokenize("public class Main {", "java")
        kinds = [s[2] for s in spans]
        self.assertIn("keyword", kinds)

    def test_type_detected(self):
        spans = tokenize("String name;", "java")
        found = [s for s in spans if s[2] == "type"]
        self.assertTrue(found)


class TestIndentSpecs(unittest.TestCase):
    def test_all_languages_have_indent_size(self):
        from stdedit.languages.schema import LANGUAGES, get_indent_spec

        for name in LANGUAGES:
            spec = get_indent_spec(name)
            self.assertIn("size", spec, name)
            self.assertIsInstance(spec["size"], int, name)
            self.assertGreater(spec["size"], 0, name)

    def test_brace_languages_have_decrease(self):
        from stdedit.languages.schema import get_indent_spec

        for lang in ("javascript", "typescript", "c", "cpp", "java",
                     "rust", "go", "css"):
            spec = get_indent_spec(lang)
            self.assertIn("increase", spec, lang)
            self.assertIn("decrease", spec, lang)


class TestLanguageLabels(unittest.TestCase):
    def test_friendly_names(self):
        self.assertEqual(language_label("python"), "Python")
        self.assertEqual(language_label("javascript"), "JavaScript")
        self.assertEqual(language_label("cpp"), "C++")
        self.assertEqual(language_label("shell"), "Shell")
        self.assertEqual(language_label("plaintext"), "Text")

    def test_unknown_language_falls_back_to_text(self):
        self.assertEqual(language_label("made_up_lang"), "Text")


if __name__ == "__main__":
    unittest.main()
