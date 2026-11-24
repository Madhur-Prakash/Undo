#!/usr/bin/env sh
# Remove the Undo systemd service. Your data directory is NOT deleted.
#   ./uninstall_service.sh            # user service
#   sudo ./uninstall_service.sh --system
set -eu

if [ "${1:-}" = "--system" ]; then
  [ "$(id -u)" -eq 0 ] || { echo "--system requires root" >&2; exit 1; }
  CTL="systemctl"
  UNIT=/etc/systemd/system/undo.service
else
  CTL="systemctl --user"
  UNIT="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/undo.service"
fi

$CTL disable --now undo.service 2>/dev/null || true
rm -f "$UNIT"
$CTL daemon-reload
echo "Removed $UNIT. History in your Undo data directory was left untouched."
