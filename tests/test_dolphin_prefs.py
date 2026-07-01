"""Dolphin color-scheme pinning (dolphinrc)."""

from __future__ import annotations

from pathlib import Path

import pytest

from plasmacolorizer.core.dolphin_prefs import (
    dolphin_cohesion_warnings,
    patch_dolphin_follow_system_colorscheme,
    read_dolphin_pinned_scheme,
)


def test_patch_dolphin_follow_system_colorscheme(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg = tmp_path / ".config"
    cfg.mkdir(parents=True)
    (cfg / "dolphinrc").write_text(
        "[UiSettings]\nColorScheme=MaterialYouDark\n",
        encoding="utf-8",
    )
    ok, msg = patch_dolphin_follow_system_colorscheme()
    assert ok
    assert "MaterialYouDark" in msg
    assert read_dolphin_pinned_scheme() == "*"


def test_dolphin_cohesion_warnings_stale_pin(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg = tmp_path / ".config"
    cfg.mkdir(parents=True)
    (cfg / "dolphinrc").write_text(
        "[UiSettings]\nColorScheme=MaterialYouDark\n",
        encoding="utf-8",
    )
    warnings = dolphin_cohesion_warnings()
    assert len(warnings) == 1
    assert "MaterialYouDark" in warnings[0]


def test_dolphin_cohesion_warnings_clear_after_patch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg = tmp_path / ".config"
    cfg.mkdir(parents=True)
    (cfg / "dolphinrc").write_text(
        "[UiSettings]\nColorScheme=MaterialYouDark\n",
        encoding="utf-8",
    )
    patch_dolphin_follow_system_colorscheme()
    assert dolphin_cohesion_warnings() == []
