"""Background workers for heavy KDE / image tasks."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal

from plasmacolorizer.core import kde_prefs
from plasmacolorizer.core import palette as pal
from plasmacolorizer.core import plasma_scheme
from plasmacolorizer.core import wallpaper as wp


class GenerateSchemeWorker(QObject):
    finished = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(
        self,
        *,
        monitor: int,
        manual_path: str | None,
        green_strength: float,
        dark: bool | None,
        quality: int,
    ) -> None:
        super().__init__()
        self._monitor = monitor
        self._manual_path = manual_path
        self._green = green_strength
        self._dark = dark
        self._quality = quality

    def run(self) -> None:
        try:
            path: str | None = self._manual_path.strip() if self._manual_path else None
            if path and Path(path).is_file():
                src = path
            else:
                src = wp.current_wallpaper_image_path(self._monitor)

            seed = pal.seed_color_from_image(src, quality=self._quality)
            if self._green > 0:
                seed = pal.apply_green_bias(seed, self._green)

            dark = bool(self._dark) if self._dark is not None else kde_prefs.is_plasma_dark_scheme_preferred()
            mpl = pal.build_palette(seed, dark=dark)
            body = plasma_scheme.render_colors_file(mpl)
            written = plasma_scheme.write_scheme_file(body)
            plasma_scheme.apply_scheme()
            self.finished.emit((src, mpl, written))
        except Exception as exc:  # noqa: BLE001 — surfaced to UI
            self.failed.emit(str(exc))
