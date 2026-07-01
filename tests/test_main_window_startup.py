"""MainWindow startup regression tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from PyQt6.QtWidgets import QApplication

from plasmacolorizer.ui.main_window import MainWindow


def test_main_window_instantiates(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    with patch.object(MainWindow, "_startup_autodetect_preview"):
        win = MainWindow()
    try:
        assert hasattr(win, "_load_app_settings_to_ui")
        assert callable(win._load_app_settings_to_ui)
        assert win._apply_konsole_scheme.isChecked()
        assert win._auto_apply_wallpaper.isChecked()
        assert win._wallpaper_daemon.isChecked()
        assert hasattr(win, "_daemon_status")
    finally:
        win.close()
