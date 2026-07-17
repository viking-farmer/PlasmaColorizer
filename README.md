# PlasmaColorizer

PyQt6 utility for **KDE Plasma** (Manjaro-friendly) that:

- Reads the active wallpaper via **`org.kde.PlasmaShell`** (DBus).
- Extracts a seed color with **materialyoucolor** and builds a Material You–style palette.
- Writes `~/.local/share/color-schemes/PlasmaColorizer.colors`, merges into `~/.config/kdeglobals`, installs a **Plasma desktop theme** (`PlasmaColorizer`), and reloads it via `plasma-apply-desktoptheme` plus DBus accent sync.
- **KDE panel opacity** mode on the Colorizer tab (Solid / Adaptive / Translucent — Plasma 6’s real API in `~/.config/plasmashellrc`; Solid by default so scheme colours show on the taskbar).
- Optional **component colour overrides** — pin panel, launcher, selection, etc. to palette swatches or a custom colour / screen dropper without replacing automated mapping.
- Optional **strong panel tint** and **primary color bias** for more visible wallpaper-driven accents.
- Offers a **Terminal** tab to theme your terminal from the palette: pick **Konsole** (KDE default) or another installed terminal (**kitty**, **Alacritty**, **xterm**), tweak the font family/size, background opacity, and optionally pin custom background / text / accent (cursor) colours, with a live preview.
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
- **Cohesive KDE theming** (Colorizer tab): when **Apply palette to Konsole** is enabled (default), PlasmaColorizer writes `~/.local/share/konsole/PlasmaColorizer.colorscheme` (plus a mirror `PlasmaColorizerAlt` for live reload), maps Material `onBackground` / `onSurface` to default terminal text, uses a proper 16-colour ANSI palette for `ls` and shell output, enables **BoldIntenseColors** on the default profile, and reloads open Konsole windows. **Point Dolphin at system color scheme** (default on) clears stale `MaterialYou*` pins in `~/.config/dolphinrc`. **Dolphin and Breeze title bars** refresh via `plasma-apply-colorscheme`. Re-open Konsole/Dolphin if an already-open window still shows old colours.
- **Terminal tab**: theme any terminal from the current palette, easily and without editing config files by hand.
  - **Terminal picker** — **Konsole** is the default; **kitty**, **Alacritty**, and **xterm** are selectable when their executable is on `PATH` (others are greyed out as *(not installed)*).
  - **Font & transparency** — optionally set a custom monospace **font family** and **size**, toggle **BoldIntenseColors** (bright colours for bold text), and set the **background opacity** (needs a compositor).
  - **Color overrides** — every colour is derived from the wallpaper by default; flip on **Custom background / text / accent (cursor)** to pin a specific colour via the picker. A **live preview** shows the resulting prompt, ANSI swatches, and sample text.
  - **Apply to terminal** writes the scheme now and reloads where possible; **Save settings** persists to `~/.config/plasmacolorizer/terminal.json`. The same selection is reused by **Apply palette to Konsole** on the Colorizer tab and by the wallpaper daemon, so auto-apply themes whichever terminal you chose.
  - Non-Konsole backends write an include-able file (kitty `~/.config/kitty/plasmacolorizer.conf`, Alacritty `~/.config/alacritty/plasmacolorizer.toml`, xterm `~/.config/plasmacolorizer/xterm.Xresources`) and wire it into the terminal's main config. Alacritty live-reloads; kitty is signalled to reload; xterm changes are merged with `xrdb` and apply to newly-opened windows.
- **Wallpaper auto-apply**: enable **Run wallpaper watcher at login** to install `plasmacolorizer-daemon`. The daemon **never restarts plasmashell** — it only writes the scheme and soft-refreshes via `plasma-apply-colorscheme` / DBus (full shell restart via `kquitapp` previously left Plasma dead when systemd’s `plasma-plasmashell.service --no-respawn` did not recover). Soft-apply is the default for the Colorizer tab as well; optional “Restart Plasma shell afterward” uses `systemctl --user restart plasma-plasmashell.service` when possible. If the desktop dies: `plasmacolorizer-recover` or **Recover Plasma desktop** on the Conky tab.
- **Dark / light** for generated Material schemes: choose *Follow KDE* (reads `ColorScheme` in `~/.config/kdeglobals`), or force dark/light.
- **Conky tab** fills tokens such as `{{primary}}`, `{{on_surface}}`, `{{surface}}`, etc., from the **effective** palette (Colorizer tab, including swatch overrides).
- **Bundled presets** (Start / Stop per preset, **Stop all**, **Apply colors to running Conkys**):
  - Window mode defaults to **Normal + below** so panels stay visible on Plasma Wayland. **Desktop layer** often looks like Conky “died” because plasmashell draws the wallpaper over those windows while the process is still running.
  - Bundled configs force `out_to_x = true` / `out_to_wayland = false` for reliable XWayland windows under KDE.
  - If Plasma stops responding after starting Conky panels: use **Recover Plasma desktop** on the Conky tab, or run `plasmacolorizer-recover` from a terminal (TTY/Ctrl+Alt+F3 also works). That stops Conky, disables Conky login autostart, stops the wallpaper daemon, and restarts `plasmashell` without touching colour schemes. Re-enable Conky autostart later with `plasmacolorizer-recover --reenable-autostart` or the Conky tab checkbox.
  - **System** — CPU, load, RAM, root disk free/used, network up/down (`wlo1` / `wlan0` / `eth0` when up).
  - **Shortcuts** — a KDE-oriented cheat sheet you can edit directly in the app. Use the **Shortcuts widget** editor on the Conky tab to add, remove, reorder, or rename rows (each row is an *Action* label plus a *Shortcut* key combo); **Reset to defaults** restores the bundled list. Entries persist in `~/.config/plasmacolorizer/settings.json` (`conky_shortcuts`); after **Save shortcuts**, restart the Shortcuts preset (or **Apply colors to running Conkys**) to refresh the panel.
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
