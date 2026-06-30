"""Optional per-component KDE color overrides (on top of automated mapping)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from plasmacolorizer.core.palette import MaterialPalette, rgb_to_hex

# Curated tokens shown in the palette picker grid (readable names + common roles).
PALETTE_PICKER_TOKENS: tuple[str, ...] = (
    "primary",
    "onPrimary",
    "primaryContainer",
    "onPrimaryContainer",
    "primaryFixed",
    "secondary",
    "onSecondary",
    "secondaryContainer",
    "tertiary",
    "onTertiary",
    "surface",
    "onSurface",
    "surfaceVariant",
    "onSurfaceVariant",
    "surfaceContainer",
    "surfaceContainerHigh",
    "surfaceContainerHighest",
    "surfaceContainerLow",
    "outline",
    "error",
    "onError",
    "inversePrimary",
    "inverseOnSurface",
)


@dataclass(frozen=True)
class PlasmaComponent:
    id: str
    label: str
    section: str
    key: str
    material_token: str


PLASMA_COMPONENTS: tuple[PlasmaComponent, ...] = (
    PlasmaComponent("panel_background", "Panel background", "Colors:Window", "BackgroundNormal", "surfaceContainer"),
    PlasmaComponent(
        "panel_background_alt", "Panel background (alt)", "Colors:Window", "BackgroundAlternate", "surfaceContainerHigh",
    ),
    PlasmaComponent("panel_text", "Panel text", "Colors:Window", "ForegroundNormal", "onSurface"),
    PlasmaComponent("panel_accent", "Panel accent / active", "Colors:Window", "ForegroundActive", "primary"),
    PlasmaComponent("panel_focus", "Panel focus ring", "Colors:Window", "DecorationFocus", "primary"),
    PlasmaComponent("launcher_background", "Launcher / menu background", "Colors:View", "BackgroundNormal", "surface"),
    PlasmaComponent("launcher_text", "Launcher / menu text", "Colors:View", "ForegroundNormal", "onSurface"),
    PlasmaComponent(
        "selection_background", "Selection highlight", "Colors:Selection", "BackgroundNormal", "primary",
    ),
    PlasmaComponent("selection_text", "Selection text", "Colors:Selection", "ForegroundNormal", "onPrimary"),
    PlasmaComponent(
        "tooltip_background", "Tooltip background", "Colors:Tooltip", "BackgroundNormal", "surfaceContainerHigh",
    ),
    PlasmaComponent(
        "titlebar_background", "Title bar", "Colors:Header", "BackgroundNormal", "surfaceContainerHigh",
    ),
    PlasmaComponent("button_background", "Buttons", "Colors:Button", "BackgroundNormal", "surfaceContainerHigh"),
)

COMPONENT_BY_ID: dict[str, PlasmaComponent] = {c.id: c for c in PLASMA_COMPONENTS}


@dataclass(frozen=True)
class ComponentColorOverride:
    source: Literal["palette", "custom"]
    palette_token: str | None = None
    rgb: tuple[int, int, int] | None = None

    def to_json_dict(self) -> dict[str, Any]:
        if self.source == "palette":
            return {"source": "palette", "palette_token": self.palette_token or "primary"}
        r, g, b = self.rgb or (0, 0, 0)
        return {"source": "custom", "rgb": [int(r), int(g), int(b)]}

    @classmethod
    def from_json_dict(cls, data: dict[str, Any] | None) -> ComponentColorOverride | None:
        if not data or not isinstance(data, dict):
            return None
        source = str(data.get("source", "")).strip().lower()
        if source == "palette":
            token = str(data.get("palette_token") or "primary").strip()
            return cls(source="palette", palette_token=token)
        if source == "custom":
            raw = data.get("rgb")
            if isinstance(raw, (list, tuple)) and len(raw) >= 3:
                return cls(
                    source="custom",
                    rgb=(int(raw[0]) & 255, int(raw[1]) & 255, int(raw[2]) & 255),
                )
        return None


def overrides_from_settings_dict(
    data: dict[str, Any] | None,
) -> dict[str, ComponentColorOverride]:
    if not data:
        return {}
    out: dict[str, ComponentColorOverride] = {}
    for comp_id, raw in data.items():
        if comp_id not in COMPONENT_BY_ID:
            continue
        parsed = ComponentColorOverride.from_json_dict(raw if isinstance(raw, dict) else None)
        if parsed is not None:
            out[comp_id] = parsed
    return out


def overrides_to_settings_dict(
    overrides: dict[str, ComponentColorOverride],
) -> dict[str, dict[str, Any]]:
    return {k: v.to_json_dict() for k, v in overrides.items()}


def resolve_override_rgb(
    override: ComponentColorOverride,
    palette: MaterialPalette,
) -> tuple[int, int, int]:
    if override.source == "palette":
        token = override.palette_token or "primary"
        if token in palette.colors:
            return palette.get(token)
        return palette.get("primary")
    if override.rgb is not None:
        r, g, b = override.rgb
        return (int(r) & 255, int(g) & 255, int(b) & 255)
    return palette.get("primary")


def apply_component_color_overrides(
    sections: dict[str, dict[str, str]],
    overrides: dict[str, ComponentColorOverride] | None,
    *,
    palette: MaterialPalette | None = None,
) -> dict[str, dict[str, str]]:
    if not overrides or palette is None:
        return sections
    out = {name: dict(rows) for name, rows in sections.items()}
    for comp_id, override in overrides.items():
        comp = COMPONENT_BY_ID.get(comp_id)
        if comp is None:
            continue
        rgb = resolve_override_rgb(override, palette)
        csv = f"{rgb[0]},{rgb[1]},{rgb[2]}"
        if comp.section not in out:
            out[comp.section] = {}
        out[comp.section][comp.key] = csv
    return out


def effective_component_rgb(
    comp_id: str,
    sections: dict[str, dict[str, str]],
    palette: MaterialPalette,
) -> tuple[int, int, int] | None:
    comp = COMPONENT_BY_ID.get(comp_id)
    if comp is None:
        return None
    sec = sections.get(comp.section, {})
    raw = sec.get(comp.key)
    if not raw:
        if comp.material_token in palette.colors:
            return palette.get(comp.material_token)
        return None
    try:
        parts = [int(x.strip()) for x in raw.split(",")[:3]]
        if len(parts) == 3:
            return (parts[0], parts[1], parts[2])
    except ValueError:
        pass
    return None


def component_tooltip(
    comp_id: str,
    *,
    sections: dict[str, dict[str, str]] | None,
    palette: MaterialPalette | None,
    override: ComponentColorOverride | None,
) -> str:
    comp = COMPONENT_BY_ID.get(comp_id)
    if comp is None:
        return ""
    if override is not None:
        if override.source == "palette":
            token = override.palette_token or "primary"
            return f"{comp.label} — manual (palette: {token})"
        if override.rgb:
            return f"{comp.label} — manual ({rgb_to_hex(override.rgb)})"
    if sections is not None and palette is not None:
        rgb = effective_component_rgb(comp_id, sections, palette)
        if rgb:
            return f"{comp.label} — automated: {comp.material_token} → {rgb_to_hex(rgb)}"
    return f"{comp.label} — automated ({comp.material_token})"
