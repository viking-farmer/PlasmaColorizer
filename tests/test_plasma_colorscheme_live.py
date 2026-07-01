"""Plasma color scheme live apply and reload stub."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from plasmacolorizer.core.plasma_scheme import (
    SCHEME_FILE_STEM,
    SCHEME_RELOAD_STEM,
    apply_plasma_colorscheme_live,
    write_scheme_file,
)


def test_write_scheme_file_creates_reload_stub(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    body = (
        "[General]\n"
        f"ColorScheme={SCHEME_FILE_STEM}\n"
        f"Name={SCHEME_FILE_STEM}\n\n"
        "[Colors:View]\nBackgroundNormal=1,2,3\n"
    )
    write_scheme_file(body)
    main = tmp_path / f".local/share/color-schemes/{SCHEME_FILE_STEM}.colors"
    reload = tmp_path / f".local/share/color-schemes/{SCHEME_RELOAD_STEM}.colors"
    assert main.is_file()
    assert reload.is_file()
    assert f"Name={SCHEME_RELOAD_STEM}" in reload.read_text(encoding="utf-8")


def test_apply_plasma_colorscheme_live_toggles_reload_first(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    write_scheme_file(
        f"[General]\nColorScheme={SCHEME_FILE_STEM}\nName={SCHEME_FILE_STEM}\n",
    )
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):  # noqa: ANN001
        calls.append(list(cmd))
        return MagicMock(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("plasmacolorizer.core.plasma_scheme.shutil.which", lambda _: "/usr/bin/plasma-apply-colorscheme")
    monkeypatch.setattr("plasmacolorizer.core.plasma_scheme.subprocess.run", fake_run)
    ok, msg = apply_plasma_colorscheme_live()
    assert ok
    assert len(calls) == 2
    assert calls[0][-1] == SCHEME_RELOAD_STEM
    assert calls[1][-1] == SCHEME_FILE_STEM
    assert SCHEME_RELOAD_STEM in msg
