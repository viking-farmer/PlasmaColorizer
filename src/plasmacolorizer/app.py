"""Application entry helpers."""

from __future__ import annotations

import sys

from PyQt6.QtWidgets import QApplication

from plasmacolorizer.ui.main_window import MainWindow
from plasmacolorizer.ui.style import APP_STYLESHEET


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("PlasmaColorizer")
    app.setStyle("Fusion")
    app.setStyleSheet(APP_STYLESHEET)
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
