# PlasmaColorizer

PyQt6 helper for Manjaro KDE that reads the current Plasma wallpaper via DBus, derives colors with **materialyoucolor**, generates a Plasma color scheme (optional green-accent bias), and includes a tab for **Conky** configs with simple color templating.

Details and full implementation will land in subsequent commits.

## Requirements (planned)

- Python 3.10+
- Plasma 5/6 desktop session (`org.kde.PlasmaShell` on DBus, `plasma-apply-colorscheme` on `$PATH`)

## Local setup

```bash
cd ~/Projects/PlasmaColorizer
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

(Run step will be wired once `app.py` exists.)

## Connect this folder to GitHub and push

1. **Install GitHub CLI** (Arch/Manjaro): `sudo pacman -S github-cli`
2. **Log in**: `gh auth login` → GitHub.com → HTTPS → authenticate in the browser
3. **Wire git to gh**: `gh auth setup-git`
4. **Create the remote repo from this clone and push**:

```bash
cd ~/Projects/PlasmaColorizer
gh repo create PlasmaColorizer --public --source=. --remote=origin --push
```

Use `--private` instead of `--public` if you want a private repository.

Already created an empty repo on GitHub manually? Skip `gh repo create` and:

```bash
git remote add origin https://github.com/<your-username>/PlasmaColorizer.git
git push -u origin main
```

## Permissions note

If this directory was created by another tool and shows `root:root` ownership, fix it before pushing:

```bash
sudo chown -R "$(whoami)":"$(whoami)" ~/Projects/PlasmaColorizer
```
