"""Primary window with Colorizer and Conky tabs."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QSize, Qt, QThread
from PyQt6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from plasmacolorizer.conky.templating import context_from_palette, render_template
from plasmacolorizer.core import wallpaper as wp
from plasmacolorizer.core.palette import MaterialPalette
from plasmacolorizer.workers import GenerateSchemeWorker


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("PlasmaColorizer")
        self.resize(QSize(900, 640))

        self._last_palette: MaterialPalette | None = None
        self._thread: QThread | None = None

        tabs = QTabWidget()
        tabs.addTab(self._build_color_tab(), "Colorizer")
        tabs.addTab(self._build_conky_tab(), "Conky")
        self.setCentralWidget(tabs)

    # --- Colorizer tab -------------------------------------------------
    def _build_color_tab(self) -> QWidget:
        outer = QWidget()
        layout = QVBoxLayout(outer)
        layout.setSpacing(14)

        box = QGroupBox("Wallpaper and extraction")
        form = QFormLayout()
        self._path_display = QLineEdit()
        self._path_display.setReadOnly(True)
        self._path_display.setPlaceholderText("Detected wallpaper path appears here")

        self._manual_path = QLineEdit()
        self._manual_path.setPlaceholderText("Optional: explicit image path override")

        path_row = QHBoxLayout()
        path_row.addWidget(self._path_display, 1)
        btn_detect = QPushButton("Detect")
        btn_detect.setObjectName("secondary")
        btn_detect.clicked.connect(self._on_detect_wallpaper)
        path_row.addWidget(btn_detect)
        form.addRow("Current", path_row)
        form.addRow("Override", self._manual_path)

        self._monitor = QSpinBox()
        self._monitor.setRange(0, 16)
        self._monitor.setValue(0)

        self._quality = QSpinBox()
        self._quality.setRange(1, 10)
        self._quality.setValue(4)
        self._quality.setToolTip("Quantizer quality: higher = more sampling work")

        self._dark_combo = QComboBox()
        self._dark_combo.addItems(["Follow KDE", "Force dark", "Force light"])

        green_row = QHBoxLayout()
        self._green_slider = QSlider(Qt.Orientation.Horizontal)
        self._green_slider.setRange(0, 100)
        self._green_slider.setValue(0)
        self._green_label = QLabel("0%")
        self._green_slider.valueChanged.connect(lambda v: self._green_label.setText(f"{v}%"))
        green_row.addWidget(self._green_slider, 1)
        green_row.addWidget(self._green_label)

        form.addRow("Screen index", self._monitor)
        form.addRow("Quantizer quality", self._quality)
        form.addRow("UI mode", self._dark_combo)
        form.addRow("Green accent bias", green_row)

        box.setLayout(form)
        layout.addWidget(box)

        actions = QHBoxLayout()
        self._apply_btn = QPushButton("Generate and apply scheme")
        self._apply_btn.clicked.connect(self._on_generate)
        clear_manual = QPushButton("Clear override")
        clear_manual.setObjectName("secondary")
        clear_manual.clicked.connect(self._manual_path.clear)
        actions.addWidget(self._apply_btn)
        actions.addWidget(clear_manual)
        actions.addStretch(1)
        layout.addLayout(actions)

        log_box = QGroupBox("Log")
        log_layout = QVBoxLayout()
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setMinimumHeight(200)
        log_layout.addWidget(self._log)
        log_box.setLayout(log_layout)
        layout.addWidget(log_box)

        self._append_log("Ready. Use Detect to read the active Plasma wallpaper.")
        return outer

    def _dark_choice(self) -> bool | None:
        idx = self._dark_combo.currentIndex()
        return None if idx == 0 else (True if idx == 1 else False)

    def _append_log(self, msg: str) -> None:
        self._log.append(msg)

    def _on_detect_wallpaper(self) -> None:
        try:
            path = wp.current_wallpaper_image_path(self._monitor.value())
            self._path_display.setText(path)
            self._append_log(f"Wallpaper: {path}")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Wallpaper", str(exc))
            self._append_log(f"Detect failed: {exc}")

    def _on_generate(self) -> None:
        if self._thread and self._thread.isRunning():
            self._append_log("Already running.")
            return

        manual = self._manual_path.text().strip() or None
        self._apply_btn.setEnabled(False)
        self._append_log("Working…")

        thread = QThread()
        worker = GenerateSchemeWorker(
            monitor=self._monitor.value(),
            manual_path=manual,
            green_strength=self._green_slider.value() / 100.0,
            dark=self._dark_choice(),
            quality=self._quality.value(),
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_worker_finished)
        worker.failed.connect(self._on_worker_failed)
        thread.finished.connect(lambda: self._apply_btn.setEnabled(True))
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)

        self._thread = thread
        thread.start()

    def _on_worker_finished(self, payload: object) -> None:
        src, mpl, written = payload  # type: ignore[misc]
        self._last_palette = mpl
        self._path_display.setText(str(src))
        self._append_log(f"Applied scheme → {written}")
        self._append_log(
            f"Palette: dark={mpl.is_dark}, primary={mpl.colors.get('primary', (0,0,0))}"
        )
        QMessageBox.information(self, "PlasmaColorizer", "Color scheme generated and applied.")

    def _on_worker_failed(self, message: str) -> None:
        self._append_log(f"Error: {message}")
        QMessageBox.critical(self, "PlasmaColorizer", message)

    # --- Conky tab -----------------------------------------------------
    def _build_conky_tab(self) -> QWidget:
        wrap = QWidget()
        root = QVBoxLayout(wrap)

        hint = QLabel(
            "Use <code>{{token}}</code> placeholders (e.g. <code>{{primary}}</code>, "
            "<code>{{on_surface}}</code>, <code>{{surface}}</code>). "
            "Tokens are filled from the last successful palette run on the Colorizer tab."
        )
        hint.setWordWrap(True)
        hint.setTextFormat(Qt.TextFormat.RichText)
        root.addWidget(hint)

        grid = QFormLayout()
        self._conky_in = QLineEdit()
        self._conky_out = QLineEdit()
        browse_in = QPushButton("Browse…")
        browse_in.setObjectName("secondary")
        browse_in.clicked.connect(self._pick_conky_in)
        browse_out = QPushButton("Browse…")
        browse_out.setObjectName("secondary")
        browse_out.clicked.connect(self._pick_conky_out)

        in_row = QHBoxLayout()
        in_row.addWidget(self._conky_in, 1)
        in_row.addWidget(browse_in)
        out_row = QHBoxLayout()
        out_row.addWidget(self._conky_out, 1)
        out_row.addWidget(browse_out)

        grid.addRow("Template file", in_row)
        grid.addRow("Output file", out_row)
        root.addLayout(grid)

        btn_row = QHBoxLayout()
        preview_btn = QPushButton("Preview render")
        preview_btn.clicked.connect(self._conky_preview)
        save_btn = QPushButton("Save rendered")
        save_btn.clicked.connect(self._conky_save)
        btn_row.addWidget(preview_btn)
        btn_row.addWidget(save_btn)
        btn_row.addStretch(1)
        root.addLayout(btn_row)

        preview_box = QGroupBox("Preview")
        pv_layout = QVBoxLayout()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self._conky_preview = QTextEdit()
        self._conky_preview.setReadOnly(True)
        self._conky_preview.setMinimumHeight(260)
        scroll.setWidget(self._conky_preview)
        pv_layout.addWidget(scroll)
        preview_box.setLayout(pv_layout)
        root.addWidget(preview_box)
        return wrap

    def _require_palette(self) -> MaterialPalette | None:
        if self._last_palette is None:
            QMessageBox.information(
                self,
                "Conky",
                "Generate a palette on the Colorizer tab first.",
            )
            return None
        return self._last_palette

    def _pick_conky_in(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Conky template", str(Path.home()))
        if path:
            self._conky_in.setText(path)

    def _pick_conky_out(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Rendered Conky config", str(Path.home() / "conky.conf"))
        if path:
            self._conky_out.setText(path)

    def _read_template_file(self) -> str:
        p = Path(self._conky_in.text().strip())
        if not p.is_file():
            raise FileNotFoundError(f"Template not found: {p}")
        return p.read_text(encoding="utf-8", errors="replace")

    def _conky_preview(self) -> None:
        pal = self._require_palette()
        if pal is None:
            return
        try:
            text = self._read_template_file()
        except OSError as exc:
            QMessageBox.warning(self, "Conky", str(exc))
            return
        ctx = context_from_palette(pal)
        self._conky_preview.setPlainText(render_template(text, ctx))

    def _conky_save(self) -> None:
        pal = self._require_palette()
        if pal is None:
            return
        out = Path(self._conky_out.text().strip())
        if not out.parent.is_dir():
            QMessageBox.warning(self, "Conky", f"Output directory missing: {out.parent}")
            return
        try:
            text = self._read_template_file()
        except OSError as exc:
            QMessageBox.warning(self, "Conky", str(exc))
            return
        ctx = context_from_palette(pal)
        rendered = render_template(text, ctx)
        out.write_text(rendered, encoding="utf-8")
        QMessageBox.information(self, "Conky", f"Wrote {out}")
