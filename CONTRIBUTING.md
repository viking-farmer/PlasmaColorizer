# Contributing to PlasmaColorizer

Thanks for your interest. This is a small project with a few simple rules.

## Commit messages

We use [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/).
A commit message has a short summary line and an optional body that explains
the *why* of the change, plus any caveats:

```
<type>(<optional scope>): <short, imperative summary>

<body: what changed, why it changed, side-effects, follow-ups>

<optional footer: BREAKING CHANGE: ..., Refs #123>
```

Allowed `<type>` values:

- `feat` — a new user-visible feature
- `fix` — a bug fix
- `docs` — documentation only
- `refactor` — code change that neither fixes a bug nor adds a feature
- `perf` — a performance improvement
- `test` — adding or fixing tests
- `build` — packaging / build-system changes
- `ci` — CI configuration
- `chore` — anything else (deps bump, housekeeping)

Example:

```
fix(plasma_scheme): apply colors by writing kdeglobals directly

plasma-apply-colorscheme is unreliable on some KDE setups: the DBus
call to plasmashell never returns and the subprocess hangs forever.
We now replicate its work in-process: write ~/.config/kdeglobals and
emit org.kde.KGlobalSettings.notifyChange with a hard 2s timeout.

Closes #4.
```

## Code style

- Python 3.10+, type hints, `from __future__ import annotations`.
- Keep public functions documented with a short docstring.
- No new runtime dependencies without a discussion.
- Avoid touching DBus from background threads — call it on the GUI thread.

## Before opening a PR

1. `pytest` is green.
2. `pip install -e ".[dev]"` succeeds in a fresh venv.
3. CHANGELOG.md has an entry under `## [Unreleased]`.

## Pushing

Do not push to `main` directly without review unless you're the
maintainer and the change is trivial (typos, docs).
