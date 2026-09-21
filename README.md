# redberry-webkit

Shared, project-agnostic modules for FastAPI + NiceGUI applications: same
code, same behavior, imported once instead of rewritten project by project.

## Modules

| Module | What it does |
|---|---|
| `env_resolver` | `resolve_env_path()` — precedence `ENV_FILE` (Docker) > `--env-file` (CLI) > nearest `.env` |
| `auth` | `AuthManager` (JWT cookie session, scrypt password hashing, per-IP/global rate limiting) + `verify_api_token`, `is_secure_context`, `client_ip` |
| `config` | `ConfigManager` — `.env`-backed, hot-reload via mtime polling, writable from a UI (`update_many`) |
| `logging_utils` | `redact()` + `CredentialFilter` — scrubs passwords/tokens/secrets from logs |
| `timezone_utils` | `resolve_timezone(tz_name)` — safe `ZoneInfo`, falls back to UTC with a warning |
| `credentials` | `watch_loop()` / `CredentialsStatus` — generic expiry monitor for an external CLI's OAuth credentials JSON |
| `metrics` | `MetricsStore` — async request history on SQLite (record/get_stats/get_history/purge_old), free-form `extra` field for project-specific data |

Every module takes project-specific values (paths, cookie names, TTLs, JSON
fields) as parameters — the package provides the mechanism, never the
values.

## Installing in a consumer app

`requirements.txt`:

```
redberry-webkit @ git+https://github.com/daniloreddy/redberry-webkit.git@v0.2.3
```

```bash
pip install -r requirements.txt
```

Import name (underscore, not hyphen):

```python
from redberry_webkit.auth import AuthManager
from redberry_webkit.env_resolver import resolve_env_path
from redberry_webkit.config import ConfigManager
```

## Usage notes

- `AuthManager.verify_password()`/`set_password()` are synchronous and
  CPU/memory-bound (scrypt → ~150-250ms, ~128MB per call): in an async
  FastAPI handler, run them via `asyncio.to_thread(...)`, never inline.
- `ConfigManager.update_many()` validates keys and writes to `.env` safely
  against injection — see the method's docstring for exactly what's
  accepted/rejected.

## Versioning

Every fix/feature → a new semver tag (`vX.Y.Z`). Consumer apps update the
pin in their own `requirements.txt` explicitly — no automatic propagation.

## Development

```bash
scripts\checks.bat   # Windows
scripts/checks.sh    # Linux/Mac
```

Creates/activates the venv, installs `requirements.dev.txt`, runs `ruff check .`, `mypy redberry_webkit`, `pytest`.

## License

MIT — see [LICENSE](LICENSE).
