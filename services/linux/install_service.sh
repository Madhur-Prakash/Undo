#!/usr/bin/env sh
# Install the Undo daemon as a systemd service.
#
#   ./install_service.sh                 # user service (no root needed)
#   sudo ./install_service.sh --system --user alice   # system service running as alice
#
# Options:
#   --python PATH     Python interpreter that has undo-core installed (default: auto-detect)
#   --data-dir DIR    Undo data directory (default: $UNDO_HOME or ~/.local/share/undo)
set -eu

SCOPE=user
RUN_AS=""
PYTHON=""
DATA_DIR="${UNDO_HOME:-}"
HERE="$(cd "$(dirname "$0")" && pwd)"

while [ $# -gt 0 ]; do
  case "$1" in
    --system) SCOPE=system ;;
    --user) RUN_AS="$2"; shift ;;
    --python) PYTHON="$2"; shift ;;
    --data-dir) DATA_DIR="$2"; shift ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

command -v systemctl >/dev/null 2>&1 || { echo "systemctl not found" >&2; exit 1; }

if [ -z "$PYTHON" ]; then
  if command -v undo >/dev/null 2>&1; then
    # The interpreter from the undo launcher's shebang (uv tool / pipx / venv).
    PYTHON="$(head -n1 "$(command -v undo)" | sed 's/^#!//' | awk '{print $1}')"
  fi
  [ -x "${PYTHON:-}" ] || PYTHON="$(command -v python3)"
fi
"$PYTHON" -c "import undo_core" 2>/dev/null || { echo "$PYTHON cannot import undo_core; pass --python" >&2; exit 1; }

if [ "$SCOPE" = system ]; then
  [ "$(id -u)" -eq 0 ] || { echo "--system requires root" >&2; exit 1; }
  [ -n "$RUN_AS" ] || { echo "--system requires --user ACCOUNT" >&2; exit 1; }
  HOME_DIR="$(getent passwd "$RUN_AS" | cut -d: -f6)"
  [ -n "$DATA_DIR" ] || DATA_DIR="$HOME_DIR/.local/share/undo"
  UNIT_DIR=/etc/systemd/system
  CTL="systemctl"
else
  [ -n "$DATA_DIR" ] || DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/undo"
  UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
  CTL="systemctl --user"
fi

if [ ! -f "$DATA_DIR/config.json" ]; then
  echo "Initialising $DATA_DIR"
  if [ "$SCOPE" = system ]; then
    su -s /bin/sh "$RUN_AS" -c "'$PYTHON' -c 'from undo_core.context import UndoContext; UndoContext.open(\"$DATA_DIR\", require_initialized=False).initialize()'"
  else
    "$PYTHON" -c "from undo_core.context import UndoContext; UndoContext.open('$DATA_DIR', require_initialized=False).initialize()"
  fi
fi

mkdir -p "$UNIT_DIR"
UNIT="$UNIT_DIR/undo.service"
sed -e "s#@UNDO_PYTHON@#$PYTHON#g" -e "s#@UNDO_HOME@#$DATA_DIR#g" -e "s#@UNDO_DOCS@#$HERE/../../docs/INSTALLATION.md#g" \
  "$HERE/undo.service" > "$UNIT"
if [ "$SCOPE" = system ]; then
  sed -i -e "s#^\[Service\]#[Service]\nUser=$RUN_AS#" -e "s#^WantedBy=default.target#WantedBy=multi-user.target#" "$UNIT"
fi

$CTL daemon-reload
$CTL enable --now undo.service
echo "Installed $UNIT"
$CTL --no-pager status undo.service | head -n 5 || true
if [ "$SCOPE" = user ]; then
  echo "Tip: run 'loginctl enable-linger $USER' so the daemon keeps running when you are logged out."
fi
