# PlasmaColorizer

PyQt6 utility for **KDE Plasma** (Manjaro-friendly) that:

- Reads the active wallpaper via **`org.kde.PlasmaShell`** (DBus).
- Extracts a seed color with **materialyoucolor** and builds a Material You–style palette.
- Writes `~/.local/share/color-schemes/PlasmaColorizer.colors`, merges into `~/.config/kdeglobals`, installs a **Plasma desktop theme** (`PlasmaColorizer`), and reloads it via `plasma-apply-desktoptheme` plus DBus accent sync.
- **KDE panel opacity** mode on the Colorizer tab (Solid / Adaptive / Translucent — Plasma 6’s real API in `~/.config/plasmashellrc`; Solid by default so scheme colours show on the taskbar).
- Optional **component colour overrides** — pin panel, launcher, selection, etc. to palette swatches or a custom colour / screen dropper without replacing automated mapping.
- Optional **strong panel tint** and **primary color bias** for more visible wallpaper-driven accents.
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
- **Cohesive KDE theming** (Colorizer tab): when **Apply palette to Konsole** is enabled (default), PlasmaColorizer writes `~/.local/share/konsole/PlasmaColorizer.colorscheme`, points your **default** Konsole profile (`DefaultProfile` in `~/.config/konsolerc`) at it, and reloads open Konsole windows. **Point Dolphin at system color scheme** (default on) clears stale per-app pins in `~/.config/dolphinrc` (e.g. `MaterialYouDark` left by kde-material-you-colors) so Dolphin follows the global `PlasmaColorizer` scheme. **Dolphin and Breeze title bars** are updated via `plasma-apply-colorscheme` (with a reload stub so KDE picks up changes even when the scheme name stays `PlasmaColorizer`). After the first apply, **close and reopen Dolphin** if an already-open window still shows old colours.
- **Wallpaper auto-apply**: enable **Run wallpaper watcher at login** (default on) to install `plasmacolorizer-daemon` — it polls the main-screen wallpaper every few seconds and re-applies the palette when it changes, even when the UI is closed. While the app is open, the in-app poll is used only when the background watcher is disabled. Manual **Override** paths are ignored by the watcher. Auto-apply runs are logged with `[auto]` / `[daemon]` prefixes.
- **Dark / light** for generated Material schemes: choose *Follow KDE* (reads `ColorScheme` in `~/.config/kdeglobals`), or force dark/light.
- **Conky tab** fills tokens such as `{{primary}}`, `{{on_surface}}`, `{{surface}}`, etc., from the **effective** palette (Colorizer tab, including swatch overrides).
- **Bundled presets** (Start / Stop per preset, **Stop all**, **Apply colors to running Conkys**):
  - **System** — CPU, load, RAM, root disk free/used, network up/down (`wlo1` / `wlan0` / `eth0` when up).
  - **Shortcuts** — short static KDE-oriented cheat sheet (edit the template in the repo if you want different bindings).
  - **Verse** — text from the **ESV API** (Crossway). Register at [api.esv.org](https://api.esv.org/) and paste your token under *Conky settings*; passage rotates by calendar day from a built-in list of references. Follow Crossway API / copyright terms.
  - **Weather** — [Open-Meteo](https://open-meteo.com/) (no API key). Set a **city** or **lat, lon** in Conky settings.
- Rendered configs: `~/.local/share/plasmacolorizer/conky/rendered/<preset>.conf`. PIDs: `~/.cache/plasmacolorizer/conky/`. App settings (ESV key, weather location): `~/.config/plasmacolorizer/settings.json` (mode `600` when possible).
- Default positions: system **top-left**, shortcuts **top-right**, verse **bottom-left**, weather **bottom-right** (each preset has a **3×3 grid** position in Conky settings).
- Panels use **real compositor transparency** driven by the **panel transparency** slider (slider lowest = solid surface, highest = fully see-through with only the text/icons rendered). Because Conky's own `own_window_argb_value` is silently ignored by KWin on XWayland on most setups, PlasmaColorizer also sets the **`_NET_WM_WINDOW_OPACITY`** X11 atom on every spawned Conky window (via `xprop`) — that's the universal compositor opacity hint and KWin always honors it. Dragging the slider updates this property **live** on all running panels (no restart needed). To stay **below every real application window without ghosting**, the panels run as `own_window_type = 'normal'` with the `below` state plus `skip_taskbar` / `skip_pager` / `sticky` / `undecorated` hints — KWin treats them as ordinary managed windows so damage / expose events repaint them cleanly when overlapping windows move, while the `below` state guarantees no real window is ever covered. Panels also set `own_window_class = 'PlasmaColorizerConky'` so you can target them with a custom KWin window rule if your setup ever needs one.
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

**Wallpaper watcher daemon** (optional CLI):

```bash
plasmacolorizer-daemon --foreground   # run in a terminal
plasmacolorizer-daemon --stop           # stop background watcher
plasmacolorizer-daemon --install-autostart
```

## Troubleshooting

### KDE panel opacity (Solid / Adaptive / Translucent)

Plasma 6 stores panel opacity as an integer mode in `~/.config/plasmashellrc` (`0` = Adaptive, `1` = Solid, `2` = Translucent). This is **not** a continuous alpha slider like Conky.

**All three modes look identical:** The PlasmaColorizer Plasma Style ships a `plasmarc` under `~/.local/share/plasma/desktoptheme/PlasmaColorizer/`. If that file contains `[AdaptiveTransparency]` or `[ContrastEffect]` — even with `enabled=false` — Plasma ignores the per-panel opacity mode and renders every choice the same. The theme `plasmarc` must contain only:

```ini
[Settings]
FallbackTheme=default
```

On the Colorizer tab, use **Diagnose panel opacity** and **Repair theme for panel opacity** (or re-apply a scheme, which regenerates a minimal `plasmarc`). Then switch Solid ↔ Translucent; plasmashell restarts briefly so the panel picks up the change.

**Translucent looks subtle:** Enable KWin blur (System Settings → Apps & Windows → Window Management → Desktop Effects) and use a wallpaper with contrast behind the panel. Third-party panel styling tools (`kde-material-you-colors`, luisbocanegra panel widgets) can paint their own background and hide native opacity — remove or pause them first.

**Manual check:** After repair, `plasmashellrc` should show `panelOpacity=1` (Solid) or `panelOpacity=2` (Translucent). Switching to stock `breeze-dark` Plasma Style and comparing Solid vs Translucent isolates whether the issue is theme-side.

## GitHub

```bash
gh repo create PlasmaColorizer --public --source=. --remote=origin --push
```

(Use `--private` for a private repository.)

If the project directory ever has wrong ownership from automation:

```bash
sudo chown -R "$(whoami)":"$(whoami)" ~/Projects/PlasmaColorizer
```
