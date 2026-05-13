# PlasmaColorizer

PyQt6 utility for **KDE Plasma** (Manjaro-friendly) that:

- Reads the active wallpaper via **`org.kde.PlasmaShell`** (DBus).
- Extracts a seed color with **materialyoucolor** and builds a Material You–style palette.
- Writes `~/.local/share/color-schemes/PlasmaColorizer.colors`, merges into `~/.config/kdeglobals`, and refreshes Plasma accent (see app sources).
- Optional **green accent bias** (shifts the seed hue toward green before scheme generation).
- Offers a **Conky** tab with **bundled presets** (system stats, shortcuts, ESV verse, Open-Meteo weather) plus custom `{{token}}` templates filled from the palette.

## Requirements

- Python 3.10+
- Plasma session with `org.kde.PlasmaShell` and related session services the app calls.
- `python-dbus` / **dbus-python** (see `pyproject.toml`).
- Optional: **`conky`** package to launch bundled presets from the UI.

## Install (editable, recommended)

```bash
cd ~/Projects/PlasmaColorizer
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Run the UI:

```bash
plasmacolorizer
# or
python -m plasmacolorizer
```

**Icon:** The app ships **PNG** (multiple sizes) and an **SVG** fallback, and sets them on the window. Plasma’s taskbar uses `setDesktopFileName("plasmacolorizer")` to match `plasmacolorizer.desktop`. **`run.sh`** copies PNGs into `~/.local/share/icons/hicolor/{NxN}/apps/` and the SVG into `scalable/apps/` so `Icon=plasmacolorizer` resolves reliably (SVG-only icons often look blank in Qt/KDE without extra plugins). If you launch only the `plasmacolorizer` binary, run **`run.sh` once** or copy the `src/plasmacolorizer/icons/plasmacolorizer_*.png` files into the matching `hicolor` folders.

## Usage notes

- **Wallpaper detection** works best with the standard **Image** wallpaper plugin (`org.kde.image`). Other plugins may not expose a file path; use the “Override” field to point at an image.
- **Dark / light** for generated Material schemes: choose *Follow KDE* (reads `ColorScheme` in `~/.config/kdeglobals`), or force dark/light.
- **Conky tab** fills tokens such as `{{primary}}`, `{{on_surface}}`, `{{surface}}`, etc., from the **effective** palette (Colorizer tab, including swatch overrides).
- **Bundled presets** (Start / Stop per preset, **Stop all**, **Apply colors to running Conkys**):
  - **System** — CPU, load, RAM, root disk free/used, network up/down (`wlo1` / `wlan0` / `eth0` when up).
  - **Shortcuts** — short static KDE-oriented cheat sheet (edit the template in the repo if you want different bindings).
  - **Verse** — text from the **ESV API** (Crossway). Register at [api.esv.org](https://api.esv.org/) and paste your token under *Conky settings*; passage rotates by calendar day from a built-in list of references. Follow Crossway API / copyright terms.
  - **Weather** — [Open-Meteo](https://open-meteo.com/) (no API key). Set a **city** or **lat, lon** in Conky settings.
- Rendered configs: `~/.local/share/plasmacolorizer/conky/rendered/<preset>.conf`. PIDs: `~/.cache/plasmacolorizer/conky/`. App settings (ESV key, weather location): `~/.config/plasmacolorizer/settings.json` (mode `600` when possible).
- Default positions: system **top-left**, shortcuts **top-right**, verse **bottom-left**, weather **bottom-right** (each preset has a **3×3 grid** position in Conky settings).
- Panels are **opaque** `desktop`-layer windows so other windows **always pass over them**; **panel transparency** blends the palette **surface** colour toward a neutral backdrop in RGB (not ARGB translucency), which also avoids KDE blur **ghosting** when other windows cross the Conky region.
- Fetch helpers for Conky `execi` (also useful from a terminal):

  ```bash
  python -m plasmacolorizer.conky.fetch esv
  python -m plasmacolorizer.conky.fetch weather
  ```

  Use the same Python environment you installed PlasmaColorizer into so imports resolve.

- After **Preview palette** or **Generate / Apply** on the Colorizer tab, any **running** bundled Conkys are re-rendered and restarted so colors stay in sync with the wallpaper.

## Tests

```bash
pytest
```

## GitHub

```bash
gh repo create PlasmaColorizer --public --source=. --remote=origin --push
```

(Use `--private` for a private repository.)

If the project directory ever has wrong ownership from automation:

```bash
sudo chown -R "$(whoami)":"$(whoami)" ~/Projects/PlasmaColorizer
```
