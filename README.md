# PlasmaColorizer

PyQt6 utility for **KDE Plasma** (Manjaro-friendly) that:

- Reads the active wallpaper via **`org.kde.PlasmaShell`** (DBus).
- Extracts a seed color with **materialyoucolor** and builds a Material You–style palette.
- Writes `~/.local/share/color-schemes/PlasmaColorizer.colors` and applies it with **`plasma-apply-colorscheme`**.
- Optional **green accent bias** (shifts the seed hue toward green before scheme generation).
- Offers a **Conky** tab to render config templates with `{{token}}` placeholders filled from the last generated palette.

## Requirements

- Python 3.10+
- Plasma session with `org.kde.PlasmaShell` and `plasma-apply-colorscheme` available.
- `python-dbus` / **dbus-python** (see `pyproject.toml`).

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

## Usage notes

- **Wallpaper detection** works best with the standard **Image** wallpaper plugin (`org.kde.image`). Other plugins may not expose a file path; use the “Override” field to point at an image.
- **Dark / light** for generated Material schemes: choose *Follow KDE* (reads `ColorScheme` in `~/.config/kdeglobals`), or force dark/light.
- **Conky tab** fills tokens such as `{{primary}}`, `{{on_surface}}`, `{{surface}}`, etc., after you successfully generate a palette on the Colorizer tab.

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
