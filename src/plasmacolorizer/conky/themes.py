"""Bundled Conky visual themes (chrome/layout only).

Colors are deliberately NOT part of a theme — every preset still receives
``primary`` / ``secondary`` / ``onSurface`` / etc. from the Material You
palette via ``context_from_palette``.  A theme only changes the **style** of
the panels: body font, section heading wrappers, divider widget, and (for
the bundled ``system`` preset) whether CPU/RAM are drawn as text, bars, or
graphs.

The 8 bundled themes are inspired by long-running Conky community styles
(harmattan-style brackets, mono dashboards, graph spectrums, etc.) but the
implementation is original to PlasmaColorizer.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ConkyTheme:
    theme_id: str
    label: str
    font_body: str
    title_open: str
    title_close: str
    section_divider: str
    # If set, dictates the bundled ``system`` preset widget style
    # (``text`` | ``bar`` | ``graph``) and the user's ``system_stats_style``
    # setting is ignored for that preset.  ``None`` = use the user's setting.
    system_widget_style: str | None


DEFAULT_THEME_ID = "material"


_THEMES: tuple[ConkyTheme, ...] = (
    ConkyTheme(
        theme_id="material",
        label="Material Minimal (default)",
        font_body="sans:size=10",
        title_open="",
        title_close="",
        section_divider="${font sans:size=8}${hr 1}${font}",
        system_widget_style=None,
    ),
    ConkyTheme(
        theme_id="harmattan",
        label="Harmattan Lite",
        font_body="sans:size=10",
        title_open="[ ",
        title_close=" ]",
        section_divider="${hr 2}",
        system_widget_style=None,
    ),
    ConkyTheme(
        theme_id="gotham",
        label="Gotham Mono",
        font_body="DejaVu Sans Mono:size=9",
        title_open="",
        title_close="",
        section_divider="${stippled_hr 1 2}",
        system_widget_style="text",
    ),
    ConkyTheme(
        theme_id="hexagon",
        label="Hexagon Terminal",
        font_body="DejaVu Sans Mono:size=10",
        title_open=">> ",
        title_close="",
        section_divider="═════════════════════",
        system_widget_style="text",
    ),
    ConkyTheme(
        theme_id="bars",
        label="Bar Dashboard",
        font_body="sans:size=10",
        title_open="■ ",
        title_close="",
        section_divider="${hr 1}",
        system_widget_style="bar",
    ),
    ConkyTheme(
        theme_id="spectrum",
        label="Conky Spectrum",
        font_body="sans:size=10",
        title_open="▌ ",
        title_close="",
        section_divider="${hr 1}",
        system_widget_style="graph",
    ),
    ConkyTheme(
        theme_id="sidebar",
        label="Sidebar Strip",
        font_body="sans:size=9",
        title_open="· ",
        title_close="",
        section_divider="${stippled_hr 1 2}",
        system_widget_style="text",
    ),
    ConkyTheme(
        theme_id="bold",
        label="Bold Headlines",
        font_body="sans:size=10",
        title_open="${font sans:size=12:bold}",
        title_close="${font}",
        section_divider="${hr 1}",
        system_widget_style=None,
    ),
)


THEMES: dict[str, ConkyTheme] = {t.theme_id: t for t in _THEMES}


def theme_choices() -> tuple[ConkyTheme, ...]:
    """Themes in display order (used to populate the UI combo)."""
    return _THEMES


def get_theme(theme_id: str | None) -> ConkyTheme:
    if theme_id and theme_id in THEMES:
        return THEMES[theme_id]
    return THEMES[DEFAULT_THEME_ID]
