#!/usr/bin/env bash
# Same targets as the Makefile, for shells without make (Git Bash on Windows, minimal Linux):
#   ./make.sh <target> [args]      e.g.  ./make.sh init   ./make.sh test   ./make.sh cli status
# Every target delegates to scripts/dev.py.
set -euo pipefail
cd "$(dirname "$0")"

TARGETS="init install dev backend cli tui gui test test-unit test-integration test-stress lint format typecheck build clean docs"
target="${1:-help}"
[ $# -gt 0 ] && shift

if [ "$target" = "help" ] || ! printf ' %s ' $TARGETS | grep -q " $target "; then
  echo "Targets: $TARGETS"
  exit 0
fi

PY=""
for candidate in python3 python py; do
  if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c "import sys" >/dev/null 2>&1; then
    PY="$candidate"
    break
  fi
done
[ -n "$PY" ] || { echo "Python not found on PATH" >&2; exit 1; }

if [ "$target" = "dev" ]; then
  "$PY" scripts/dev.py init
  target="backend"
fi
exec "$PY" scripts/dev.py "$target" "$@"
