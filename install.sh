#!/usr/bin/env bash
#
# install.sh — clone YUKI-ide and run its Makefile installer
#
# Usage:
#   ./install.sh
#   curl -fsSL https://raw.githubusercontent.com/the-priyankaa/YUKI-ide/main/install.sh | bash
#
set -euo pipefail

REPO_URL="https://github.com/the-priyankaa/YUKI-ide.git"
REPO_DIR="YUKI-ide"

info()  { printf '\033[1;34m[info]\033[0m %s\n' "$1"; }
error() { printf '\033[1;31m[error]\033[0m %s\n' "$1" >&2; }

# --- OS check -----------------------------------------------------------

case "$(uname -s)" in
  Linux*|Darwin*)
    ;; # supported
  CYGWIN*|MINGW*|MSYS*)
    error "Native Windows shells (Git Bash/Cygwin/MSYS) are not fully supported."
    error "Please use WSL, or run install.ps1 from PowerShell instead."
    exit 1
    ;;
  *)
    error "Unsupported OS: $(uname -s)"
    exit 1
    ;;
esac

# --- sanity checks -----------------------------------------------------

if ! command -v git >/dev/null 2>&1; then
  error "git is not installed. Please install git and re-run this script."
  exit 1
fi

if ! command -v make >/dev/null 2>&1; then
  error "make is not installed. Please install make and re-run this script."
  exit 1
fi

# --- clone ---------------------------------------------------------------

if [ -d "$REPO_DIR" ]; then
  info "Directory '$REPO_DIR' already exists, skipping clone."
else
  info "Cloning $REPO_URL ..."
  git clone "$REPO_URL" "$REPO_DIR"
fi

# --- install ---------------------------------------------------------------

info "Entering $REPO_DIR/core ..."
cd "$REPO_DIR/core"

info "Running 'make install' (creates venv + symlinks to ~/.local/bin) ..."
make install

info "Done. Make sure ~/.local/bin is on your PATH:"
echo '  export PATH="$HOME/.local/bin:$PATH"'
