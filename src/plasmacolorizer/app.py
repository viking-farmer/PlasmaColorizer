"""Application entry helpers."""

from __future__ import annotations

import sys

from PyQt6.QtWidgets import QApplication

from plasmacolorizer.app_icon import load_app_icon
from plasmacolorizer.ui.main_window import MainWindow
from plasmacolorizer.ui.style import APP_STYLESHEET


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("PlasmaColorizer")
    app.setApplicationDisplayName("PlasmaColorizer")
    # Associate the window with ~/.local/share/applications/plasmacolorizer.desktop (Wayland / Plasma taskbar).
    app.setDesktopFileName("plasmacolorizer")
    icon = load_app_icon()
    if not icon.isNull():
        app.setWindowIcon(icon)
    app.setStyle("Fusion")
    app.setStyleSheet(APP_STYLESHEET)
    win = MainWindow()
    if not icon.isNull():
        win.setWindowIcon(icon)
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
