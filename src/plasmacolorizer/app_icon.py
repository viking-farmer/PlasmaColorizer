"""Load the bundled window / launcher icon."""

from __future__ import annotations

from importlib import resources

from PyQt6.QtCore import QSize
from PyQt6.QtGui import QIcon


def load_app_icon() -> QIcon:
    """
    Prefer multi-resolution PNGs (reliable in Qt + KDE); fall back to SVG.

    SVG-only QIcon often appears blank without full Qt SVG imageformat setup;
    PNG works everywhere.
    """
    icon = QIcon()
    try:
        root = resources.files("plasmacolorizer.icons")
        for size in (16, 22, 24, 32, 48, 64, 128, 256):
            name = f"plasmacolorizer_{size}.png"
            ref = root / name
            if not ref.is_file():
                continue
            with resources.as_file(ref) as path:
                icon.addFile(str(path), QSize(size, size))
        if not icon.availableSizes():
            ref = root / "plasmacolorizer.svg"
            with resources.as_file(ref) as path:
                icon = QIcon(str(path))
    except (FileNotFoundError, OSError, TypeError, ValueError):
        return QIcon()
    return icon if not icon.isNull() else QIcon()
