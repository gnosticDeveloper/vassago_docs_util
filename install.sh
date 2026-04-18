#!/usr/bin/env bash
# install.sh — installs vassago_docs_util as a system-wide command
# Run once from the project root: bash install.sh

set -euo pipefail

# ── Colours ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BOLD='\033[1m'; NC='\033[0m'
info()    { echo -e "${BOLD}→${NC} $*"; }
success() { echo -e "${GREEN}✓${NC} $*"; }
warn()    { echo -e "${YELLOW}⚠${NC}  $*"; }
die()     { echo -e "${RED}✗${NC} $*" >&2; exit 1; }

# ── Resolve project root (where this script lives) ────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MAIN_PY="$SCRIPT_DIR/main.py"
VENV_DIR="$SCRIPT_DIR/.venv"
LAUNCHER="/usr/local/bin/vassago_docs_util"

[[ -f "$MAIN_PY" ]] || die "main.py not found in $SCRIPT_DIR — run this from the project root."

# ── Check Python in venv ──────────────────────────────────────────────────────
PYTHON=""
if [[ -x "$VENV_DIR/bin/python" ]]; then
    PYTHON="$VENV_DIR/bin/python"
elif command -v uv &>/dev/null; then
    info "No .venv found — running 'uv sync' to create it..."
    (cd "$SCRIPT_DIR" && uv sync) || die "uv sync failed. Check pyproject.toml."
    PYTHON="$VENV_DIR/bin/python"
else
    die "No .venv and no 'uv' found. Run 'uv sync' in the project root first, or install uv: https://docs.astral.sh/uv/"
fi
success "Python: $PYTHON"

# ── Check / install Node + npx ────────────────────────────────────────────────
if ! command -v npx &>/dev/null; then
    warn "'npx' not found. Attempting to install Node.js via your package manager..."
    if command -v apt-get &>/dev/null; then
        sudo apt-get update -qq && sudo apt-get install -y nodejs npm \
            || die "apt install failed. Install Node.js manually: https://nodejs.org"
    elif command -v dnf &>/dev/null; then
        sudo dnf install -y nodejs npm \
            || die "dnf install failed. Install Node.js manually: https://nodejs.org"
    elif command -v pacman &>/dev/null; then
        sudo pacman -S --noconfirm nodejs npm \
            || die "pacman install failed. Install Node.js manually: https://nodejs.org"
    else
        die "Cannot auto-install Node.js on this system. Install it manually: https://nodejs.org"
    fi
    success "Node.js installed."
fi

# ── Check / install repomix via npx (caches it globally) ─────────────────────
info "Verifying repomix is available via npx..."
if ! npx repomix --version &>/dev/null 2>&1; then
    info "repomix not cached — pre-installing globally so npx doesn't need network later..."
    npm install -g repomix || warn "Global repomix install failed — npx will fetch it on first run."
else
    success "repomix OK."
fi

# ── Write the launcher script ─────────────────────────────────────────────────
# We write a small wrapper instead of a direct symlink to main.py because:
#   1. The shebang needs to point to the venv Python, not the system one
#   2. We want to run from the CWD (the repo being documented), not the project dir
#   3. We can embed the absolute path to main.py safely

info "Writing launcher to $LAUNCHER (requires sudo)..."
sudo tee "$LAUNCHER" > /dev/null << LAUNCHER_EOF
#!/usr/bin/env bash
# vassago_docs_util — auto-generated launcher, do not edit manually
# Regenerate by re-running install.sh in the auto-docs project.

PYTHON="$PYTHON"
MAIN_PY="$MAIN_PY"

# Sanity checks at invocation time (not just at install time)
if [[ ! -x "\$PYTHON" ]]; then
    echo "✗ Python not found at \$PYTHON" >&2
    echo "  Re-run install.sh in the auto-docs project to fix the venv." >&2
    exit 1
fi

if [[ ! -f "\$MAIN_PY" ]]; then
    echo "✗ main.py not found at \$MAIN_PY" >&2
    echo "  Has the auto-docs project been moved or deleted?" >&2
    exit 1
fi

if ! command -v npx &>/dev/null; then
    echo "✗ 'npx' not found. Install Node.js: https://nodejs.org" >&2
    exit 1
fi

# Run from wherever the user is (the repo to be documented)
exec "\$PYTHON" "\$MAIN_PY" "\$@"
LAUNCHER_EOF

sudo chmod +x "$LAUNCHER"
success "Launcher written."

# ── Verify ────────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}Installation complete.${NC}"
echo ""
echo "  Usage (run from any repo):"
echo "    vassago_docs_util"
echo "    vassago_docs_util --verbose"
echo "    vassago_docs_util --yes --verbose"
echo ""
echo "  To uninstall:"
echo "    sudo rm $LAUNCHER"
