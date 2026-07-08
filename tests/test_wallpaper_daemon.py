"""Wallpaper daemon loop and autostart helpers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from plasmacolorizer.core.app_settings import AppSettings
from plasmacolorizer import wallpaper_daemon


def test_autostart_install_uses_daemon_executable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    autostart = tmp_path / "autostart"
    monkeypatch.setattr(wallpaper_daemon, "autostart_dir", lambda: autostart)
    monkeypatch.setattr(
        wallpaper_daemon,
        "autostart_desktop_path",
        lambda: autostart / wallpaper_daemon.AUTOSTART_FILE,
    )
    monkeypatch.setattr(
        wallpaper_daemon,
        "resolve_daemon_executable",
        lambda: "/home/user/.venv/bin/plasmacolorizer-daemon",
    )
    path = wallpaper_daemon.install_autostart()
    body = path.read_text(encoding="utf-8")
    assert "Exec=/home/user/.venv/bin/plasmacolorizer-daemon" in body
    assert "python3.14 -m" not in body


def test_run_loop_applies_when_fingerprint_differs_from_stored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = AppSettings(
        wallpaper_daemon_enabled=True,
        auto_apply_on_wallpaper_change=True,
        wallpaper_daemon_poll_interval_s=0.01,
        last_applied_wallpaper_fingerprint="fp-a",
    )
    fps = iter(["fp-b", "fp-b"])
    times = iter([0.0, 0.0, 1.0, 1.0])
    apply_calls: list[str] = []

    monkeypatch.setattr(
        "plasmacolorizer.wallpaper_daemon.WALLPAPER_CHANGE_DEBOUNCE_MS",
        0,
    )
    monkeypatch.setattr(
        wallpaper_daemon,
        "wallpaper_fingerprint",
        lambda monitor: next(fps, "fp-b"),
    )
    monkeypatch.setattr(wallpaper_daemon.time, "sleep", lambda _s: None)
    monkeypatch.setattr(wallpaper_daemon.time, "monotonic", lambda: next(times, 1.0))
    monkeypatch.setattr(wallpaper_daemon, "load_app_settings", lambda: app)

    def fake_apply(**kwargs):  # noqa: ANN003
        apply_calls.append("ok")
        wallpaper_daemon._STOP = True
        from plasmacolorizer.core.apply_pipeline import PipelineResult
        from plasmacolorizer.core.palette import MaterialPalette
        from plasmacolorizer.core.plasma_scheme import DiskApplyResult

        pal = MaterialPalette(is_dark=True, colors={"primary": (1, 2, 3)})
        disk = DiskApplyResult(
            scheme_path=Path("/tmp/x.colors"),
            kdeglobals_path=Path("/tmp/kdeglobals"),
            apply_ok=True,
        )
        return PipelineResult(
            src="/tmp/wall.jpg",
            palette=pal,
            disk=disk,
            notify_ok=True,
            notify_msg="ok",
        )

    monkeypatch.setattr(wallpaper_daemon, "generate_and_apply_from_wallpaper", fake_apply)
    wallpaper_daemon._STOP = False
    wallpaper_daemon.run_loop(app)
    assert apply_calls == ["ok"]


def test_run_loop_applies_on_startup_when_never_applied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = AppSettings(
        wallpaper_daemon_enabled=True,
        auto_apply_on_wallpaper_change=True,
        wallpaper_daemon_poll_interval_s=0.01,
        last_applied_wallpaper_fingerprint="",
    )
    times = iter([0.0, 0.0, 1.0, 1.0])
    apply_calls: list[str] = []

    monkeypatch.setattr(
        "plasmacolorizer.wallpaper_daemon.WALLPAPER_CHANGE_DEBOUNCE_MS",
        0,
    )
    monkeypatch.setattr(
        wallpaper_daemon,
        "wallpaper_fingerprint",
        lambda monitor: "fp-current",
    )
    monkeypatch.setattr(wallpaper_daemon.time, "sleep", lambda _s: None)
    monkeypatch.setattr(wallpaper_daemon.time, "monotonic", lambda: next(times, 1.0))
    monkeypatch.setattr(wallpaper_daemon, "load_app_settings", lambda: app)

    def fake_apply(**kwargs):  # noqa: ANN003
        apply_calls.append("ok")
        wallpaper_daemon._STOP = True
        from plasmacolorizer.core.apply_pipeline import PipelineResult
        from plasmacolorizer.core.palette import MaterialPalette
        from plasmacolorizer.core.plasma_scheme import DiskApplyResult

        pal = MaterialPalette(is_dark=True, colors={"primary": (1, 2, 3)})
        disk = DiskApplyResult(
            scheme_path=Path("/tmp/x.colors"),
            kdeglobals_path=Path("/tmp/kdeglobals"),
            apply_ok=True,
        )
        return PipelineResult(
            src="/tmp/wall.jpg",
            palette=pal,
            disk=disk,
            notify_ok=True,
            notify_msg="ok",
        )

    monkeypatch.setattr(wallpaper_daemon, "generate_and_apply_from_wallpaper", fake_apply)
    wallpaper_daemon._STOP = False
    wallpaper_daemon.run_loop(app)
    assert apply_calls == ["ok"]
