"""Read lightweight KDE preferences (dark scheme hint)."""

from __future__ import annotations

import os
import re


def kdeglobals_path() -> str:
    return os.path.expanduser("~/.config/kdeglobals")


def is_plasma_dark_scheme_preferred() -> bool:
    """Heuristic only: infer dark UI from current color scheme name in kdeglobals."""
    path = kdeglobals_path()
    try:
        text = open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        return True
    lines = text.splitlines()
    in_general = False
    for line in lines:
        line_s = line.strip()
        if line_s.startswith("[") and line_s.endswith("]"):
            in_general = line_s.lower() == "[general]"
            continue
        if not in_general:
            continue
        m = re.match(r"^\s*ColorScheme\s*=\s*(.+?)\s*$", line)
        if m:
            name = m.group(1).strip()
            break
    else:
        return True
    lowered = name.lower()
    if "dark" in lowered or "night" in lowered:
        return True
    if "light" in lowered and "dark" not in lowered:
        return False
    return True
