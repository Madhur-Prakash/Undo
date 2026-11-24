#!/usr/bin/env sh
# Remove Undo for the current user. History is kept unless --remove-data is given.
set -u
export PATH="$HOME/.local/bin:$PATH"
if command -v undo >/dev/null 2>&1; then
  undo stop || true
  undo service uninstall || true
fi
if command -v uv >/dev/null 2>&1; then
  uv tool uninstall undo-cli || true
elif command -v pipx >/dev/null 2>&1; then
  pipx uninstall undo-cli || true
else
  python3 -m pip uninstall -y undo-cli undo-core || true
fi
rm -rf "$HOME/.local/opt/undo" "$HOME/.local/share/applications/undo-desktop.desktop"
DATA="${UNDO_HOME:-${XDG_DATA_HOME:-$HOME/.local/share}/undo}"
if [ "${1:-}" = "--remove-data" ]; then
  rm -rf "$DATA"
  echo "Removed version history in $DATA"
else
  echo "Version history kept in $DATA (use --remove-data to delete it)."
fi
