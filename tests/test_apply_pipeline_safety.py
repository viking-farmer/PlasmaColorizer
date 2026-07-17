"""Apply pipeline plasmashell-restart safety."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from plasmacolorizer.core.apply_pipeline import generate_and_apply_from_wallpaper
from plasmacolorizer.core.app_settings import AppSettings
from plasmacolorizer.core.palette import MaterialPalette
from plasmacolorizer.core.plasma_scheme import DiskApplyResult


def _pal() -> MaterialPalette:
    return MaterialPalette(is_dark=True, colors={"primary": (1, 2, 3)})


def _disk_ok() -> DiskApplyResult:
    return DiskApplyResult(
        scheme_path=Path("/tmp/x.colors"),
        kdeglobals_path=Path("/tmp/kdeglobals"),
        apply_ok=True,
    )


def test_daemon_path_never_restarts_plasmashell(monkeypatch: pytest.MonkeyPatch) -> None:
    restarts: list[str] = []

    monkeypatch.setattr(
        "plasmacolorizer.core.apply_pipeline.resolve_wallpaper_for_apply",
        lambda app, src_path=None: "/tmp/wall.jpg",
    )
    monkeypatch.setattr(
        "plasmacolorizer.core.apply_pipeline.compute_material_palette_from_wallpaper",
        lambda **_k: _pal(),
    )
    monkeypatch.setattr(
        "plasmacolorizer.core.apply_pipeline.plasma_scheme.apply_material_palette_to_disk",
        lambda *_a, **_k: _disk_ok(),
    )
    monkeypatch.setattr(
        "plasmacolorizer.core.apply_pipeline.plasma_scheme.notify_kde_palette_change",
        lambda *_a, **_k: (True, "ok"),
    )
    monkeypatch.setattr(
        "plasmacolorizer.core.apply_pipeline.plasma_scheme.restart_plasmashell",
        lambda **_k: restarts.append("restarted") or (True, "restarted"),
    )
    monkeypatch.setattr(
        "plasmacolorizer.core.apply_pipeline.record_applied_wallpaper_fingerprint",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "plasmacolorizer.core.apply_pipeline.apply_lock",
        __import__("contextlib").nullcontext,
    )

    app = AppSettings(restart_plasma_after_apply=True)
    result = generate_and_apply_from_wallpaper(
        app_settings=app,
        allow_plasmashell_restart=False,
    )
    assert restarts == []
    assert result.restarted_plasma is False
    assert "skipped" in result.restart_msg


def test_ui_path_restarts_when_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    restarts: list[str] = []

    monkeypatch.setattr(
        "plasmacolorizer.core.apply_pipeline.resolve_wallpaper_for_apply",
        lambda app, src_path=None: "/tmp/wall.jpg",
    )
    monkeypatch.setattr(
        "plasmacolorizer.core.apply_pipeline.compute_material_palette_from_wallpaper",
        lambda **_k: _pal(),
    )
    monkeypatch.setattr(
        "plasmacolorizer.core.apply_pipeline.plasma_scheme.apply_material_palette_to_disk",
        lambda *_a, **_k: _disk_ok(),
    )
    monkeypatch.setattr(
        "plasmacolorizer.core.apply_pipeline.plasma_scheme.notify_kde_palette_change",
        lambda *_a, **_k: (True, "ok"),
    )
    monkeypatch.setattr(
        "plasmacolorizer.core.apply_pipeline.plasma_scheme.restart_plasmashell",
        lambda **_k: restarts.append("restarted") or (True, "restarted"),
    )
    monkeypatch.setattr(
        "plasmacolorizer.core.apply_pipeline.record_applied_wallpaper_fingerprint",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "plasmacolorizer.core.apply_pipeline.apply_lock",
        __import__("contextlib").nullcontext,
    )

    app = AppSettings(restart_plasma_after_apply=True)
    result = generate_and_apply_from_wallpaper(
        app_settings=app,
        allow_plasmashell_restart=True,
    )
    assert restarts == ["restarted"]
    assert result.restarted_plasma is True


def test_restart_plasma_default_is_false() -> None:
    assert AppSettings().restart_plasma_after_apply is False
    assert AppSettings().wallpaper_daemon_enabled is False


def test_restart_plasmashell_prefers_systemctl(monkeypatch: pytest.MonkeyPatch) -> None:
    from plasmacolorizer.core import plasma_scheme

    calls: list[list[str]] = []

    def fake_which(name: str) -> str | None:
        return f"/usr/bin/{name}" if name in ("systemctl", "kquitapp6", "kstart") else None

    def fake_run(cmd, **_k):  # noqa: ANN001
        calls.append(list(cmd))

        class R:
            returncode = 0
            stdout = ""
            stderr = ""

        return R()

    monkeypatch.setattr(plasma_scheme.shutil, "which", fake_which)
    monkeypatch.setattr(plasma_scheme.subprocess, "run", fake_run)
    monkeypatch.setattr(plasma_scheme, "_wait_for_plasmashell", lambda timeout_s=5.0: True)
    monkeypatch.setattr(plasma_scheme, "plasmashell_dbus_ready", lambda: True)
    monkeypatch.setattr(plasma_scheme, "plasmashell_process_running", lambda: True)

    ok, msg = plasma_scheme.restart_plasmashell()
    assert ok
    systemctl_calls = [c for c in calls if c and "systemctl" in c[0]]
    assert systemctl_calls
    assert systemctl_calls[0][:3] == ["/usr/bin/systemctl", "--user", "restart"]
    assert "plasma-plasmashell.service" in systemctl_calls[0][-1]
    assert "systemctl" in msg


def test_restart_plasmashell_never_calls_kquitapp(monkeypatch: pytest.MonkeyPatch) -> None:
    from plasmacolorizer.core import plasma_scheme

    calls: list[list[str]] = []

    def fake_which(name: str) -> str | None:
        return f"/usr/bin/{name}" if name in ("systemctl", "kquitapp6", "kstart") else None

    def fake_run(cmd, **_k):  # noqa: ANN001
        calls.append(list(cmd))

        class R:
            returncode = 1
            stdout = ""
            stderr = "failed"

        return R()

    monkeypatch.setattr(plasma_scheme.shutil, "which", fake_which)
    monkeypatch.setattr(plasma_scheme.subprocess, "run", fake_run)
    monkeypatch.setattr(plasma_scheme, "_wait_for_plasmashell", lambda timeout_s=5.0: False)
    monkeypatch.setattr(plasma_scheme, "plasmashell_dbus_ready", lambda: False)
    monkeypatch.setattr(plasma_scheme, "plasmashell_process_running", lambda: False)

    ok, msg = plasma_scheme.restart_plasmashell()
    assert ok is False
    assert all("kquitapp" not in " ".join(c) for c in calls)
    assert "recover" in msg or "start plasma-plasmashell" in msg
