#!/usr/bin/env bash
#
# token fishing - install / update / uninstall (macOS, Linux)
#
#   bash install.sh              install
#   bash install.sh update       pull the latest source and reinstall
#   bash install.sh uninstall    remove the command, the statusline hook and settings
#
# Do NOT run this with sudo. Everything this tool touches lives in your own home
# directory (~/.claude). Installing as root would register the statusline hook in
# root's home instead of yours, and the tool would never find your usage data.

set -euo pipefail

PACKAGE="token-fishing"
COMMAND="tokenfishing"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

bold() { printf '\033[1m%s\033[0m\n' "$1"; }
info() { printf '  %s\n' "$1"; }
warn() { printf '\033[33m  ! %s\033[0m\n' "$1"; }
fail() { printf '\033[31m  x %s\033[0m\n' "$1" >&2; exit 1; }

# ---------------------------------------------------------------- sanity checks

if [ "$(id -u)" -eq 0 ]; then
    fail "Do not run this as root. It installs into your own home directory.
     Run it again without sudo:  bash install.sh"
fi

find_python() {
    for candidate in python3.13 python3.12 python3.11 python3 python; do
        if command -v "$candidate" >/dev/null 2>&1 &&
           "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
            command -v "$candidate"
            return 0
        fi
    done
    return 1
}

PYTHON="$(find_python)" || fail "Python 3.11 or newer is required but was not found.
     macOS:  brew install python@3.12
     Debian: sudo apt install python3"

check_tkinter() {
    if "$PYTHON" -c 'import tkinter' >/dev/null 2>&1; then
        return 0
    fi
    warn "tkinter is missing - the pixel window will not open (the console command still works)."
    case "$(uname -s)" in
        Darwin) info "Install it with:  brew install python-tk" ;;
        *)
            if command -v apt >/dev/null 2>&1; then
                info "Install it with:  sudo apt install python3-tk"
            elif command -v dnf >/dev/null 2>&1; then
                info "Install it with:  sudo dnf install python3-tkinter"
            elif command -v pacman >/dev/null 2>&1; then
                info "Install it with:  sudo pacman -S tk"
            else
                info "Install your distribution's python3-tk package."
            fi
            ;;
    esac
}

MARKER="# added by token fishing installer"

shell_rc() {
    # Where a login shell would pick up an export. zsh reads .zshrc; bash on
    # macOS reads .bash_profile for login shells, .bashrc elsewhere.
    case "$(basename "${SHELL:-bash}")" in
        zsh) echo "$HOME/.zshrc" ;;
        *)
            if [ "$(uname -s)" = "Darwin" ]; then
                echo "$HOME/.bash_profile"
            else
                echo "$HOME/.bashrc"
            fi
            ;;
    esac
}

bin_dir() {
    if command -v pipx >/dev/null 2>&1; then
        pipx environment --value PIPX_BIN_DIR 2>/dev/null && return 0
    fi
    "$PYTHON" -c 'import site, os; print(os.path.join(site.USER_BASE, "bin"))' 2>/dev/null \
        || echo "$HOME/.local/bin"
}

add_to_path() {
    local bindir rc
    bindir="$(bin_dir)"
    [ -n "$bindir" ] || return 0

    # Make it work in *this* shell too, so the "Run it with:" line below is true
    # immediately and not only after the user opens a new terminal.
    case ":$PATH:" in
        *":$bindir:"*) ;;
        *) export PATH="$bindir:$PATH" ;;
    esac

    rc="$(shell_rc)"
    if [ -f "$rc" ] && grep -qF "$bindir" "$rc"; then
        info "PATH already set up in $rc"
        return 0
    fi
    printf '\n%s\nexport PATH="%s:$PATH"\n' "$MARKER" "$bindir" >> "$rc"
    info "added $bindir to PATH in $rc"
    info "(already active here; other terminals pick it up after restart)"
}

remove_from_path() {
    local rc
    rc="$(shell_rc)"
    [ -f "$rc" ] || return 0
    grep -qF "$MARKER" "$rc" || return 0
    # Drop the marker and the export line that follows it, leave the rest alone.
    "$PYTHON" - "$rc" "$MARKER" <<'PY'
import sys
path, marker = sys.argv[1], sys.argv[2]
with open(path, encoding="utf-8") as f:
    lines = f.readlines()
out, skip = [], 0
for line in lines:
    if skip:
        skip -= 1
        continue
    if line.strip() == marker:
        skip = 1          # also drop the export line right after it
        continue
    out.append(line)
with open(path, "w", encoding="utf-8") as f:
    f.writelines(out)
PY
    info "removed the PATH entry from $rc"
}

# ------------------------------------------------------------------- operations

do_install() {
    bold "Installing token fishing"
    check_tkinter

    if command -v pipx >/dev/null 2>&1; then
        info "using pipx (isolated environment)"
        pipx install --force "$REPO_DIR" >/dev/null
        pipx ensurepath >/dev/null 2>&1 || true
    else
        info "using pip --user (install pipx for an isolated environment)"
        "$PYTHON" -m pip install --user --upgrade "$REPO_DIR" >/dev/null
    fi

    add_to_path

    # The hook stores an absolute path to the installed file, so it has to be
    # re-registered after every install - the path changes when the venv does.
    bold "Registering the Claude Code statusline hook"
    if command -v "$COMMAND" >/dev/null 2>&1; then
        "$COMMAND" --install-statusline || warn "could not register the hook (see above)"
    else
        "$PYTHON" -m ccpet --install-statusline || warn "could not register the hook (see above)"
    fi

    bold "Done"
    if ! command -v "$COMMAND" >/dev/null 2>&1; then
        warn "$COMMAND is still not on PATH - open a new terminal and try again."
    fi
    info "Run it with:            $COMMAND"
    info "Apiary screen:          $COMMAND --bee"
    info "Keep your shell free:   $COMMAND -d"
}

do_update() {
    bold "Updating token fishing"
    if [ -d "$REPO_DIR/.git" ]; then
        git -C "$REPO_DIR" pull --ff-only
    else
        warn "not a git checkout - reinstalling the current source instead"
    fi
    do_install
}

do_uninstall() {
    bold "Removing token fishing"

    # Unregister first: the command disappears with the package, and a stale
    # statusLine entry would leave Claude Code running a file that is gone.
    if command -v "$COMMAND" >/dev/null 2>&1; then
        "$COMMAND" --uninstall-statusline || warn "could not unregister the hook"
    else
        "$PYTHON" -m ccpet --uninstall-statusline 2>/dev/null || true
    fi

    if command -v pipx >/dev/null 2>&1 && pipx list 2>/dev/null | grep -q "$PACKAGE"; then
        pipx uninstall "$PACKAGE" >/dev/null
    else
        "$PYTHON" -m pip uninstall -y "$PACKAGE" >/dev/null 2>&1 || true
    fi

    remove_from_path

    bold "Done"
    info "Your Claude Code transcripts in ~/.claude/projects were not touched."
}

case "${1:-install}" in
    install)   do_install ;;
    update)    do_update ;;
    uninstall) do_uninstall ;;
    *)
        echo "usage: bash install.sh [install|update|uninstall]" >&2
        exit 2
        ;;
esac
