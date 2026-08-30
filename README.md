<!-- Update this file after every feature/keybind change -->

# YUKI

Zero-dependency terminal text editor. Python stdlib only.

![Python](https://img.shields.io/badge/python-%3E%3D3.9-blue)
![Zero Deps](https://img.shields.io/badge/deps-zero-brightgreen)
![Tests](https://img.shields.io/badge/tests-788-passing)
![Version](https://img.shields.io/badge/version-0.1.0-orange)

## Quick Start

```bash
git clone https://github.com/the-priyankaa/Demogorgon-.git
```
```
cd core
```
```
make install          # creates venv + symlinks to ~/.local/bin
stdedit myfile.py     # or: yuki myfile.py
```

Run without installing:

```bash
PYTHONPATH=src python3 -m stdedit.main myfile.py
```

## Features

**Core Editing**
- Line-based text buffer with cursor movement and scrolling
- Undo / redo (memory-bounded: 500 snapshots / 32 MB cap)
- Selection (character, word, line, select-all, shift-click, drag)
- Clipboard (internal + system via `wl-copy` / `xclip` / `pbcopy`)
- Auto-close brackets `(` `{` `[` and quotes `"` `'`
- Smart auto-indent per language
- Tab / space conversion with configurable width
- Find (`Ctrl-F`) and Replace All (`Ctrl-R`) with live highlighting
- Large file support (8 MB+): memory-mapped reads, compact byte-array storage

**Syntax Highlighting** — 17 languages: Python, JavaScript, TypeScript, HTML, CSS, C, C++, Java, Rust, Go, JSON, YAML, Markdown, Shell, SQL, XML, plaintext

**Themes** — 15 built-in color themes: default, Monokai, Dracula, Solarized Dark, Solarized Light, Nord, One Dark, Tokyo Night, Gruvbox Dark, Catppuccin Mocha, Rose Pine, GitHub Light, Zenburn, Everforest, Ayu

**Panels & Overlays**
- Welcome Dashboard (opens with no file/project): YUKI front panel — Find File, Open Folder (native dialog), New File (folder-first), Recent Files (multi-file picker), Extensions (discovery-only listing), Restore Session, Settings, Help and Quit; `Ctrl+1` returns to YUKI from any overlay
- File Explorer (`Ctrl-E`): tree view, search, create, delete, rename, copy path
- Source Control (`Ctrl-G`): stage, unstage, commit, push, pull, branch switch, stash
- Quick Open (`Ctrl-O`): fuzzy file search — background indexing **and** background result matching, home-directory search from the dashboard, recent-files fallback. Painted as an overlay over the live screen (the real dashboard or the editor) with a `|` caret inside the search input, so there is never a blank page behind the box. Results rank **nearest files first** (shallower paths beat deeper ties), with app-config / hidden dirs (`.config`, `.ssh`, `Library`, `AppData`, …) matched last but still searchable — so `EDA.py` under `~/Projects` beats `~/.config/…/EDA.py`, and config files are never lost
- Diff Viewer: scrollable unified diff with syntax colors
- Image Viewer: opens automatically when you open an image file — PNG / BMP / PPM render in-terminal via half-block truecolor (any 256-color terminal); JPEG / GIF / WebP / HEIC / SVG and more stream full-screen through the Kitty / iTerm2 inline-graphics protocol (raw bytes, terminal-native decoding)
- Settings (`Ctrl-P`): auto-save mode, theme, font family, suggestions (off / auto-suggest / AI inline)
- Help (`Ctrl-H` / `F1`): scrollable keybinding reference

**Git & GitHub**
- Branch detection, status counts, ahead/behind upstream- Stage / unstage / commit / push / pull / stash
- Branch listing and switching
- Issues (list / close / reopen) via `gh` CLI
- Pull requests (list / checkout / merge) via `gh` CLI

**Auto-suggest & AI Completions**
- Local suggestion popup (VS Code-style): auto-triggers while typing an
  identifier and shows the keyword pool of the current file type plus
  identifiers already in the open file, ranked by keyword-priority then
  frequency. Each language has its own keyword set (Python, JS, Go, C++,
  HTML tags, CSS properties, XML, …), so `.py`, `.js` and `.html` files
  suggest different keywords. `Tab` / `Enter` insert the highlighted
  candidate, `Esc` dismisses, `^`/`v` move the selection. Select
  **Auto-suggest** in Settings (`Ctrl-P`), on top of the default
  **Suggestions: off**.
- No popup or AI ghost is ever offered while the cursor is inside a
  double-quoted string (e.g. `name = "ja"` stays quiet), so string literal
  content never triggers suggestions.
- Codeium AI inline ghost text (opt-in): dim suggestion shown at the cursor
  after ~0.35s of idle typing; `Tab` accepts, `Esc` dismisses. Select
  **AI inline (Codeium)** in Settings (`Ctrl-P`, default is off via
  **Suggestions: off**).
  Store your Codeium personal API key at
  `~/.config/stdedit/codeium_key`; suggestions silently skip when the key
  is missing or the API is unreachable.

**Run Current File** (`F5` / `Ctrl-Enter`)
- Launches the file in an external terminal (kitty, gnome-terminal, …) with
  the right runtime per extension (Python, Node/tsx, gcc/g++, rustc, go, …)
- Output (stdout + stderr) is indented to align inside the boxed frame, with
  long `cmd:`/`file:` lines wrapped to indented continuation rows
- A full-width bottom bar shows the exit code (green `✔` / red `✖`) and what
  to do next: `r` rerun, `Enter` close
- Interactive/curses programs (htop, vim) don't render under the output pipe

**Extensions** — Plugin system with `setup(api)` / `register(api)` lifecycle, 3 search paths, isolated error handling

**Performance**
- Quick Open never blocks editing: the file index and the per-keystroke result
  scoring both run on background worker threads, so typing stays smooth even
  on huge search roots.
- The index is bounded (`MAX_FILES` = 40 000) with lowercase forms cached at
  scan time — no per-keystroke allocation or re-lowercasing. Home-directory
  searches over the cap show `Index capped (40k files) — type more
  specifically`.
- Status hints show live progress: `Searching... (N files indexed)`,
  `Updating results...`, `Press Enter to open typed path`.

**Zero Dependencies** — Every import is Python stdlib. Verified by `make proof`.

## Keyboard Shortcuts

### Editing

```
characters          type to insert text at the cursor
Enter               new line (auto-indents per language)
Tab                 indent (width adapts to the language)
Backspace / Del     delete character
< > ^ v             move cursor
Home / End          jump to line start / end
( { [               auto-close bracket pairs
) } ]               skip closer / dedent on block close
" '                 auto-close quotes
Ctrl-F              find text in the file
Ctrl-R              replace all occurrences
```

### Auto-suggest

```
typing              while typing an identifier, matching keywords and
                    document identifiers appear in a popup below the cursor
                    (no popup appears inside double-quoted strings)
^ / v               move popup selection (while the popup is open)
Tab / Enter         insert the highlighted suggestion
Esc                 dismiss the popup / inline ghost text
```

### Selection & Clipboard

```
Ctrl-A              select all
Ctrl-Space          start / stop selection ([SELECT] in status)
                    (arrow keys extend the selection while it is active)
Ctrl-C              copy selection
Ctrl-X              cut selection
Ctrl-V              paste (system + internal clipboard)
```

### History & Files

```
Ctrl-Z              undo
Ctrl-Y              redo
Ctrl-S              save current file
Ctrl-P              settings / preferences
Ctrl-O              quick open — fuzzy file search
Ctrl-Q              quit (opens a confirmation dialog:
                    Enter/Space confirm the focused button,
                    s/d/q save / discard / cancel shortcuts)
```

### Image Viewer

```
auto                opening an image file shows the viewer immediately
                    (q exits to the raw byte buffer; Ctrl-\ toggles back)
q / Esc             leave the viewer (edit / inspect raw bytes)
+ / -               zoom in / zoom out
Arrow keys          pan the image
PageUp / PageDown   pan up / down in larger steps
r                   reset zoom + pan
Home                fit the whole image
End                 100% zoom
v                   full-screen passthrough stream (any format) — the
                    terminal's own decoder renders the raw file, Enter returns
Ctrl-Q              quit the editor
```

### File Tree (Ctrl-E panel)

```
Ctrl-E              open / focus the file tree
^ v                 move selection
< >                 collapse / expand folder (<..> climbs up)
Enter               open file / expand folder / go up on <..>
/                   search files and folders (Esc to cancel)
Esc                 close the file tree
h                   show / hide dotfiles
n                   new file (opens it for editing)
N                   new folder in selected folder
d                   delete file / folder (with confirmation)
r                   rename file / folder
y                   copy absolute path to clipboard
Y                   copy relative path to clipboard
O                   pick project root via system dialog
R                   reveal root in system file manager
Tab / Esc           focus the editor
```

### Git Status

```
status bar          shows branch name and change counts
                    +N added  ~N modified  -N deleted  !N untracked
automatic           refreshes every 2 seconds (no manual trigger)
```

### Source Control (Ctrl-G panel)

```
Ctrl-G              open / close source control panel
Up / Down           move selection
c                   focus commit message box
Enter               commit (when message box focused)
Esc                 cancel commit / defocus panel
s                   stage selected file
u                   unstage selected file
S                   stage all changes
U                   unstage all changes
d                   show diff for selected file
p                   push
P                   pull
R                   refresh status
b                   switch branch
I                   list issues (o:close r:reopen)
M                   list PRs (c:checkout m:merge)
Tab / Ctrl-G / Esc  focus the editor
```

### Diff Viewer

```
d / Space           page down
u                   page up
Up / Down           scroll one line
g / G               jump to top / bottom
q / Esc             close diff view
```

### Quick Open (Ctrl-O overlay)

```
type to filter      fuzzy search across project files; a `|` caret sits
                    inside the search input right after what you've typed
Up / Down           move selection
Enter               open selected file
Esc / Ctrl-O        close quick open
Backspace           delete last query character
Ctrl+1              return to the YUKI dashboard
                    (Esc and empty-query Enter return to the dashboard too
                    when the search was opened from it)
```

The overlay is drawn over the live base frame — the YUKI dashboard when
launched from `F`/`D`, otherwise the editor — and repaints only when the
query, selection or results actually change (dirty-frame skip), so there is
no flicker while typing and no full-screen redraw churn.

### Welcome Dashboard overlays

```
Enter/Space         activate the highlighted tile
E                   Extensions — lists discovered extensions without loading
                    them; ↑/↓ select, Esc / Ctrl+1 return to the dashboard
N                   New File — folder-first: select a directory with Enter,
                    type the filename, Enter creates and opens the real file
--------            inside the New File overlay --------
Enter               enter the selected directory / create the typed file
Tab                 auto-complete the filename
Backspace           delete the last char; with an empty name, go up a folder
Up / Down           move the selection (selection stays on screen)
Esc                 return to the dashboard
Ctrl+1              return to YUKI
```

### Settings (Ctrl-P panel)

```
Ctrl-P              open / close settings panel
Up / Down           navigate settings (section headers too)
Space / Enter       toggle a setting, or expand/collapse a section
▸ / ▾               collapsed / expanded section header
click header        expand / collapse a section
click setting       select it (Space to toggle)
q / Esc / Ctrl-P    close settings panel
Ctrl+1              return to the YUKI dashboard
```
`auto-save`, `theme`, and `font family` are collapsible dropdown sections (all collapsed when opened) — `Space`/`Enter` or a click on a section header expands or collapses it. Only one section stays open: opening or navigating to another closes the current one. Within a section, `Space` on any option activates it and turns the others off.

### Mouse

```
click               position cursor
double-click        select word
triple-click        select line
drag                select text
Shift+click         extend selection
scroll wheel        scroll up / down
```

### Terminal & Prompts

```
terminal paste      bracketed paste inserts multi-line text
typed prompts       Enter confirms, Esc cancels
prompt Tab          autocomplete file paths
prompt Backspace    edits the text (new file/folder, O fallback)
icons               Nerd Font glyphs (e.g. MesloLGS NF);
                    disable with STDEDIT_ICONS=0

(prompts appear for n / O and the O path fallback)
```

### Help

```
Ctrl-H or F1        open / close this guide
Up / Down, PgUp/Dn  scroll this guide
q / Esc / Enter     close this guide
Ctrl+1              return to the YUKI dashboard
```

## CLI Usage

```
stdedit [file] [options]
```

Running `stdedit` with no file (and no `--project`) opens the **welcome
dashboard**: ↑/↓ navigate its options, Enter/Space activates the selected
one, or press the key shown on each tile (`F` Find File, `O` Open Folder,
`N` New File, `R` Recent Files, `E` Extensions, `S` Restore Session, `C`
Settings, `H`/F1 Help, `Q`/Ctrl-Q quit). `R` opens the **Recent Files**
picker — a list of your most recently opened files (that still exist); ↑/↓
choose, `Enter` opens it, `Esc` returns to the dashboard. `S` restores the
most recent file directly. `O` opens a native system folder dialog via
`zenity` (or `kdialog`); without one it falls back to browsing your home
directory. `N` opens the folder-first **New File** picker: enter the target
directory, type a name, and `Enter` creates the file and opens it in the
editor (`Esc` abandons the overlay). `E` lists **Extensions** discovered on
your search paths without importing any of them (`Esc` / `Ctrl+1` closes).
`F` Find File, `D` Open Folder, `R` Recent Files, `C` Settings and
`H`/F1 Help are all painted **over the live dashboard** — the YUKI screen
stays behind the box instead of a blank editor page, and searching, typing
and scrolling repaint only what changed (no screen shutter once the overlay
settles; the RAM meter works on Linux **and** macOS/BSD). From any dashboard
overlay — and from Quick Open, Settings and Help — `Ctrl+1` returns to the
YUKI dashboard.

| Option | Description |
|--------|-------------|
| `file` | File to open (or directory to open as project) |
| `--project DIR` | Folder the file tree is rooted at |
| `--tree` | Open with the file explorer tree visible and focused, file revealed |
| `--tab-size INT` | Tab width in spaces (default: 4) |
| `--tabs` | Use literal tab characters instead of spaces |
| `--large-file-mb INT` | Disable undo snapshots at this size (default: 8 MB) |
| `--extension NAME` | Load one external extension by name (repeatable) |
| `--extension-file PATH` | Load one external extension file (repeatable) |
| `--all-extensions` | Load every discovered extension |
| `--list-extensions` | List discovered extensions and exit |

## Install with carl

```bash
make install        # create venv, pip install editable, symlink to ~/.local/bin
make uninstall      # remove symlinks
make deps           # check optional OS helpers (zenity, xdg-open, etc.)
make deps-fix       # auto-install missing helpers via detected package manager
```

`carl` supports: apt-get, dnf, yum, pacman, zypper, apk, brew.

## Configuration

| File | Purpose |
|------|---------|
| `~/.config/stdedit/settings.json` | Editor settings (auto-save, theme, font family, auto-suggest toggles) |
| `~/.config/stdedit/recent.json` | Recently opened files (max 50) |
| `~/.config/stdedit/codeium_key` | Codeium personal API key (AI inline suggestions) |

**Auto-save modes:** off (default), on idle (5s), periodic (30s), on every edit

**Auto-suggest toggles:** the SUGGESTIONS section is a three-way radio
group — exactly one option is active. `suggestions_off` (default on →
suggestions disabled by default), `suggestions_on` (local keyword/identifier
popup), and `codeium_on` (dim AI inline ghost text shown after a short pause
while typing). Switching one option clears the others. Keyword pools are
per-file-type (HTML tags, CSS properties, Python keywords, …), and neither
the popup nor the AI ghost appears while the cursor is inside a
double-quoted string.

**Themes:** default, Monokai, Dracula, Solarized Dark, Solarized Light, Nord, One Dark, Tokyo Night, Gruvbox Dark, Catppuccin Mocha, Rose Pine, GitHub Light, Zenburn, Everforest, Ayu. On 256-color terminals each theme uses its true palette; fewer colors fold tones to the closest base color.

**Font family:** Detects installed monospace fonts via `fc-list` and tries to switch terminal font via OSC 50 escape sequences (works in xterm, Konsole, iTerm2; best-effort in other terminals).

## Extensions

### Write an extension

Create a `.py` file in any of these paths:
- `$STDEDIT_EXTENSIONS/`
- `.stdedit/extensions/`
- `~/.config/stdedit/extensions/`

```python
# my_extension.py
def setup(api):
    api.extension("my-ext", "1.0", "Does something cool")

    def on_save(editor):
        # your logic here
        pass

    api.bind_key("\x12", lambda editor: print("Ctrl-R pressed"))  # Ctrl-R
    api.add_status(lambda editor: "custom status text")
```

### API methods

| Method | Description |
|--------|-------------|
| `api.extension(name, version, description)` | Register extension metadata |
| `api.bind_key(key, callback)` | Bind a key to a callback |
| `api.add_command(name, callback)` | Register a named command |
| `api.add_status(callback)` | Add text to the status bar |
| `api.on_startup(callback)` | Run code when editor starts |
| `api.on_shutdown(callback)` | Run code when editor exits |

### Example extensions

| Extension | Key | Description |
|-----------|-----|-------------|
| `word_count.py` | (status only) | Live word/char count in status bar |
| `reverse_line.py` | Ctrl-R | Reverses the current line |
| `vim_command.py` | Ctrl-B | Toggles Vim-mode status indicator |

## Development

### Makefile commands

| Command | Description |
|---------|-------------|
| `make run FILE=file.py` | Run the editor |
| `make test` | Run all tests (628 tests) |
| `make proof` | Verify zero dependencies |
| `make clean` | Remove `__pycache__` and artifacts |

### Architecture

- **UI-agnostic core** — `Buffer` has no curses dependency, fully unit-testable
- **Graceful degradation** — All external tools (clipboard, git, gh, fc-list, zenity) timeout and return safe defaults
- **Bounded memory** — Undo capped at 500 snapshots / 32 MB; large files use mmap-backed reads
- **Extension isolation** — Each extension imported in its own namespace; failures don't crash the editor
- **Subprocess-only integration** — git, gh, clipboard tools, font detection all use `subprocess.run` with short timeouts

## Project Structure

```
src/stdedit/
├── main.py              CLI entry point (argparse)
├── buffer.py            Core text buffer engine (UI-agnostic)
├── tui.py               Curses front-end (main event loop)
├── undo.py              Memory-bounded snapshot undo/redo
├── clipboard.py         System clipboard (wl-copy, xclip, pbcopy)
├── completion.py        Path tab-completion
├── diff_viewer.py       Scrollable unified-diff overlay
├── explorer.py          File tree explorer panel
├── filemanager.py       System file-manager integration
├── font_detect.py       Monospace font detection (fc-list)
├── git.py               Git operations via subprocess
├── git_panel.py         Source control panel (VS Code-style)
├── github_api.py        GitHub CLI (gh) integration
├── codeium.py           Codeium AI inline-completion
├── suggest.py           Local suggestion engine (keywords + identifiers)
├── icons.py             Nerd Font glyph mapping
├── install.py           'carl' installer (venv + symlinks)
├── perf.py              RSS memory + frame timing
├── dashboard.py         YUKI welcome dashboard (front panel)
├── imageviewer.py       In-terminal image viewer (pure decoders + half-block render +
│                        Kitty/iTerm2 graphics passthrough)
├── quick_open.py        Fuzzy file search (async index + scoring, capped)
├── recent.py            Recently opened files (JSON)
├── settings.py          Persistent editor settings (JSON)
├── themes.py            Color themes (syntax, git, diff palettes)
├── languages/
│   └── schema.py        Regex tokenizer + language detection (17 languages)
├── extensions/
│   ├── api.py           Extension API (commands, keybinds, lifecycle)
│   └── loader.py        Extension discovery & lazy loading
└── storage/
    ├── compact.py       Compact byte-array line store
    └── mapped.py        Memory-mapped read-mostly line store
```
