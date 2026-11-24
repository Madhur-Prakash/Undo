#!/usr/bin/env bash
# Update Undo on Linux to the code in this checkout and restart the daemon.
#
# Run it from anywhere, as the user who runs Undo, after `git pull` (or with --pull):
#
#   bash scripts/update_linux.sh            # reinstall from this checkout, restart the daemon
#   bash scripts/update_linux.sh --pull     # git pull first
#   bash scripts/update_linux.sh --editable # install in editable mode (follows the checkout)
#
# It handles every way the daemon can run:
#   * systemd user service (`undo service install`)      -> systemctl --user restart
#   * systemd system service (install_service.sh --system) -> sudo systemctl restart
#   * no service, daemon started with `undo start`         -> undo stop + undo start
#   * not running at all                                   -> left stopped (says so)
# History, settings and tracked folders are kept: they live in the data directory, not here.
set -euo pipefail

PULL=0
EDITABLE=0
PYTHON_VERSION="${UNDO_PYTHON:-3.12}"
for arg in "$@"; do
  case "$arg" in
    --pull) PULL=1 ;;
    --editable) EDITABLE=1 ;;
    -h|--help) sed -n '2,18p' "$0"; exit 0 ;;
    *) echo "unknown option: $arg (see --help)" >&2; exit 2 ;;
  esac
done

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PATH="$HOME/.local/bin:$PATH"

step() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
fail() { printf '\033[31merror:\033[0m %s\n' "$*" >&2; exit 1; }

[ -f "$REPO/cli/pyproject.toml" ] && [ -f "$REPO/backend/pyproject.toml" ] \
  || fail "$REPO does not look like the Undo repository (cli/ and backend/ missing)"
command -v uv >/dev/null 2>&1 \
  || fail "uv not found. Install it: curl -LsSf https://astral.sh/uv/install.sh | sh"

if [ "$(id -u)" -eq 0 ]; then SUDO=""; else SUDO="sudo"; fi
has_systemd=0
command -v systemctl >/dev/null 2>&1 && has_systemd=1
user_unit=0
system_unit=0
if [ "$has_systemd" = 1 ]; then
  systemctl --user cat undo.service >/dev/null 2>&1 && user_unit=1
  systemctl cat undo.service >/dev/null 2>&1 && [ -f /etc/systemd/system/undo.service ] && system_unit=1
fi

# ---------------------------------------------------------------------------- 1. code
if [ "$PULL" = 1 ]; then
  step "Pulling the latest code"
  git -C "$REPO" pull --ff-only
fi
step "Code: $(git -C "$REPO" log -1 --format='%h %s (%cr)' 2>/dev/null || echo "$REPO")"

# ------------------------------------------------------------------- 2. stop the daemon
# Stop before reinstalling, so the running daemon never sees its files replaced underneath it.
was_running=0
if [ "$user_unit" = 1 ] && systemctl --user is-active --quiet undo; then
  step "Stopping the user service"
  systemctl --user stop undo
  was_running=1
fi
if [ "$system_unit" = 1 ] && systemctl is-active --quiet undo; then
  step "Stopping the system service"
  $SUDO systemctl stop undo
  was_running=1
fi
if [ "$was_running" = 0 ] && command -v undo >/dev/null 2>&1 && undo status --json 2>/dev/null | grep -q '"daemon_running": true'; then
  step "Stopping the daemon (started with undo start)"
  undo stop || true
  was_running=1
fi

# ----------------------------------------------------------------------- 3. reinstall
step "Installing undo from $REPO"
if [ "$EDITABLE" = 1 ]; then
  uv tool install --force --reinstall --python "$PYTHON_VERSION" \
    --editable "$REPO/cli" --with-editable "$REPO/backend"
else
  # --reinstall: rebuild even when the version number did not change.
  uv tool install --force --reinstall --python "$PYTHON_VERSION" "$REPO/cli" --with "$REPO/backend"
fi
hash -r
undo --version

# Apply schema migrations and new default settings before the daemon starts.
undo init >/dev/null

# ------------------------------------------------------------------------- 4. restart
started=0
if [ "$user_unit" = 1 ]; then
  step "Restarting the user service"
  systemctl --user daemon-reload
  systemctl --user restart undo
  started=1
fi
if [ "$system_unit" = 1 ]; then
  step "Restarting the system service"
  $SUDO systemctl daemon-reload
  $SUDO systemctl restart undo
  started=1
fi
if [ "$started" = 0 ] && [ "$was_running" = 1 ]; then
  step "Starting the daemon"
  undo start
  started=1
fi

# -------------------------------------------------------------------------- 5. verify
if [ "$started" = 1 ]; then
  step "Waiting for the daemon"
  for _ in $(seq 1 40); do
    if undo status --json 2>/dev/null | grep -q '"daemon_running": true'; then break; fi
    sleep 0.5
  done
  undo status || true
  if ! undo status --json 2>/dev/null | grep -q '"daemon_running": true'; then
    echo
    echo "The daemon did not come up. Look at:"
    [ "$user_unit" = 1 ] && echo "  journalctl --user -u undo -n 50"
    [ "$system_unit" = 1 ] && echo "  sudo journalctl -u undo -n 50"
    echo "  undo logs"
    exit 1
  fi
else
  echo
  echo "Undo is updated. No daemon was running, so none was started."
  echo "Start one with 'undo start', or install autostart with 'undo service install'."
fi

if [ "$user_unit" = 1 ] && command -v loginctl >/dev/null 2>&1; then
  linger="$(loginctl show-user "$USER" -p Linger 2>/dev/null | cut -d= -f2 || true)"
  if [ "$linger" != "yes" ]; then
    echo
    echo "Note: linger is off, so the user service stops when you log out and does not start at boot."
    echo "      Turn it on with: sudo loginctl enable-linger $USER"
  fi
fi
echo
echo "Done."
