import os
import re
import unittest

from stdedit import runner
from stdedit import icons


def make_which(available):
    """Build a fake shutil.which that only knows *available* tools."""
    def _which(name):
        return f"/usr/bin/{name}" if name in available else None
    return _which


CAPTURE = []


def fake_popen(argv, *args, **kwargs):
    CAPTURE.append((argv, args, kwargs))


class RunCommandForTests(unittest.TestCase):
    def cmd_for(self, path, available):
        cmd, reason = runner.run_command_for(
            path, _which=make_which(set(available)))
        self.assertIsNotNone(cmd, reason)
        return cmd

    def test_python_uses_unbuffered_python3(self):
        cmd = self.cmd_for("proj/hello.py", {"python3"})
        self.assertTrue(cmd.startswith("python3 -u "), cmd)
        self.assertIn("hello.py", cmd)
        self.assertEqual("python3", runner.run_command_for(
            "proj/hello.py", _which=make_which({"python3"}))[1].split()[0])

    def test_paths_with_spaces_are_shell_quoted(self):
        cmd = self.cmd_for("my proj/hello world.py", {"python3"})
        self.assertRegex(cmd, r"'/.*my proj/hello world\.py'")

    def test_javascript_uses_node(self):
        self.assertIn("node", self.cmd_for("app/index.js", {"node"}))
        self.assertIn("node", self.cmd_for("mod.mjs", {"node"}))

    def test_typescript_uses_tsx_via_npx(self):
        cmd = self.cmd_for("src/main.ts", {"npx"})
        self.assertIn("npx --yes tsx", cmd)
        self.assertIn("tsx", self.cmd_for("page.jsx", {"npx"}))

    def test_java_uses_single_file_launcher(self):
        cmd = self.cmd_for("Main.java", {"java"})
        self.assertIn("java", cmd)
        self.assertNotIn("javac", cmd)

    def test_c_uses_gcc_and_temp_output(self):
        cmd = self.cmd_for("prog.c", {"gcc"})
        self.assertIn("gcc", cmd)
        self.assertRegex(cmd, r"-o /tmp/stdedit-run-\d+")

    def test_cpp_variants_use_gplusplus(self):
        for ext in ("cpp", "cc", "cxx", "C"):
            self.assertIn("g++", self.cmd_for(f"prog.{ext}", {"g++"}))

    def test_rust_uses_rustc(self):
        self.assertIn("rustc", self.cmd_for("lib.rs", {"rustc"}))

    def test_go_uses_go_run(self):
        self.assertIn("go run", self.cmd_for("pkg/main.go", {"go"}))

    def test_shell_script_prefers_bash(self):
        cmd = self.cmd_for("deploy.sh", {"bash", "sh"})
        self.assertIn("bash", cmd)
        self.assertTrue(cmd.startswith("bash "), cmd)

    def test_shell_falls_back_to_sh(self):
        cmd = self.cmd_for("deploy.sh", {"sh"})
        self.assertIn("sh ", cmd)
        self.assertFalse(cmd.startswith("bash "), cmd)

    def test_shell_with_no_interpreter_reports_reason(self):
        cmd, reason = runner.run_command_for(
            "deploy.sh", _which=make_which(set()))
        self.assertIsNone(cmd)
        self.assertIn("not found", reason)

    def test_perl_ruby_php_lua_r(self):
        self.assertIn("PERLIO=:unix perl", self.cmd_for("script.pl", {"perl"}))
        self.assertIn("ruby", self.cmd_for("app.rb", {"ruby"}))
        self.assertIn("php", self.cmd_for("page.php", {"php"}))
        self.assertIn("lua", self.cmd_for("mod.lua", {"lua"}))
        self.assertIn("Rscript", self.cmd_for("analysis.R", {"Rscript"}))
        self.assertIn("Rscript", self.cmd_for("analysis.r", {"Rscript"}))

    def test_missing_runtime_reports_reason(self):
        cmd, reason = runner.run_command_for(
            "hello.py", _which=make_which({"node"}))
        self.assertIsNone(cmd)
        self.assertIn("python3", reason)
        self.assertIn("not found", reason)

    def test_unknown_extension_reports_reason(self):
        cmd, reason = runner.run_command_for(
            "archive.zip", _which=make_which({"python3"}))
        self.assertIsNone(cmd)
        self.assertIn("No runner", reason)

    def test_extensionless_file_reports_reason(self):
        cmd, reason = runner.run_command_for(
            "README", _which=make_which({"python3"}))
        self.assertIsNone(cmd)
        self.assertIn("No runner", reason)

    def test_non_runnable_types(self):
        for fname in ("style.css", "data.json", "config.yaml", "query.sql",
                      "graph.xml", "notes.txt"):
            cmd, reason = runner.run_command_for(
                fname, _which=make_which({"python3"}))
            self.assertIsNone(cmd, fname)
            self.assertIn("No run command", reason, fname)

    def test_web_extensions_report_browser_reason(self):
        for fname in ("index.html", "page.htm", "view.xhtml", "pic.svg",
                      "notes.md", "README.markdown"):
            cmd, reason = runner.run_command_for(
                fname, _which=make_which({"python3"}))
            self.assertIsNone(cmd, fname)
            self.assertIn("browser via a local server", reason, fname)

    def test_image_extensions_report_browser_reason(self):
        for fname in ("pic.png", "pic.jpg", "pic.jpeg", "pic.gif", "pic.webp",
                      "pic.bmp", "pic.ico", "pic.tif", "pic.tiff", "pic.heic",
                      "pic.heif", "pic.avif", "pic.ppm", "pic.pgm", "pic.pbm"):
            cmd, reason = runner.run_command_for(
                fname, _which=make_which({"python3"}))
            self.assertIsNone(cmd, fname)
            self.assertIn("default browser", reason, fname)


class TerminalLauncherTests(unittest.TestCase):
    def test_prefers_kitty_when_present(self):
        argv = runner.terminal_launcher(
            _which=make_which({"kitty", "xterm"}), env={})
        self.assertEqual(argv[:2], ["kitty", "-e"])

    def test_falls_back_to_xterm(self):
        argv = runner.terminal_launcher(
            _which=make_which({"xterm"}), env={})
        self.assertEqual(argv[:2], ["xterm", "-e"])

    def test_generic_default_as_last_resort(self):
        argv = runner.terminal_launcher(
            _which=make_which({"x-terminal-emulator"}), env={})
        self.assertEqual(argv[:2], ["x-terminal-emulator", "-e"])

    def test_none_when_no_terminal(self):
        self.assertIsNone(runner.terminal_launcher(
            _which=make_which({"python3"}), env={}))

    def test_env_override_wins(self):
        argv = runner.terminal_launcher(
            _which=make_which({"cat", "kitty"}),
            env={"STDEDIT_TERMINAL": "cat"})
        self.assertEqual(argv, ["cat"])

    def test_env_override_missing_binary(self):
        self.assertIsNone(runner.terminal_launcher(
            _which=make_which({"kitty"}),
            env={"STDEDIT_TERMINAL": "ghost"}))


class RunFileTests(unittest.TestCase):
    def setUp(self):
        CAPTURE.clear()

    def test_run_python_in_kitty(self):
        ok, status = runner.run_file(
            "proj/hello.py",
            _which=make_which({"python3", "kitty"}),
            _popen=fake_popen, env={}, pty=False)
        self.assertTrue(ok, status)
        self.assertRegex(status, r"Running: python3 .*hello\.py .*kitty")
        self.assertEqual(1, len(CAPTURE))
        argv, _, kwargs = CAPTURE[0]
        self.assertTrue(argv[0].endswith("kitty"))
        self.assertEqual(argv[1:3], ["-e", "bash"])
        script = argv[-1]
        self.assertIn('cd "$(dirname --', script)
        self.assertRegExpIn(script, r"hello\.py")
        self.assertIn("python3", script)
        self.assertIn("  stdedit · run", script)
        self.assertIn("[Enter] close", script)
        self.assertIn("[r] rerun", script)
        self.assertNotIn("[e] edit", script)
        self.assertIn("finished (exit '\"$rc\"')", script)
        self.assertIn("read -n 1 -s -r", script)
        self.assertNotIn("PIPESTATUS", script)
        self.assertRegExpIn(script, r"\{ python3 -u .*hello\.py; \} 2>&1")
        self.assertNotIn("python3 -c", script)
        self.assertTrue(kwargs.get("start_new_session"))

    def test_run_python_uses_pty_wrapper(self):
        ok, status = runner.run_file(
            "proj/hello.py",
            _which=make_which({"python3", "kitty"}),
            _popen=fake_popen, env={}, pty=True)
        self.assertTrue(ok, status)
        script = CAPTURE[0][0][-1]
        self.assertIn("script -qec 'python3 -u ", script)
        self.assertIn("' /dev/null; } 2>&1", script)
        self.assertNotIn("PIPESTATUS", script)
        self.assertNotIn("python3 -c", script)

    def test_no_terminal_reports_reason(self):
        ok, status = runner.run_file(
            "a.py", _which=make_which({"python3"}), _popen=fake_popen)
        self.assertFalse(ok)
        self.assertIn("No terminal emulator", status)
        self.assertEqual([], CAPTURE)

    def test_compile_script_cleans_up_temp_binary(self):
        runner.run_file(
            "main.c", _which=make_which({"gcc", "kitty"}),
            _popen=fake_popen, env={})
        argv, _, _ = CAPTURE[0]
        command = argv[-1]
        outs = set(re.findall(r"/tmp/stdedit-run-\d+", command))
        self.assertEqual(1, len(outs), outs)
        out = outs.pop()
        self.assertIn(f"-o {out}", command)
        self.assertIn(f"rm -f {out}", command)

    def test_html_serves_locally_and_opens_default_browser(self):
        ok, status = runner.run_file(
            "/tmp/page.html",
            _which=make_which({"kitty", "python3", "xdg-open"}),
            _popen=fake_popen, env={})
        self.assertTrue(ok, status)
        self.assertRegex(status,
                         r"Running: http://127\.0\.0\.1:\d+/page\.html \(kitty\)")
        self.assertEqual(1, len(CAPTURE))
        argv, _, kwargs = CAPTURE[0]
        self.assertEqual(argv[1:3], ["-e", "bash"])
        script = argv[-1]
        self.assertRegex(script, r"python3 -m http\.server --bind 127\.0\.0\.1 \d+"
                                 r" --directory /tmp & server_pid=\$!;")
        self.assertRegExpIn(script, r"xdg-open http://127\.0\.0\.1:\d+/page\.html")
        self.assertRegExpIn(script, r"/dev/tcp/127\.0\.0\.1/\d+")
        self.assertIn("server_pid=$!;", script)
        self.assertIn("wait $server_pid; trap - INT", script)
        self.assertIn("trap 'kill $server_pid 2>/dev/null' INT; ", script)
        self.assertNotIn("script -qec", script)
        self.assertTrue(kwargs.get("start_new_session"))

    def test_markdown_and_svg_also_serve_in_browser(self):
        for fname, keep in (("/tmp/readme.md", "readme.md"),
                            ("/tmp/pic.svg", "pic.svg"),
                            ("/tmp/view.xhtml", "view.xhtml")):
            CAPTURE.clear()
            ok, _status = runner.run_file(
                fname, _which=make_which({"kitty", "xdg-open"}),
                _popen=fake_popen, env={})
            self.assertTrue(ok, fname)
            script = CAPTURE[0][0][-1]
            self.assertIn(f"http://127.0.0.1:", script, fname)
            self.assertIn(f"/{keep}", script, fname)

    def test_web_falls_back_to_open_when_xdg_open_missing(self):
        ok, _status = runner.run_file(
            "/tmp/page.html",
            _which=make_which({"kitty", "python3", "open"}),
            _popen=fake_popen, env={})
        self.assertTrue(ok)
        script = CAPTURE[0][0][-1]
        self.assertIn("open http://127.0.0.1:", script)
        self.assertNotIn("xdg-open", script)

    def test_web_without_browser_opener_reports_reason(self):
        ok, status = runner.run_file(
            "/tmp/page.html", _which=make_which({"kitty", "python3"}),
            _popen=fake_popen, env={})
        self.assertFalse(ok)
        self.assertIn("no browser opener found", status)
        self.assertEqual([], CAPTURE)

    def test_web_still_requires_a_terminal(self):
        ok, status = runner.run_file(
            "/tmp/page.html", _which=make_which({"python3", "xdg-open"}),
            _popen=fake_popen, env={})
        self.assertFalse(ok)
        self.assertIn("No terminal emulator found", status)

    def test_web_url_encodes_space_in_filename(self):
        ok, _status = runner.run_file(
            "/tmp/my page.html",
            _which=make_which({"kitty", "xdg-open"}),
            _popen=fake_popen, env={})
        self.assertTrue(ok)
        script = CAPTURE[0][0][-1]
        self.assertIn("my%20page.html", script)
        self.assertIn("/my%20page.html", script)

    def test_web_popen_error_reports_friendly_status(self):
        def boom(_argv, *a, **k):
            raise OSError("no DISPLAY")
        ok, status = runner.run_file(
            "/tmp/page.html",
            _which=make_which({"kitty", "xdg-open"}), _popen=boom)
        self.assertFalse(ok)
        self.assertIn("Could not launch terminal", status)
        self.assertIn("no DISPLAY", status)

    def test_run_image_opens_xdg_open_directly(self):
        ok, status = runner.run_file(
            "/tmp/pic.png", _which=make_which({"xdg-open"}),
            _popen=fake_popen, env={})
        self.assertTrue(ok, status)
        self.assertEqual("Opening: pic.png (xdg-open)", status)
        self.assertEqual(1, len(CAPTURE))
        argv, _, kwargs = CAPTURE[0]
        self.assertEqual(argv, ["xdg-open", "/tmp/pic.png"])
        self.assertTrue(kwargs.get("start_new_session"))

    def test_run_image_needs_no_terminal(self):
        ok, status = runner.run_file(
            "pic.png", _which=make_which({"xdg-open"}),
            _popen=fake_popen, env={})
        self.assertTrue(ok, status)
        argv, _, _ = CAPTURE[0]
        self.assertNotIn("bash", argv)

    def test_run_image_falls_back_to_open(self):
        ok, status = runner.run_file(
            "pic.png", _which=make_which({"open"}),
            _popen=fake_popen, env={})
        self.assertTrue(ok, status)
        self.assertIn("(open)", status)
        self.assertEqual(["open", os.path.abspath("pic.png")],
                         CAPTURE[0][0])

    def test_run_image_without_browser_opener_reports_reason(self):
        ok, status = runner.run_file(
            "pic.png", _which=make_which({"kitty"}),
            _popen=fake_popen, env={})
        self.assertFalse(ok)
        self.assertIn("no browser opener found", status)
        self.assertEqual([], CAPTURE)

    def test_run_image_popen_error_reports_friendly_status(self):
        def boom(_argv, *a, **k):
            raise OSError("no DISPLAY")
        ok, status = runner.run_file(
            "pic.png", _which=make_which({"xdg-open"}), _popen=boom)
        self.assertFalse(ok)
        self.assertIn("Could not open in browser", status)
        self.assertIn("no DISPLAY", status)

    def test_run_each_image_extension_opens_in_browser(self):
        for ext in ("png", "jpg", "jpeg", "gif", "webp", "bmp", "ico", "tif",
                    "tiff", "heic", "heif", "avif", "ppm", "pgm", "pbm"):
            CAPTURE.clear()
            ok, status = runner.run_file(
                f"/tmp/pic.{ext}", _which=make_which({"xdg-open"}),
                _popen=fake_popen, env={})
            self.assertTrue(ok, (ext, status))
            self.assertEqual(["xdg-open", f"/tmp/pic.{ext}"],
                             CAPTURE[0][0], ext)

    def test_missing_runtime_cascades_to_status(self):
        ok, status = runner.run_file(
            "Main.java", _which=make_which({"kitty"}), _popen=fake_popen)
        self.assertFalse(ok)
        self.assertIn("Runtime 'java' not found", status)

    def test_empty_path_is_safe(self):
        ok, status = runner.run_file("", _which=make_which({"kitty"}),
                                     _popen=fake_popen)
        self.assertFalse(ok)

    def test_popen_error_reports_friendly_status(self):
        def boom(_argv, *a, **k):
            raise OSError("no DISPLAY")
        ok, status = runner.run_file(
            "a.py", _which=make_which({"python3", "kitty"}), _popen=boom)
        self.assertFalse(ok)
        self.assertIn("Could not launch terminal", status)
        self.assertIn("no DISPLAY", status)

    def assertRegExpIn(self, text, pattern):
        self.assertIsNotNone(re.search(pattern, text), (pattern, text))


class OpenInBrowserTests(unittest.TestCase):
    def setUp(self):
        CAPTURE.clear()

    def test_prefers_xdg_open_over_open(self):
        ok, status = runner.open_in_browser(
            "/tmp/pic.png", _which=make_which({"xdg-open", "open"}),
            _popen=fake_popen)
        self.assertTrue(ok, status)
        self.assertEqual(["Opening:", "pic.png", "(xdg-open)"],
                         status.split())
        self.assertEqual(["xdg-open", "/tmp/pic.png"],
                         CAPTURE[0][0])

    def test_falls_back_to_open(self):
        ok, status = runner.open_in_browser(
            "/tmp/pic.png", _which=make_which({"open"}), _popen=fake_popen)
        self.assertTrue(ok, status)
        self.assertEqual(["open", "/tmp/pic.png"], CAPTURE[0][0])

    def test_no_opener_reports_reason(self):
        ok, status = runner.open_in_browser(
            "/tmp/pic.png", _which=make_which({"kitty"}), _popen=fake_popen)
        self.assertFalse(ok)
        self.assertIn("no browser opener found", status)
        self.assertEqual([], CAPTURE)

    def test_popen_error_reports_friendly_status(self):
        def boom(_argv, *a, **k):
            raise OSError("no DISPLAY")
        ok, status = runner.open_in_browser(
            "/tmp/pic.png", _which=make_which({"xdg-open"}), _popen=boom)
        self.assertFalse(ok)
        self.assertIn("Could not open in browser", status)
        self.assertIn("no DISPLAY", status)

    def test_uses_absolute_path_and_blocks_nothing(self):
        ok, _status = runner.open_in_browser(
            "sub/dir/pic.png", _which=make_which({"xdg-open"}),
            _popen=fake_popen)
        self.assertTrue(ok)
        argv, _, kwargs = CAPTURE[0]
        self.assertTrue(os.path.isabs(argv[1]), argv)
        self.assertTrue(argv[1].endswith("/sub/dir/pic.png"), argv)
        self.assertTrue(kwargs.get("start_new_session"))


class RunCurrentFileTests(unittest.TestCase):
    """tui._run_current_file: auto-save-then-run wiring."""

    def setUp(self):
        from stdedit import tui
        self.tui = tui
        self.orig_run_file = tui.runner.run_file
        self.runs = []
        self.saves = []
        tui.runner.run_file = self._fake_run

    def tearDown(self):
        self.tui.runner.run_file = self.orig_run_file

    def _fake_run(self, path):
        self.runs.append(path)
        return True, f"Running: {path}"

    def make_buf(self, filename, modified):
        class FakeBuf:
            pass
        buf = FakeBuf()
        buf.filename = filename
        buf.modified = modified
        def save(path=None):
            self.saves.append(path)
            buf.modified = False
        buf.save = save
        return buf

    def test_no_filename_reports_reason(self):
        status = self.tui._run_current_file(self.make_buf(None, False))
        self.assertIn("Nothing to run", status)
        self.assertEqual([], self.runs)
        self.assertEqual([], self.saves)

    def test_autosaves_then_runs_when_modified(self):
        status = self.tui._run_current_file(
            self.make_buf("/tmp/a.py", True))
        self.assertEqual(["/tmp/a.py"], self.runs)
        self.assertEqual([None], self.saves)
        self.assertTrue(status.startswith("Running:"))

    def test_runs_without_saving_when_clean(self):
        status = self.tui._run_current_file(
            self.make_buf("/tmp/a.py", False))
        self.assertEqual(["/tmp/a.py"], self.runs)
        self.assertEqual([], self.saves)
        self.assertTrue(status.startswith("Running:"))

    def test_save_error_blocks_run(self):
        buf = self.make_buf("/tmp/b.py", True)
        def save(path=None):
            raise OSError("disk full")
        buf.save = save
        status = self.tui._run_current_file(buf)
        self.assertIn("Could not save before running", status)
        self.assertIn("disk full", status)
        self.assertEqual([], self.runs)


class DecorationTests(unittest.TestCase):
    """The spawned terminal shows a plain header + passthrough output."""

    def setUp(self):
        CAPTURE.clear()

    def test_plain_header_names_file_and_runtime(self):
        s = runner._build_script(
            "/tmp/run/sample.py", "python3 /tmp/run/sample.py",
            runtime="python3", icon="", pty=False)
        self.assertIn("  stdedit · run sample.py (Python 3)", s)
        self.assertIn("sample.py", s)
        for forbidden in ("┌", "│", "├", "└", "▶", "file: ", "cmd: ",
                          "YUKI — Python 3"):
            self.assertNotIn(forbidden, s)

    def test_header_keeps_icon_when_given(self):
        s = runner._build_script(
            "/tmp/a.py", "python3 /tmp/a.py", runtime="python3", icon="🐍",
            pty=False)
        self.assertIn("  stdedit · run 🐍 a.py (Python 3)", s)

    def test_title_osc_carries_basename_and_runtime(self):
        s = runner._build_script(
            "/tmp/my.py", "python3 /tmp/my.py", runtime="python3", icon="",
            pty=False)
        self.assertIn("\\033]0;%s\\007", s)
        self.assertIn("YUKI — run my.py (Python 3)", s)
        self.assertTrue(s.startswith("printf "), s)

    def test_tricky_filenames_are_escaped_in_emitted_lines(self):
        s = runner._build_script(
            "/tmp/odd 'name' (x).py", "python3 /tmp/odd 'name' (x).py",
            runtime="python3", icon="", pty=False)
        self.assertIn("'\\''", s)
        self.assertNotIn("syntax error", s)

    def test_colors_active_by_default(self):
        s = runner._build_script(
            "/tmp/a.py", "python3 /tmp/a.py", runtime="python3", icon="",
            pty=False)
        self.assertIn("\\x1b[32m", s)
        self.assertIn("\\x1b[31m", s)
        self.assertIn("\\x1b[0m", s)

    def test_no_color_drops_sgr_keeps_header(self):
        s = runner._build_script(
            "/tmp/a.py", "python3 /tmp/a.py", runtime="python3", icon="",
            colors=False, pty=False)
        self.assertIn("  stdedit · run a.py (Python 3)", s)
        self.assertIn("YUKI — run", s)
        self.assertIn("  stdedit — ✔ finished", s)
        self.assertNotIn("\\x1b[32m", s)
        self.assertNotIn("\\x1b[31m", s)
        self.assertNotIn("\\x1b[7m", s)

    def test_raw_script_matches_plain_template(self):
        s = runner._build_script(
            "/tmp/a.py", "python3 /tmp/a.py", runtime="python3", icon="",
            raw=True, pty=False)
        for forbidden in ("┌", "╔", "▶", "\\033]0;", "\\x1b["):
            self.assertNotIn(forbidden, s)
        self.assertIn('cd "$(dirname --', s)
        self.assertIn('echo "[YUKI] finished (exit $rc) — press Enter to close"', s)
        self.assertIn("read -r _", s)

    def test_run_file_respects_raw_env(self):
        ok, _status = runner.run_file(
            "proj/a.py", _which=make_which({"python3", "kitty"}),
            _popen=fake_popen, env={"STDEDIT_RUN_RAW": "1"})
        self.assertTrue(ok)
        script = CAPTURE[0][0][-1]
        self.assertNotIn("╔", script)
        self.assertNotIn("▶", script)

    def test_run_file_respects_no_color_env(self):
        ok, _status = runner.run_file(
            "proj/a.py", _which=make_which({"python3", "kitty"}),
            _popen=fake_popen, env={"NO_COLOR": "1"})
        self.assertTrue(ok)
        script = CAPTURE[0][0][-1]
        self.assertNotIn("\\x1b[32m", script)
        self.assertNotIn("\\x1b[31m", script)
        self.assertNotIn("╔", script)
        self.assertIn("✔ finished", script)

    def test_run_file_omits_icon_when_disabled(self):
        glyph = icons.icon_for_file("proj/a.py", True)
        self.assertTrue(glyph)
        ok, _status = runner.run_file(
            "proj/a.py", _which=make_which({"python3", "kitty"}),
            _popen=fake_popen, env={"STDEDIT_ICONS": "0"})
        self.assertTrue(ok)
        script = CAPTURE[0][0][-1]
        self.assertNotIn(glyph, script)

    def test_run_starts_on_a_blank_line(self):
        s = runner._build_script(
            "/tmp/a.py", "python3 -u /tmp/a.py", runtime="python3", icon="",
            pty=False)
        self.assertIn("  stdedit · run a.py (Python 3)'\n", s)
        self.assertIn("echo\n  { python3 -u /tmp/a.py; } 2>&1", s)

    def test_built_script_passes_output_through_directly(self):
        s = runner._build_script(
            "/tmp/a.py", "python3 -u /tmp/a.py", runtime="python3", icon="",
            pty=False)
        self.assertIn("{ python3 -u /tmp/a.py; } 2>&1", s)
        self.assertIn("rc=$?", s)
        self.assertNotIn("PIPESTATUS", s)
        self.assertNotIn("python3 -c", s)

    def test_pty_wrap_single_quotes_the_command(self):
        wrapped = runner._pty_wrap("python3 -u '/a b.py'")
        self.assertTrue(wrapped.startswith("script -qec '"), wrapped)
        self.assertTrue(wrapped.endswith(" /dev/null"), wrapped)
        self.assertIn("'\\''", wrapped)
        self.assertNotIn("syntax error", wrapped)

    def test_built_script_pty_path_wraps_command_once(self):
        s = runner._build_script(
            "/tmp/a.py", "python3 -u /tmp/a.py", runtime="python3", icon="",
            pty=True)
        self.assertEqual(1, s.count("script -qec '"), s)
        self.assertIn("{ script -qec 'python3 -u /tmp/a.py' /dev/null; } "
                      "2>&1", s)
        self.assertNotIn("PIPESTATUS", s)
        self.assertNotIn("python3 -c", s)

    def test_built_script_summary_and_keys(self):
        s = runner._build_script(
            "/tmp/a.py", "python3 -u /tmp/a.py", runtime="python3", icon="",
            pty=False)
        self.assertIn("— [r] rerun · [Enter] close", s)
        self.assertIn("[Enter] close", s)
        self.assertIn("[r] rerun", s)
        self.assertIn("finished (exit '\"$rc\"')", s)
        self.assertIn("r|R) continue", s)
        self.assertNotIn("e|E)", s)
        self.assertNotIn("command -v stdedit", s)
        self.assertNotIn("[e] edit", s)
        self.assertNotIn("run_once", s)
        self.assertIn("read -n 1 -s -r k", s)
        self.assertNotIn("PIPESTATUS", s)
        for forbidden in ("┌", "│", "├", "└", "▶"):
            self.assertNotIn(forbidden, s)

    def test_built_script_summary_honors_no_color(self):
        s = runner._build_script(
            "/tmp/a.py", "python3 -u /tmp/a.py", runtime="python3", icon="",
            colors=False, pty=False)
        self.assertIn("  stdedit — ✔ finished (exit '\"$rc\"')", s)
        self.assertIn("[r] rerun", s)
        self.assertIn("[Enter] close", s)
        self.assertNotIn("\\x1b[32m", s)
        self.assertNotIn("\\x1b[31m", s)
        self.assertNotIn("\\x1b[7m", s)

    def test_compile_script_keeps_temp_binary_cleanup(self):
        s = runner._build_script(
            "/tmp/long/dir/name/prog.c",
            "gcc /tmp/long/dir/name/prog.c -o /tmp/stdedit-run-4242 "
            "&& /tmp/stdedit-run-4242", runtime="gcc", icon="", pty=False)
        self.assertIn("-o /tmp/stdedit-run-4242 && /tmp/stdedit-run-4242", s)
        self.assertIn("gcc /tmp/long/dir/name/prog.c -o /tmp/stdedit-run-4242 "
                      "&& /tmp/stdedit-run-4242; } 2>&1", s)
        self.assertRegex(s, r"trap 'rm -f /tmp/stdedit-run-\d+ 2>/dev/null' EXIT")


if __name__ == "__main__":
    unittest.main()