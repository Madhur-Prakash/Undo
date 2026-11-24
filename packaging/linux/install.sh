#!/usr/bin/env sh
# Install Undo for the current user from a release folder (no root needed).
#   ./installer/install.sh [--no-service] [--no-desktop]
# Works on headless servers: the desktop app is skipped automatically when no
# bundle is present or --no-desktop is given.
set -eu
HERE="$(cd "$(dirname "$0")" && pwd)"
RELEASE="$(dirname "$HERE")"
SERVICE=1
DESKTOP=1
for arg in "$@"; do
  case "$arg" in
    --no-service) SERVICE=0 ;;
    --no-desktop) DESKTOP=0 ;;
    *) echo "unknown option $arg" >&2; exit 2 ;;
  esac
done

CORE="$(ls "$RELEASE"/python/undo_core-*.whl | head -n1)"
CLI="$(ls "$RELEASE"/python/undo_cli-*.whl | head -n1)"

if command -v uv >/dev/null 2>&1; then
  uv tool install --force --python 3.12 "$CLI" --with "$CORE"
elif command -v pipx >/dev/null 2>&1; then
  pipx install --force "$CLI" --preinstall "$CORE"
else
  python3 -m pip install --user --upgrade "$CORE" "$CLI"
fi

export PATH="$HOME/.local/bin:$PATH"
undo init

if [ "$SERVICE" = 1 ]; then
  if command -v systemctl >/dev/null 2>&1 && systemctl --user show-environment >/dev/null 2>&1; then
    undo service install
  else
    echo "systemd user session not available; start the daemon with 'undo start' or use services/install_service.sh --system"
  fi
fi

if [ "$DESKTOP" = 1 ] && [ -d "$RELEASE/desktop" ]; then
  TARGET="$HOME/.local/opt/undo"
  mkdir -p "$TARGET" "$HOME/.local/share/applications"
  cp -r "$RELEASE/desktop/." "$TARGET/"
  cp "$HERE/undo.png" "$TARGET/undo.png"
  sed -e "s#@EXEC@#$TARGET/undo_desktop#" -e "s#@UNDO_CLI@#$(command -v undo)#" -e "s#@ICON@#$TARGET/undo.png#" \
    "$HERE/undo-desktop.desktop" > "$HOME/.local/share/applications/undo-desktop.desktop"
  echo "Desktop app installed to $TARGET"
fi
echo "Done. Track a folder with: undo track ~/Documents"
