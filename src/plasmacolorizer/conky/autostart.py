"""Login autostart: respawn the bundled Conky presets that were running last session.

Invoked via ``~/.config/autostart/plasmacolorizer-conky.desktop`` (see
``plasmacolorizer.conky.presets.install_autostart_entry``).  Uses the
already-rendered ``~/.local/share/plasmacolorizer/conky/rendered/<id>.conf``
files so we do not have to re-quantize the wallpaper at login.
"""

from __future__ import annotations

import argparse
import sys

from plasmacolorizer.conky import presets
from plasmacolorizer.conky.settings_store import load_conky_settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="plasmacolorizer.conky.autostart")
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress the summary line printed to stdout.",
    )
    args = parser.parse_args(argv)

    s = load_conky_settings()
    if not s.autostart_enabled:
        if not args.quiet:
            sys.stdout.write("PlasmaColorizer autostart: disabled in settings; nothing to do.\n")
        return 0

    started: list[str] = []
    errors: list[str] = []
    for pid in s.autostart_preset_ids:
        if pid not in presets.PRESETS:
            continue
        if presets.is_preset_running(pid):
            continue
        ok, msg = presets.start_preset_from_rendered(pid)
        if ok:
            started.append(pid)
        else:
            errors.append(f"{pid}: {msg}")

    if not args.quiet:
        sys.stdout.write(
            "PlasmaColorizer autostart: started=["
            + ", ".join(started)
            + "] errors=["
            + "; ".join(errors)
            + "]\n"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
