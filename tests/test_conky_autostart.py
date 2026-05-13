"""Login autostart CLI for Conky bundled presets."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from plasmacolorizer.conky import autostart, presets
from plasmacolorizer.conky.settings_store import ConkySettings, save_conky_settings


def test_autostart_disabled_returns_zero(monkeypatch: pytest.MonkeyPatch, tmp_path, capsys) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    save_conky_settings(ConkySettings(autostart_enabled=False, autostart_preset_ids=["system"]))
    rc = autostart.main([])
    assert rc == 0
    assert "disabled" in capsys.readouterr().out


def test_autostart_starts_saved_presets(monkeypatch: pytest.MonkeyPatch, tmp_path, capsys) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    save_conky_settings(
        ConkySettings(autostart_enabled=True, autostart_preset_ids=["system", "weather", "bogus"])
    )

    calls: list[str] = []

    def fake_start_from_rendered(preset_id: str) -> tuple[bool, str]:
        calls.append(preset_id)
        return True, f"started {preset_id}"

    with patch.object(presets, "is_preset_running", return_value=False):
        with patch.object(presets, "start_preset_from_rendered", side_effect=fake_start_from_rendered):
            rc = autostart.main([])

    assert rc == 0
    # "bogus" should be skipped since it is not a real preset id.
    assert calls == ["system", "weather"]
    out = capsys.readouterr().out
    assert "started=[system, weather]" in out


def test_autostart_skips_running(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    save_conky_settings(
        ConkySettings(autostart_enabled=True, autostart_preset_ids=["system", "weather"])
    )

    calls: list[str] = []

    def fake_start(preset_id: str) -> tuple[bool, str]:
        calls.append(preset_id)
        return True, "ok"

    # Pretend "system" is already running; only "weather" should be (re-)started.
    with patch.object(presets, "is_preset_running", side_effect=lambda pid: pid == "system"):
        with patch.object(presets, "start_preset_from_rendered", side_effect=fake_start):
            rc = autostart.main(["--quiet"])

    assert rc == 0
    assert calls == ["weather"]
