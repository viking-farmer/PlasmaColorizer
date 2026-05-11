#!/usr/bin/env bash
set -e
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$DIR/.venv"

if [ ! -f "$VENV/bin/python" ]; then
  echo "venv not found — creating it now…"
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install -q -e "$DIR"
fi

exec "$VENV/bin/plasmacolorizer" "$@"
