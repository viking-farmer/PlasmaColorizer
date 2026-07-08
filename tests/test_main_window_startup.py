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
        # Shortcuts editor is populated with the bundled defaults on first launch.
        assert win._conky_shortcuts_table.rowCount() == 8
        # Terminal tab defaults to Konsole and lists all known backends.
        assert win._term_combo.currentData() == "konsole"
        assert win._term_combo.count() == 4
    finally:
        win.close()


def test_terminal_tab_settings_roundtrip(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from plasmacolorizer.core.terminal_settings import load_terminal_settings

    monkeypatch.setenv("HOME", str(tmp_path))
    with patch.object(MainWindow, "_startup_autodetect_preview"):
        win = MainWindow()
    try:
        win._term_bold_intense.setChecked(False)
        win._term_opacity.setValue(80)
        win._term_color_checks["background"].setChecked(True)
        win._term_overrides["background"] = "#0a0a12"
        with patch(
            "plasmacolorizer.ui.main_window.QMessageBox.information",
            return_value=None,
        ):
            win._term_save_clicked()
        saved = load_terminal_settings()
        assert saved.bold_intense is False
        assert saved.opacity == 0.8
        assert saved.background_override == "#0a0a12"
    finally:
        win.close()


def test_shortcuts_table_edit_save_roundtrip(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from plasmacolorizer.conky.settings_store import ConkyShortcut, load_conky_settings

    monkeypatch.setenv("HOME", str(tmp_path))
    with patch.object(MainWindow, "_startup_autodetect_preview"):
        win = MainWindow()
    try:
        win._conky_shortcut_reset_defaults()
        win._conky_shortcut_add_row()
        table = win._conky_shortcuts_table
        last = table.rowCount() - 1
        table.item(last, 0).setText("Rofi")
        table.item(last, 1).setText("Meta+Space")
        with patch(
            "plasmacolorizer.ui.main_window.QMessageBox.information",
            return_value=None,
        ):
            win._conky_shortcuts_save_clicked()
        saved = load_conky_settings().conky_shortcuts
        assert ConkyShortcut("Rofi", "Meta+Space") in saved
        assert len(saved) == 9
    finally:
        win.close()
