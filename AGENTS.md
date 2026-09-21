# redberry-webkit — agent instructions

Shared, project-agnostic pip package. Every module takes paths/names/TTLs/fields
as parameters: the package provides the mechanism, never the project-specific
values.

## Why it exists

Born to avoid drift between projects that each reimplement the same logic
(auth, config, log redaction, etc.) their own way — duplicated scrypt
parameters with different values, different file locations. Goal: same code
= same behavior, imported once instead of regenerated project by project.
Before reimplementing one of these functions in a consumer project, check
whether this package already covers it.

## Per-module operational notes

- **`auth.py`** — `verify_password()`/`set_password()` are synchronous,
  CPU/memory-bound (scrypt N=131072 → ~150-250ms, ~128MB per call): in an
  async FastAPI handler they must **always** be invoked via
  `asyncio.to_thread(...)`, never inline (would block the event loop) — and
  the caller should wrap that call in a semaphore + timeout, so a burst of
  unauthenticated requests can't push N unbounded parallel scrypt calls
  (~128MB each) onto the event loop. KDF params (N/r/p) are persisted
  per-hash in `auth.json`: a hash with no stored params (pre-0.2.0
  installs) is verified against the old defaults (`_LEGACY_SCRYPT_N =
  16384`), not against the current constant — no automatic re-hash on
  login, only on the next `set_password()`. `set_password()` also rotates
  the JWT secret (`auth.json["secret"]`), invalidating every existing
  session. `_save()` chmods the temp file **before** `os.replace()` (not
  after), so there's no window where the file sits at umask-default
  permissions, readable by others. `client_ip()` only trusts
  `X-Forwarded-For`/`CF-Connecting-IP` if the request arrives from an IP in
  `trusted_proxies`, and takes the **leftmost** entry as the client IP —
  this requires the proxy to *overwrite* the header, not append to it
  (nginx appends by default: a client can inject a fake
  `X-Forwarded-For` that stays leftmost and bypasses the per-IP rate
  limit). `verify_api_token()` wraps the comparison in `try/except
  TypeError` — `hmac.compare_digest` raises `TypeError` on a non-ASCII
  Bearer token, otherwise propagated as an unhandled 500.
  `purge_expired_blocks()` also cleans up stale sub-threshold
  `_failed_attempts` entries, not just blocked IPs — otherwise unbounded
  growth for IPs that make a few attempts under the block threshold
  without ever crossing it.

- **`config.py`** — `update_many()`: a key that doesn't match `_KEY_RE` →
  rejected; an empty/whitespace value → silently skipped (a UI save with a
  blank field must never wipe an existing key — clearing one means editing
  `.env` by hand); a value ending in a single backslash → rejected
  (confirmed: `set_key(..., quote_mode="always")` still writes the line,
  but python-dotenv's own *reader* can't parse it back and
  `dotenv_values()` silently returns an empty dict for **the whole file**,
  not just that key). Embedded newline/carriage-return values **are
  allowed** as of v0.2.1 — `quote_mode="always"` alone closes the injection
  path (see CHANGELOG v0.2.1); rejecting them on top of that broke a
  legitimate use case (a multi-line textarea from a web UI) for no extra
  security gain. Don't reintroduce that rejection without re-reading that
  changelog entry.

- **`logging_utils.py`** — `_kv_pattern(key)` also matches snake_case
  suffixes and plurals (`(?:\b|_){key}s?`), not just an exact word
  boundary. `CredentialFilter` also scrubs `record.exc_text` (formatting it
  from `record.exc_info` if not yet populated) — a traceback with a secret
  interpolated into an exception message still gets redacted.

- **`timezone_utils.py`** — `resolve_timezone()` catches both
  `ZoneInfoNotFoundError` and `ValueError`: an empty string or a path-like
  value passed to `ZoneInfo(...)` raises `ValueError`, not
  `ZoneInfoNotFoundError` — a single `except` isn't enough, both are needed
  so a malformed `TZ` doesn't crash the app.

- **`credentials.py`** — `_DEFAULT_EXPIRY_KEY_PATH` points at the
  `expiresAt` field (renamed by the Claude Code CLI from
  `refreshTokenExpiresAt`, fixed in v0.2.3). `watch_loop()` degrades softly
  on a read error (`readable=False`, never a crash) — a consumer with a
  differently-shaped credentials file passes its own `expiry_key_path`.

- **`metrics.py`** — `MetricsStore` has no access control of its own (I3,
  reviewed and accepted by-design in the v0.2.0 audit): whoever mounts the
  endpoint exposing the history decides the auth, not the module.

- **`request_view.py`** — pure view-model over `MetricsRecord`, no
  FastAPI/NiceGUI import (project still calls `ui.table(...)`/`add_slot(...)`
  itself). `ip`/`user_agent` live in `MetricsRecord.extra["client_ip"]`/
  `extra["user_agent"]`, not native columns — deliberate, avoids a
  migration on `data/metrics.db` files already deployed across projects.
  `request_meta()` delegates IP resolution to `auth.client_ip()`; don't
  reimplement trusted-proxy/forwarded-header handling at a project's
  `metrics.record()` call site.

- **`ui.py`** — imports NiceGUI directly. Extracted after confirming
  `_page_setup`/`_header`/`_footer`/`_logout_action` were duplicated
  near-verbatim across mid_service_py, mailmanager, ragbot, PRO-form,
  parallax-py, dca_signal — same shape the Go sibling already solved once
  via `app.RenderPage`/`Options`/`NavItem`. `page()` is the single
  entry point that replaces a project's whole `base_layout()`
  contextmanager; `page_setup()`/`header()`/`footer()`/`metric_card()`/
  `logout_action()` stay exported individually for a project that needs
  finer control. `NavItem` is a `NamedTuple` (not a dataclass) so an
  existing project's bare-tuple `NAV_ITEMS` list keeps working without a
  forced migration to `NavItem(...)` call sites.

  **Consequence**: the package now pulls in NiceGUI's
  full dependency tree (FastAPI, Starlette, Uvicorn, Socket.IO, ...) for
  every consumer, even one that only imports `auth.py`. Accepted
  trade-off (2026-09-21) — every current consumer already depends on
  NiceGUI directly anyway. Re-splitting into a separate package (e.g.
  `redberry-nicegui-kit`) remains an option if a framework-free consumer
  ever appears; not done preemptively.

  **Testing `ui.py` — no Selenium/browser.** `nicegui.testing.User`
  (in-process DOM simulation) is what the tests use, not
  `nicegui.testing.Screen` (real-browser, needs `selenium`). The default
  `pytest_plugins = ["nicegui.testing.plugin"]` pulls in `screen_plugin`
  unconditionally (imports `selenium` at module level) even if a test
  only touches `User` — so `tests/conftest.py` registers
  `nicegui.testing.general_fixtures` + `nicegui.testing.user_plugin`
  directly instead, skipping `screen_plugin` entirely. This needs a
  `main_file` ini option (`tests/_nicegui_app.py`, a trivial `ui.run()`
  stub — the `User` fixture's test harness requires *some* app entry
  point to exist, even though it's never actually run as a server).
  Confirmed working, sub-second, no browser/webdriver, on Windows +
  Python 3.11 + NiceGUI 3.17. Don't switch to the full `nicegui.testing.plugin`
  without confirming Selenium/a browser driver is actually available in
  every environment `checks.bat`/CI runs in — it isn't today.

## Known risks, accepted by design

From the v0.2.0 audit (see CHANGELOG): **L5** — rate-limit state
(`_failed_attempts`/`_blocked_until`) is in-process, reset on every
restart — acceptable only if the consumer runs a single worker/process
(state not shared across replicas). **I3** — see `metrics.py` above. Don't
"fix" these without discussing first: they're design choices, not
forgotten tech debt.

## Versioning — workflow

Every fix/feature → bump `pyproject.toml` `version` → commit → semver Git
tag (`vX.Y.Z`) on that same commit → update `CHANGELOG.md`. Consumer apps
do **not** get the update automatically: bump the pin manually in
`requirements.txt` (`redberry-webkit @ git+...@vX.Y.Z`) for each one. A fix
here isn't "live" for any consumer until that bump has happened — don't
assume a recent fix is already in production somewhere without checking
that consumer project's pin.

## Testing & conventions

`pyproject.toml`: ruff `select = ["E", "F", "I", "UP", "B"]`, mypy
`strict = true`, pytest `asyncio_mode = "auto"` (no scattered
`@pytest.mark.asyncio`). `scripts/checks.bat`/`checks.sh` do venv-detect +
ruff + mypy + pytest in sequence — use them before every commit, not the
individual commands by hand, so no step gets forgotten.

Every public module: a corresponding `test_<module>.py` in `tests/`. A
behavior fix (not just a feature) needs a test that fails *before* the fix
and passes *after* — see the style of the tests in `test_config.py` for
`update_many()` (one per rejection/acceptance case).
