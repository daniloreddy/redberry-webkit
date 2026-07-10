# Changelog

## v0.1.3

- Add one-line docstrings to all public API (classes/functions exported by each module) — this is a published pip package consumed by multiple projects, so docstrings are the API contract surface (`help()`, IDE hover), distinct from the app-level "no comments" convention.
- Uniform `from __future__ import annotations` across all 7 modules (was present in 4/7).

## v0.1.2

- Add `py.typed` marker (PEP 561) — without it, mypy in consumer projects silently treated every `redberry_webkit` export as `Any`, hiding real type errors (found while migrating `cli_agent_bridge`).

## v0.1.1

- Fix `requires-python` (was `>=3.12`, broke install on the actual runtime — every project on this machine, including `cli_agent_bridge`, runs Python 3.11.4). Now `>=3.11`, ruff/mypy target aligned.

## v0.1.0

- Initial extraction from `cli_agent_bridge`: `env_resolver`, `auth` (AuthManager, JWT cookie sessions, scrypt password hashing, per-IP/global rate limiting), `config` (ConfigManager, hot-reloadable `.env`-backed settings), `logging_utils` (secret redaction), `timezone_utils` (safe `ZoneInfo` resolution), `credentials` (generic CLI-tool OAuth expiry watcher).
