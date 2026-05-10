"""Minimal Conky-style templates using `{{token}}` placeholders."""

from __future__ import annotations

import re
from typing import Mapping

from plasmacolorizer.core.palette import MaterialPalette, rgb_to_hex

_TOKEN_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")


def _camel_to_snake(name: str) -> str:
    s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


def context_from_palette(pal: MaterialPalette) -> dict[str, str]:
    """Build `{{token}}` context: camelCase names, snake_case aliases, hex (`*_hex`)."""

    ctx: dict[str, str] = {}
    for name, rgb in pal.colors.items():
        h = rgb_to_hex(rgb)
        ctx[name] = h
        ctx[_camel_to_snake(name)] = h
        ctx[f"{name}_hex"] = h
    ctx["is_dark"] = "1" if pal.is_dark else "0"
    return ctx


def render_template(text: str, context: Mapping[str, str]) -> str:
    """Replace `{{name}}` with `context['name']` (empty string if missing)."""

    def repl(match: re.Match[str]) -> str:
        key = match.group(1)
        return str(context.get(key, ""))

    return _TOKEN_RE.sub(repl, text)
