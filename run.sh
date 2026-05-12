#!/usr/bin/env bash
set -e
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$DIR/.venv"

# Install bundled icons into the user hicolor theme (PNG + SVG) so Icon=plasmacolorizer works in Kickoff/panel.
_install_app_icon() {
  local base="$DIR/src/plasmacolorizer/icons"
  local theme="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor"
  [ -d "$base" ] || return 0
  local changed=0
  for s in 16 22 24 32 48 64 128 256; do
    local src="$base/plasmacolorizer_${s}.png"
    [ -f "$src" ] || continue
    local dst="$theme/${s}x${s}/apps/plasmacolorizer.png"
    mkdir -p "$(dirname "$dst")"
    if [ ! -f "$dst" ] || ! cmp -s "$src" "$dst" 2>/dev/null; then
      cp "$src" "$dst"
      changed=1
    fi
  done
  local svg_src="$base/plasmacolorizer.svg"
  if [ -f "$svg_src" ]; then
    local svg_dst="$theme/scalable/apps/plasmacolorizer.svg"
    mkdir -p "$(dirname "$svg_dst")"
    if [ ! -f "$svg_dst" ] || ! cmp -s "$svg_src" "$svg_dst" 2>/dev/null; then
      cp "$svg_src" "$svg_dst"
      changed=1
    fi
  fi
  if [ "$changed" = 1 ] && command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f -t "$theme" 2>/dev/null || true
  fi
}
_install_app_icon

if [ ! -f "$VENV/bin/python" ]; then
  echo "venv not found — creating it now…"
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install -q -e "$DIR"
fi

exec "$VENV/bin/plasmacolorizer" "$@"
