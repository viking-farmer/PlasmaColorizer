"""Dialog to pick a component color from the palette or a custom color (dropper)."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QColorDialog,
)

from plasmacolorizer.core.component_colors import (
    PALETTE_PICKER_TOKENS,
    ComponentColorOverride,
    PlasmaComponent,
)
from plasmacolorizer.core.palette import MaterialPalette, rgb_to_hex


class ComponentColorDialog(QDialog):
    """Pick a palette token or custom RGB for one Plasma component."""

    def __init__(
        self,
        parent: QWidget | None,
        *,
        component: PlasmaComponent,
        palette: MaterialPalette,
        current: ComponentColorOverride | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Color — {component.label}")
        self._component = component
        self._palette = palette
        self._result: ComponentColorOverride | None = None

        layout = QVBoxLayout(self)
        hint = QLabel(
            f"Choose a color for <b>{component.label}</b>. "
            "Palette picks stay linked to regenerated colors; custom colors stay fixed."
        )
        hint.setWordWrap(True)
        hint.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(hint)

        tabs = QTabWidget()
        tabs.addTab(self._build_palette_tab(), "From palette")
        tabs.addTab(self._build_custom_tab(current), "Custom color")
        layout.addWidget(tabs)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.resize(520, 420)

    def _build_palette_tab(self) -> QWidget:
        outer = QWidget()
        outer_layout = QVBoxLayout(outer)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        grid = QGridLayout(inner)
        grid.setSpacing(6)
        col = 0
        row = 0
        max_cols = 4
        for token in PALETTE_PICKER_TOKENS:
            if token not in self._palette.colors:
                continue
            rgb = self._palette.get(token)
            btn = QToolButton()
            btn.setMinimumSize(100, 36)
            hx = rgb_to_hex(rgb)
            btn.setText(token)
            btn.setToolTip(f"{token}  {hx}")
            btn.setStyleSheet(
                f"QToolButton {{ background-color: {hx}; border: 1px solid #555; "
                "border-radius: 4px; padding: 4px; }}"
            )
            btn.clicked.connect(lambda checked=False, t=token: self._pick_palette(t))
            grid.addWidget(btn, row, col)
            col += 1
            if col >= max_cols:
                col = 0
                row += 1
        scroll.setWidget(inner)
        outer_layout.addWidget(scroll)
        return outer

    def _build_custom_tab(self, current: ComponentColorOverride | None) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        if current is not None and current.source == "custom" and current.rgb:
            r, g, b = current.rgb
            initial = QColor(r, g, b)
        elif self._component.material_token in self._palette.colors:
            r, g, b = self._palette.get(self._component.material_token)
            initial = QColor(r, g, b)
        else:
            initial = QColor(128, 128, 128)
        layout.addWidget(QLabel(
            "Opens the system color dialog. On KDE Plasma this usually includes a screen color dropper."
        ))
        pick_btn = QPushButton("Choose custom color…")
        pick_btn.clicked.connect(lambda: self._pick_custom(initial))
        layout.addWidget(pick_btn)
        layout.addStretch(1)
        return w

    def _pick_palette(self, token: str) -> None:
        self._result = ComponentColorOverride(source="palette", palette_token=token)
        self.accept()

    def _pick_custom(self, initial: QColor) -> None:
        chosen = QColorDialog.getColor(
            initial, self, f"Custom color — {self._component.label}",
        )
        if not chosen.isValid():
            return
        self._result = ComponentColorOverride(
            source="custom",
            rgb=(chosen.red(), chosen.green(), chosen.blue()),
        )
        self.accept()

    def selected_override(self) -> ComponentColorOverride | None:
        return self._result
