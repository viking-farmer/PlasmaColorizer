"""Emergency Plasma / Conky recovery helpers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from plasmacolorizer.conky import recover
from plasmacolorizer.conky import presets as conky_presets
from plasmacolorizer.conky.settings_store import ConkySettings, save_conky_settings
from plasmacolorizer.core.palette import MaterialPalette


def _minimal_palette() -> MaterialPalette:
    return MaterialPalette(
        is_dark=True,
        colors={
            "primary": (10, 20, 30),
            "secondary": (40, 50, 60),
            "tertiary": (70, 80, 90),
            "onSurface": (200, 200, 210),
            "surface": (15, 15, 20),
        },
    )


def test_disable_and_enable_conky_autostart(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    path = conky_presets.install_autostart_entry()
    assert path.is_file()
    msg = recover.disable_conky_autostart()
    assert "disabled" in msg
    assert not path.is_file()
    assert path.with_suffix(path.suffix + ".disabled").is_file()
    msg2 = recover.enable_conky_autostart()
    assert "re-enabled" in msg2
    assert path.is_file()


def test_recover_desktop_stops_conky_and_reports(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(recover, "plasmashell_running", lambda: True)
    notes = recover.recover_desktop(stop_daemon=False, start_shell=False)
    assert any("stopped bundled" in n for n in notes)


def test_render_default_uses_desktop_window_mode(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_SOCKET", raising=False)
    save_conky_settings(ConkySettings(conky_window_mode="desktop"))
    body = conky_presets.render_preset("shortcuts", _minimal_palette()).read_text(
        encoding="utf-8"
    )
    assert "own_window_type = 'desktop'" in body
    assert "own_window_hints = 'undecorated,sticky,skip_taskbar,skip_pager'" in body


def test_plasma_wayland_overrides_desktop_to_normal_below(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE")
    save_conky_settings(ConkySettings(conky_window_mode="desktop"))
    body = conky_presets.render_preset("shortcuts", _minimal_palette()).read_text(
        encoding="utf-8"
    )
    # Desktop-type is invisible under Plasma wallpaper — force visible mode.
    assert "own_window_type = 'normal'" in body
    assert "below" in body


def test_render_normal_below_window_mode(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    save_conky_settings(ConkySettings(conky_window_mode="normal_below"))
    body = conky_presets.render_preset("system", _minimal_palette()).read_text(
        encoding="utf-8"
    )
    assert "own_window_type = 'normal'" in body
    assert "below" in body
    assert "out_to_x = true" in body


def test_process_is_alive_rejects_zombie(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Simulate /proc/pid/stat with zombie state.
    proc_dir = tmp_path / "proc" / "4242"
    proc_dir.mkdir(parents=True)
    (proc_dir / "stat").write_text("4242 (conky) Z 1 1 1 0 -1 0 0 0 0 0 0\n", encoding="utf-8")
    monkeypatch.setattr(conky_presets.os, "kill", lambda *_a, **_k: None)

    def _open(path, *a, **k):
        path = str(path)
        if path == "/proc/4242/stat":
            return (proc_dir / "stat").open(*a, **k)
        raise FileNotFoundError(path)

    import builtins

    real_open = builtins.open

    def fake_open(path, *a, **k):
        if str(path) == "/proc/4242/stat":
            return real_open(proc_dir / "stat", *a, **k)
        return real_open(path, *a, **k)

    monkeypatch.setattr(builtins, "open", fake_open)
    assert conky_presets._process_is_alive(4242) is False


def test_ensure_plasmashell_skips_when_running() -> None:
    with patch.object(recover, "plasmashell_running", return_value=True):
        ok, msg = recover.ensure_plasmashell()
    assert ok
    assert "already running" in msg
