# redberry-webkit — state and decisions

Last updated: 2026-11-07. Read this before asking "what did we decide".

## Direction (user decisions)

- **Everything becomes Python.** The Go and Java projects will be converted; `redberry-webkit-go`, `-j` and their
  templates are no longer kept aligned (frozen). `redberry-webkit-ui` was merged into this package and retired:
  `web/static/{app.css,app.js}`, `tests/ui/` (fixtures + golden HTML) are edited here.
- UI per project (no single shared UI). Text shown in the UI is **Italian**; code (comments, variables, classes,
  methods) is **English**; project docs are Italian. API error payloads stay English.
- Config format is `.env` (`ConfigManager`).
- `redberry_webkit.bootstrap` (v0.7.0, extra `[app]`) holds the FastAPI wiring every project used to copy:
  login, `/ui` gate, `/health`, `/ui/config`, logging, rate limit, lifespan loops, CLI. Projects only supply an
  `AppSpec` and their own routes (see `redberry-webapp-template`).
- Template docs files (`AGENTS.md`, `CLAUDE.md`, `README.md`, ...) are created once (`_skip_if_exists`): `copier update`
  never touches them.

## TODO

- **Remove NiceGUI**: `redberry_webkit/ui.py`, the `nicegui` dependency, `tests/test_ui.py`, `tests/_nicegui_app.py`,
  the NiceGUI plugins in `tests/conftest.py`, notes in AGENTS.md/CHANGELOG. Only `ragbot` still imports it: migrate it
  first (or keep it on v0.6.0). Release as v0.8.0.
- Convert the Go/Java projects to Python; before that, check that existing `auth.json` / `metrics.db` files load in
  the Python webkit.
- Existing Python projects (dca_signal, mid_service_py, parallax-py, PRO-form, ragbot) still carry a hand-copied
  bootstrap and pin v0.6.0.

## Enforcement

- `redberry-webapp-template/tools/check_template.py` (scaffold + invariants + scaffold ruff/pytest + webkit pin +
  `--trust`), run by the hooks installed with `python tools/install_hooks.py` (not versioned: rerun after a clone).
- This repo: `scripts/checks.bat|sh` (ruff, mypy, pytest); pre-push hook runs the same.

## Traps already hit

- copier mishandles staged changes on paths with spaces: the check scaffolds from a plain copy of the working tree.
- Starlette `TestClient` wants `httpx2`; non-ASCII header bytes go in as a list of tuples.
- On Windows always write files with `encoding="utf-8"`; `sed -i` can strip CRLF from `.bat`.
- Git hooks export `GIT_*` env vars; strip them before spawning git/copier.
