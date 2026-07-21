# Changelog

## v0.2.1

- **config.py**: `update_many()` no longer rejects values with embedded newlines/carriage
  returns. The v0.2.0 fix closed an env-injection path (a value containing `\n` planting an
  unrelated `KEY=value` line) by rejecting such values outright — but that also broke a
  legitimate use case surfaced by a consumer project (PRO-form): a multi-line value written
  from a web-UI textarea (e.g. a customizable message template). `quote_mode="always"`
  (already in place since v0.2.0) turns out to be sufficient on its own: python-dotenv's
  `set_key()` quotes the value and backslash-escapes any embedded quote character, which
  closes the injection path regardless of content — a value's embedded newlines stay inside
  the quoted block and round-trip correctly through `dotenv_values()`. Verified empirically
  (see `tests/test_config.py::test_update_many_embedded_newline_cannot_inject_a_new_key`)
  before relaxing the check, not just by reasoning about it. `docker compose`'s own `.env`
  parser (compose-go, a joho/godotenv-compatible implementation) also supports multi-line
  quoted values — a **manually hand-edited** `.env` with an *unquoted* multi-line value still
  breaks `docker compose up` (the two parsers don't share this codepath), but anything written
  through `ConfigManager.update_many()` is always quoted, so this class of consumer never hits
  that failure mode via the UI.

## v0.2.0

Fixes from a security/quality audit (REPORT.md, 23 findings). ~17 fixed below; L5 (in-memory
rate-limit state resets on restart) and I3 (MetricsStore has no built-in access control) were
reviewed and accepted as by-design, not fixed. Four findings were checked against source and
found to be false positives (see bottom) — this list isn't exhaustive line-accounting, just
what changed:

- **auth.py**: scrypt cost raised to OWASP-2023 minimum (N=16384→131072); KDF params now persisted per-hash so old passwords keep verifying under the old N instead of breaking (`maxmem` raised accordingly — OpenSSL's default 32MB is too low for N=131072,r=8). `auth.json` writes are now atomic (temp file + `os.replace`) and chmod'd to owner-only where supported. Fixed a TOCTOU (`exists()`+`read_text()` race) in `_load_or_init`. `verify_api_token` no longer short-circuits on first match (timing side-channel). JWT now sets an explicit `typ` header.
- **config.py**: `update_many()` now rejects invalid keys and values with embedded newlines, and writes via `quote_mode="always"` instead of `"never"` — closes an env-injection path where a value containing `\n` could plant arbitrary new `KEY=value` lines. `get_public()` now masks secret keys unconditionally (an empty secret value used to leak "not configured" in cleartext).
- **logging_utils.py**: redaction regex now matches quoted values (`{"password": "..."}`), not just bare ones — JSON-formatted log lines previously bypassed redaction entirely.
- **credentials.py**: fixed the same TOCTOU pattern as auth.py; `resolve_credentials_path()` normalizes `config_dir` (documented as trusted-input-only, not sandboxed); malformed-file log messages now log the exception type only, not its message, which could echo file content.
- **metrics.py**: `get_stats()`/`get_history()` now share the same lock as `record()`/`purge_old()` (previously reads weren't locked, risking inconsistent reads under concurrent purge); `get_history(redact_sensitive=True)` applies `logging_utils.redact()` to `error_message`/`extra` for callers exposing history to a wider audience than the recorder; `purge_old()` now runs `PRAGMA optimize` so the DB file doesn't grow unbounded across purge cycles.
- **env_resolver.py**: `resolve_env_path()` no longer crashes on a malformed `--env-file` CLI flag (argparse raising `SystemExit` is now caught and treated as "flag not given").

Four report findings were checked against source and found to be false positives (not fixed):
"getMessage() exposes secret before redaction" (the filter contract is correct when attached
to every handler, as this repo's consumers already do), "ReDoS-prone redaction pattern" (a
single negated character class is linear, not exponential), "cache updated before verifying
write succeeded" (the code already updates cache *after* `set_key()`, not before), and
"test_env_resolver.py mutates sys.argv globally" (it uses `monkeypatch.setattr`, which
auto-reverts per test — not a global mutation).

**Known tradeoffs from this release, not yet addressed:**
- The scrypt N bump (16384→131072) makes `verify_password`/`set_password` ~8x slower
  (~150-250ms) and each call transiently allocates ~128MB. Both are synchronous CPU-bound
  calls — a consumer calling them from an async request handler should run them via
  `asyncio.to_thread` (done in `redberry-webapp-template`'s `router.py.jinja`) or accept the
  blocking cost. Concurrent logins each cost ~128MB RAM; on a memory-constrained container
  this is a real capacity/OOM consideration, not just latency.
- Existing passwords hashed under the old N=16384 are verified against the params stored
  at hash time (see `set_password`) and are **not** automatically re-hashed at the new cost
  on next successful login — they stay at N=16384 until the password is reset.

## v0.1.3

- Add one-line docstrings to all public API (classes/functions exported by each module) — this is a published pip package consumed by multiple projects, so docstrings are the API contract surface (`help()`, IDE hover), distinct from the app-level "no comments" convention.
- Uniform `from __future__ import annotations` across all 7 modules (was present in 4/7).

## v0.1.2

- Add `py.typed` marker (PEP 561) — without it, mypy in consumer projects silently treated every `redberry_webkit` export as `Any`, hiding real type errors (found while migrating `cli_agent_bridge`).

## v0.1.1

- Fix `requires-python` (was `>=3.12`, broke install on the actual runtime — every project on this machine, including `cli_agent_bridge`, runs Python 3.11.4). Now `>=3.11`, ruff/mypy target aligned.

## v0.1.0

- Initial extraction from `cli_agent_bridge`: `env_resolver`, `auth` (AuthManager, JWT cookie sessions, scrypt password hashing, per-IP/global rate limiting), `config` (ConfigManager, hot-reloadable `.env`-backed settings), `logging_utils` (secret redaction), `timezone_utils` (safe `ZoneInfo` resolution), `credentials` (generic CLI-tool OAuth expiry watcher).
