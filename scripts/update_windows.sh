#!/usr/bin/env bash
# Update Undo on Windows to the code in this checkout (run in Git Bash), after `git pull`.
#
#   bash scripts/update_windows.sh              # build the installer from this code, install it
#   bash scripts/update_windows.sh --pull       # git pull first
#   bash scripts/update_windows.sh --no-build   # install the newest Undo-Setup-*.exe already built
#   bash scripts/update_windows.sh --dev        # development install (uv tool) instead of the installer
#
# Installed app (the default, for anyone who installed Undo-Setup-<version>.exe):
#   1. builds gui/installer/Undo-Setup-<version>.exe with Inno Setup (uv + Flutter + Visual Studio
#      are needed for that, see docs/INSTALLATION.md#building-the-installer),
#   2. closes the app and stops the daemon,
#   3. runs the installer silently with "start at sign-in" and "add to PATH" on,
#   4. Setup replaces the programs, re-registers autostart and starts the new daemon,
#   5. checks the result.
# Windows has no "daemon-reload": the installer does the whole restart.
#
# --dev (for a `uv tool install ./cli --with ./backend` setup): reinstalls with uv, then
# restarts the daemon and re-registers autostart.
#
# History, settings and tracked folders are kept: they live in %LOCALAPPDATA%\Undo.
set -euo pipefail

PULL=0
BUILD=1
MODE=""
for arg in "$@"; do
  case "$arg" in
    --pull) PULL=1 ;;
    --no-build) BUILD=0 ;;
    --dev) MODE=dev ;;
    --installed) MODE=installed ;;
    -h|--help) sed -n '2,23p' "$0"; exit 0 ;;
    *) echo "unknown option: $arg (see --help)" >&2; exit 2 ;;
  esac
done

case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*) ;;
  *) echo "This script is for Windows (Git Bash). On Linux use scripts/update_linux.sh." >&2; exit 2 ;;
esac

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCAL="$(cygpath -u "${LOCALAPPDATA:?LOCALAPPDATA is not set}")"
APP_DIR="$LOCAL/Programs/Undo"
INSTALLED_UNDO="$APP_DIR/backend/undo.exe"
export PATH="$HOME/.local/bin:$PATH"

step() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
fail() { printf '\033[31merror:\033[0m %s\n' "$*" >&2; exit 1; }

[ -f "$REPO/gui/installer/Undo.iss" ] || fail "$REPO does not look like the Undo repository"

if [ -z "$MODE" ]; then
  if [ -f "$INSTALLED_UNDO" ]; then
    MODE=installed
  elif command -v uv >/dev/null 2>&1 && uv tool list 2>/dev/null | grep -q '^undo-cli'; then
    MODE=dev
  else
    MODE=installed   # first install from source: build and install the app
  fi
fi

if [ "$PULL" = 1 ]; then
  step "Pulling the latest code"
  git -C "$REPO" pull --ff-only
fi
step "Code: $(git -C "$REPO" log -1 --format='%h %s (%cr)' 2>/dev/null || echo "$REPO")"

# ------------------------------------------------------------------------ dev install
if [ "$MODE" = dev ]; then
  command -v uv >/dev/null 2>&1 || fail "uv not found: https://docs.astral.sh/uv/"
  step "Stopping the daemon"
  if command -v undo >/dev/null 2>&1; then undo stop || true; fi
  step "Reinstalling undo from $REPO (uv tool)"
  uv tool install --force --reinstall --python 3.12 "$REPO/cli" --with "$REPO/backend"
  hash -r
  undo --version
  undo init >/dev/null
  step "Registering autostart and starting the daemon"
  undo service install
  undo status || true
  echo; echo "Done."
  exit 0
fi

# ------------------------------------------------------------------ installed app
find_iscc() {
  local c
  for c in "${ISCC:-}" \
           "/c/Program Files/Inno Setup 7/ISCC.exe" \
           "/c/Program Files (x86)/Inno Setup 7/ISCC.exe" \
           "/c/Program Files (x86)/Inno Setup 6/ISCC.exe" \
           "/c/Program Files/Inno Setup 6/ISCC.exe" \
           "$(command -v ISCC 2>/dev/null || true)" \
           "$(command -v iscc 2>/dev/null || true)"; do
    if [ -n "$c" ] && [ -f "$c" ]; then echo "$c"; return 0; fi
  done
  return 1
}

if [ "$BUILD" = 1 ]; then
  ISCC_EXE="$(find_iscc)" || fail "Inno Setup not found. Install Inno Setup 7, or set ISCC=/path/to/ISCC.exe"
  step "Building the installer (several minutes; logs in gui/installer/build/)"
  ISS="$(cygpath -w "$REPO/gui/installer/Undo.iss")"
  ok=0
  # The first attempt builds everything. An antivirus scan of the new setup file can make the
  # final step fail ("EndUpdateResource failed"); the retries then only repackage the builds
  # just made (BuildApp=0), which takes seconds, after giving the scan time to finish.
  build_flag=""
  iscc_out="$REPO/gui/installer/build/iscc.log"
  mkdir -p "$(dirname "$iscc_out")"
  for attempt in 1 2 3 4 5; do
    rm -f "$REPO"/gui/installer/Undo-Setup-*.exe 2>/dev/null || true
    if MSYS_NO_PATHCONV=1 "$ISCC_EXE" /Q $build_flag "$ISS" 2>&1 | tee "$iscc_out"; [ "${PIPESTATUS[0]}" = 0 ]; then
      ok=1; break
    fi
    # Retry only the antivirus lock; any other error is a real build failure.
    grep -q "EndUpdateResource\|Resource update error" "$iscc_out" || break
    [ "$attempt" = 5 ] && break
    wait_s=$((attempt * 10))
    echo "Packaging attempt $attempt failed (antivirus lock?); repackaging in $wait_s seconds ..."
    sleep "$wait_s"
    build_flag="/DBuildApp=0"
  done
  [ "$ok" = 1 ] || fail "the installer did not build; read the log named above in gui/installer/build/"
fi

SETUP="$(ls -t "$REPO"/gui/installer/Undo-Setup-*.exe 2>/dev/null | head -n1 || true)"
[ -n "$SETUP" ] || fail "no gui/installer/Undo-Setup-*.exe found; run without --no-build"
step "Installer: $(basename "$SETUP")"

step "Closing the app and stopping the daemon"
taskkill //IM Undo.exe //F >/dev/null 2>&1 || true
if [ -f "$INSTALLED_UNDO" ]; then "$INSTALLED_UNDO" stop || true; fi

step "Installing (silent)"
LOG="$REPO/gui/installer/build/install.log"
mkdir -p "$(dirname "$LOG")"
MSYS_NO_PATHCONV=1 "$SETUP" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CLOSEAPPLICATIONS \
  "/TASKS=startup,addtopath" "/LOG=$(cygpath -w "$LOG")" \
  || fail "Setup failed (exit $?); see $LOG"

step "Checking"
[ -f "$INSTALLED_UNDO" ] || fail "$INSTALLED_UNDO is missing after Setup; see $LOG"
"$INSTALLED_UNDO" --version
for _ in $(seq 1 40); do
  if "$INSTALLED_UNDO" status --json 2>/dev/null | grep -q '"daemon_running": true'; then break; fi
  sleep 0.5
done
"$INSTALLED_UNDO" status || true
"$INSTALLED_UNDO" service status || true
echo
echo "Done. Open a new terminal to pick up PATH changes, if this was the first install."
