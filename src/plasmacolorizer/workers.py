"""Background workers for heavy KDE / image tasks."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal

from plasmacolorizer.core import kde_prefs
from plasmacolorizer.core import palette as pal
from plasmacolorizer.core import plasma_scheme
from plasmacolorizer.core import wallpaper as wp
from plasmacolorizer.core.palette import MaterialPalette


@dataclass
class WorkerResult:
    src: str
    palette: MaterialPalette
    scheme_path: Path
    apply_ok: bool
    apply_error: str = ""


class GenerateSchemeWorker(QObject):
    finished = pyqtSignal(object)        # WorkerResult
    failed   = pyqtSignal(str)
    progress = pyqtSignal(str)           # step description for the log

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
            # ── Step 1: resolve wallpaper ──────────────────────────────
            path: str | None = self._manual_path.strip() if self._manual_path else None
            if path and Path(path).is_file():
                src = path
            else:
                self.progress.emit("Detecting wallpaper via Plasma DBus…")
                src = wp.current_wallpaper_image_path(self._monitor)

            self.progress.emit(f"Wallpaper: {src}")

            # ── Step 2: extract colors ─────────────────────────────────
            self.progress.emit(f"Quantizing image (quality={self._quality})…")
            seed = pal.seed_color_from_image(src, quality=self._quality)

            if self._green > 0:
                self.progress.emit(f"Applying green accent bias ({self._green*100:.0f}%)…")
                seed = pal.apply_green_bias(seed, self._green)

            # ── Step 3: build palette ──────────────────────────────────
            dark = bool(self._dark) if self._dark is not None else kde_prefs.is_plasma_dark_scheme_preferred()
            self.progress.emit(f"Building Material You palette (dark={dark})…")
            mpl = pal.build_palette(seed, dark=dark)

            # ── Step 4: write .colors file ────────────────────────────
            self.progress.emit("Writing Plasma .colors file…")
            body = plasma_scheme.render_colors_file(mpl)
            written = plasma_scheme.write_scheme_file(body)
            self.progress.emit(f"Scheme written → {written}")

            # ── Step 5: apply (non-fatal) ─────────────────────────────
            self.progress.emit("Running plasma-apply-colorscheme…")
            apply_ok = True
            apply_error = ""
            try:
                plasma_scheme.apply_scheme()
                self.progress.emit("plasma-apply-colorscheme succeeded.")
            except Exception as exc:  # noqa: BLE001
                apply_ok = False
                apply_error = str(exc)
                self.progress.emit(f"Apply warning: {exc}")

            self.finished.emit(WorkerResult(
                src=src,
                palette=mpl,
                scheme_path=written,
                apply_ok=apply_ok,
                apply_error=apply_error,
            ))

        except Exception as exc:  # noqa: BLE001 — surfaced to UI
            self.failed.emit(str(exc))
