"""One-call bootstrap for a FastAPI + Jinja2/HTMX dashboard app: the wiring every project used to copy.

Requires the optional extra: ``pip install "redberry-webkit[app]"``.

A project describes itself with an `AppSpec` and calls `create_app`; it gets back a `WebApp` holding the
FastAPI app plus the shared objects (config, auth, metrics, layout, limiter). What `create_app` wires:
.env loading, logging with credential redaction, runtime config (hot reload), dashboard auth (login/logout
routes, `/ui/*` gate), `/health`, `/` redirect, the `/ui/config` page, branding assets, the shared static
assets, rate limiting and the bearer-token dependency for API routes. `run` is the matching CLI entry point.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import re
from collections.abc import AsyncIterator, Callable, Coroutine, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

import uvicorn
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, FastAPI, Form, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.middleware.base import RequestResponseEndpoint

from .auth import AuthManager, client_ip, is_secure_context, purge_loop
from .auth import verify_api_token as verify_bearer_token
from .config import ConfigManager
from .env_resolver import resolve_env_path
from .logging_utils import CredentialFilter
from .metrics import MetricsStore
from .timezone_utils import resolve_timezone
from .web import (
    ASSET_CACHE_CONTROL,
    STATIC_DIR,
    ConfigField,
    NavItem,
    WebLayout,
    parse_config_form,
)

logger = logging.getLogger(__name__)

UI_PREFIX = "/ui"
LOGIN_PATHS = frozenset({"/login", "/auth/login", "/auth/logout"})
UI_BYPASS_PREFIXES = (f"{UI_PREFIX}/_assets", f"{UI_PREFIX}/_static")

SKELETON_DEFAULTS: dict[str, str] = {
    "REFRESH_ENABLED": "true",
    "REFRESH_INTERVAL": "5",
    "RATE_LIMIT": "20/minute",
    "API_TOKENS": "",
}
SKELETON_SECRET_KEYS: frozenset[str] = frozenset({"API_TOKENS"})

LOGIN_MAX_CONCURRENT = 4
LOGIN_VERIFY_TIMEOUT_S = 10
CONFIG_RELOAD_INTERVAL_S = 5
TOKEN_TTL_S = 7 * 24 * 3600

_BEARER = HTTPBearer(auto_error=False)
_RATE_LIMIT_RE = re.compile(r"^\d+/(second|minute|hour|day)$")


@dataclass
class AppSpec:
    """Everything that differs between projects: the rest of the wiring is identical."""

    name: str
    slug: str
    project_root: Path
    nav_items: Sequence[NavItem]
    config_fields: Sequence[ConfigField]
    config_defaults: dict[str, str] = field(default_factory=dict)
    secret_keys: set[str] = field(default_factory=set)
    extra_head: str = ""
    routers: Sequence[APIRouter] = ()
    validate_config: Callable[[dict[str, str]], str | None] | None = None


def _setup_logging(log_dir: Path) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    stream_handler = logging.StreamHandler()
    file_handler = RotatingFileHandler(log_dir / "app.log", maxBytes=5_000_000, backupCount=3, encoding="utf-8")
    credential_filter = CredentialFilter()
    stream_handler.addFilter(credential_filter)
    file_handler.addFilter(credential_filter)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[stream_handler, file_handler],
    )


def _read_optional(static_dir: Path, *names: str) -> bytes | None:
    for name in names:
        path = static_dir / name
        if path.is_file():
            return path.read_bytes()
    return None


def _crash_on_task_error(task: asyncio.Task[None]) -> None:
    # A background loop (purge, config reload) must only ever end via .cancel() at shutdown. If it dies
    # from an unhandled exception, asyncio would just log "never retrieved" and keep the process alive
    # with silently broken purging/hot-reload — worse than crashing and letting the supervisor restart.
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.critical("Background task %s died unexpectedly, exiting", task.get_name(), exc_info=exc)
        os._exit(1)


class WebApp:
    """The wired application: `app` plus the shared objects projects use in their own routes."""

    def __init__(self, spec: AppSpec) -> None:
        self.spec = spec
        env_path = resolve_env_path()
        load_dotenv(env_path)
        self.data_dir = spec.project_root / "data"
        _setup_logging(self.data_dir / "logs")
        logger.info("Using .env=%s", env_path)

        self.host = os.getenv("HOST", "127.0.0.1")
        self.port = int(os.getenv("PORT", "8000"))
        self.dev = os.getenv("DEV", "false").lower() in ("true", "1", "yes")
        self.trusted_proxies = {ip.strip() for ip in os.getenv("TRUSTED_PROXIES", "127.0.0.1").split(",") if ip.strip()}
        self.force_secure_cookie = os.getenv("AUTH_SECURE_COOKIE", "0").strip().lower() in ("1", "true", "yes")
        self.display_tz = resolve_timezone(os.getenv("TZ", "UTC"))
        self.login_max_concurrent = LOGIN_MAX_CONCURRENT
        self.login_verify_timeout_s: float = LOGIN_VERIFY_TIMEOUT_S

        self.config = ConfigManager(
            defaults={**SKELETON_DEFAULTS, **spec.config_defaults},
            secret_keys=set(SKELETON_SECRET_KEYS) | spec.secret_keys,
            env_path=env_path,
        )
        self.auth = AuthManager(
            auth_file=self.data_dir / "auth.json", cookie_name=f"{spec.slug}_session", token_ttl=TOKEN_TTL_S
        )
        self.metrics = MetricsStore(db_path=self.data_dir / "metrics.db")
        static_dir = spec.project_root / "static"
        self.layout = WebLayout(
            spec.name,
            list(spec.nav_items),
            extra_head=spec.extra_head,
            favicon=_read_optional(static_dir, "favicon.png", "favicon.ico", "favicon.svg"),
            logo=_read_optional(static_dir, "logo.svg", "logo.png"),
        )
        self.limiter = Limiter(key_func=self._rate_limit_key)
        self._background: list[Callable[[], Coroutine[Any, Any, None]]] = []
        self._login_semaphore = asyncio.Semaphore(self.login_max_concurrent)

        self.app = FastAPI(
            title=spec.name,
            lifespan=self._lifespan,
            docs_url="/docs" if self.dev else None,
            redoc_url="/redoc" if self.dev else None,
            openapi_url="/openapi.json" if self.dev else None,
        )
        self.app.state.limiter = self.limiter
        # slowapi lacks precise stubs for this handler signature, hence the ignore below.
        self.app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]
        self.app.add_middleware(SlowAPIMiddleware)
        self.app.middleware("http")(self._auth_gate)
        self.app.include_router(self._build_router())
        for router in spec.routers:
            self.app.include_router(router)
        self.app.mount(f"{UI_PREFIX}/_assets", StaticFiles(directory=STATIC_DIR), name="webkit-assets")
        self.app.mount(f"{UI_PREFIX}/_static", StaticFiles(directory=static_dir), name="static")

    # --- shared helpers -------------------------------------------------------------------------

    def _client_ip(self, request: Request) -> str:
        host = request.client.host if request.client else "unknown"
        return client_ip(request.headers, host, self.trusted_proxies)

    def _rate_limit_key(self, request: Request) -> str:
        return self._client_ip(request)

    async def verify_api_token(
        self, credentials: HTTPAuthorizationCredentials | None = Depends(_BEARER),  # noqa: B008 - FastAPI dependency marker
    ) -> str | None:
        """Depends() for routes outside /ui that need a bearer token; a no-op while API_TOKENS is unset."""
        raw = self.config.get("API_TOKENS", "")
        tokens = {t.strip() for t in raw.split(",") if t.strip()}
        if raw.strip() and not tokens:
            # Set but blank after cleanup (e.g. " , "): fail closed instead of treating auth as unconfigured.
            logger.error("API_TOKENS is set but contains no valid tokens; denying all API requests")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="API authentication misconfigured",
                headers={"WWW-Authenticate": "Bearer"},
            )
        if tokens:
            header = f"Bearer {credentials.credentials}" if credentials else ""
            if not verify_bearer_token(header, tokens):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid or missing API token",
                    headers={"WWW-Authenticate": "Bearer"},
                )
        return credentials.credentials if credentials else None

    # --- lifecycle ------------------------------------------------------------------------------

    def add_background(self, factory: Callable[[], Coroutine[Any, Any, None]]) -> None:
        """Run ``factory()`` as a task for the app's lifetime (started in the lifespan, cancelled at shutdown).

        The coroutine should loop forever; one that raises ends the process like the built-in loops (a silent dead
        collector is worse than a restart under the supervisor).
        """
        self._background.append(factory)

    async def _config_reload_loop(self, interval_s: float) -> None:
        while True:
            await asyncio.sleep(interval_s)
            try:
                self.config.reload_if_stale()
            except Exception:
                # A transient .env read error must not end this loop (it would crash the server via
                # _crash_on_task_error): keep the last-known values and retry on the next poll.
                logger.warning("config reload failed, retrying on next poll", exc_info=True)

    @asynccontextmanager
    async def _lifespan(self, app: FastAPI) -> AsyncIterator[None]:
        await self.metrics.init_db()
        purge_task = asyncio.create_task(purge_loop(self.auth))
        purge_task.add_done_callback(_crash_on_task_error)
        config_task = asyncio.create_task(self._config_reload_loop(CONFIG_RELOAD_INTERVAL_S))
        config_task.add_done_callback(_crash_on_task_error)
        extra = [asyncio.create_task(factory()) for factory in self._background]
        for task in extra:
            task.add_done_callback(_crash_on_task_error)
        try:
            yield
        finally:
            for task in (purge_task, config_task, *extra):
                task.cancel()

    async def _auth_gate(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path
        if path in LOGIN_PATHS or any(path.startswith(p) for p in UI_BYPASS_PREFIXES):
            return await call_next(request)
        if path == UI_PREFIX or path.startswith(UI_PREFIX + "/"):
            if self.auth.verify_token(request.cookies.get(self.auth.cookie_name, "")):
                return await call_next(request)
            return RedirectResponse(url="/login", status_code=302)
        return await call_next(request)

    # --- routes ---------------------------------------------------------------------------------

    def _asset_response(self, name: str) -> Response:
        asset = self.layout.asset(name)
        if asset is None:
            return Response(status_code=404)
        data, content_type = asset
        return Response(data, media_type=content_type, headers={"Cache-Control": ASSET_CACHE_CONTROL})

    def _render_config(self, banner: str = "", *, ok: bool = True, status_code: int = 200) -> HTMLResponse:
        html = self.layout.render_config(
            list(self.spec.config_fields), self.config.get_public(), banner=banner, banner_ok=ok
        )
        return HTMLResponse(html, status_code=status_code)

    def _validate_config(self, updates: dict[str, str]) -> str | None:
        if "REFRESH_INTERVAL" in updates and int(updates["REFRESH_INTERVAL"]) < 1:
            # An HTML min= attribute only constrains normal UI use, not a crafted POST.
            return "Intervallo auto-refresh non valido (minimo 1s)"
        if "RATE_LIMIT" in updates and not _RATE_LIMIT_RE.match(updates["RATE_LIMIT"]):
            return "Rate limit non valido (formato atteso: 20/minute)"
        if self.spec.validate_config is not None:
            return self.spec.validate_config(updates)
        return None

    def _build_router(self) -> APIRouter:
        router = APIRouter()

        @router.get("/health")
        async def health() -> dict[str, str]:
            return {"status": "ok"}

        @router.get("/")
        async def root() -> RedirectResponse:
            return RedirectResponse(url=f"{UI_PREFIX}/")

        @router.get("/login", response_class=HTMLResponse)
        async def login_page(error: str = "") -> str:
            return self.layout.render_login(error)

        @router.post("/auth/login")
        async def auth_login(request: Request, password: str = Form(...)) -> RedirectResponse:
            return await self._login(request, password)

        @router.post("/auth/logout")
        async def auth_logout(request: Request) -> RedirectResponse:
            response = RedirectResponse(url="/login", status_code=303)
            response.delete_cookie(
                self.auth.cookie_name,
                httponly=True,
                samesite="strict",
                secure=self.force_secure_cookie or is_secure_context(request.headers),
            )
            return response

        # Explicit routes, not a wildcard: they win over the /ui/_assets StaticFiles mount and must not
        # shadow app.css. Both are gate-exempt through the /ui/_assets prefix.
        @router.get(f"{UI_PREFIX}/_assets/favicon")
        async def favicon() -> Response:
            return self._asset_response("favicon")

        @router.get(f"{UI_PREFIX}/_assets/logo")
        async def logo() -> Response:
            return self._asset_response("logo")

        @router.get(f"{UI_PREFIX}/config", response_class=HTMLResponse)
        async def config_page(result: str = "") -> HTMLResponse:
            return self._render_config("Configurazione salvata" if result == "ok" else "")

        @router.post(f"{UI_PREFIX}/config", response_model=None)
        async def config_save(request: Request) -> HTMLResponse | RedirectResponse:
            form = {k: v for k, v in (await request.form()).items() if isinstance(v, str)}
            updates, error = parse_config_form(list(self.spec.config_fields), form)
            problem = error or self._validate_config(updates)
            if problem:
                return self._render_config(problem, ok=False, status_code=400)
            self.config.update_many(updates)
            return RedirectResponse(url=f"{UI_PREFIX}/config?result=ok", status_code=303)

        return router

    async def _login(self, request: Request, password: str) -> RedirectResponse:
        ip = self._client_ip(request)
        auth = self.auth
        if not auth.has_password():
            return RedirectResponse(url="/login?error=nopassword", status_code=303)
        if auth.is_ip_blocked(ip):
            return RedirectResponse(url="/login?error=blocked", status_code=303)
        if auth.is_global_limited():
            # Cross-IP volume is logged, never used to block: a hard global lockout lets one attacker lock
            # out every legitimate admin login. Per-IP blocking above is the real defense.
            logger.warning("elevated login attempt volume across IPs; latest attempt from ip=%s", ip)

        # scrypt (N=131072) takes ~150-250ms and ~128MB: run it off the event loop, and cap how many run at
        # once so a burst of unauthenticated attempts cannot multiply into an unbounded memory spike.
        async with self._login_semaphore:
            try:
                success = await asyncio.wait_for(
                    asyncio.to_thread(auth.verify_password, password), timeout=self.login_verify_timeout_s
                )
            except TimeoutError as exc:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Login temporarily unavailable"
                ) from exc
        auth.record_attempt(ip, success=success)
        if not success:
            return RedirectResponse(url="/login?error=invalid", status_code=303)

        response = RedirectResponse(url=f"{UI_PREFIX}/", status_code=303)
        response.set_cookie(
            auth.cookie_name,
            auth.create_token(),
            httponly=True,
            samesite="strict",
            secure=self.force_secure_cookie or is_secure_context(request.headers),
            max_age=auth.token_ttl,
        )
        return response


def create_app(spec: AppSpec) -> WebApp:
    """Build the shared wiring for `spec`; see the module docstring for what it covers."""
    return WebApp(spec)


def run(import_string: str, web: WebApp) -> None:
    """CLI entry point: `--host`, `--port`, `--dev` (uvicorn reload), `--env-file` (read by resolve_env_path)."""
    parser = argparse.ArgumentParser(description=f"{web.spec.name} — FastAPI + Jinja2/HTMX web app")
    parser.add_argument("--port", type=int, default=web.port)
    parser.add_argument("--host", type=str, default=web.host)
    parser.add_argument("--dev", action=argparse.BooleanOptionalAction, default=web.dev)
    parser.add_argument("--env-file", type=str, default=None)
    args = parser.parse_args()
    root = web.spec.project_root
    uvicorn.run(
        import_string,
        host=args.host,
        port=args.port,
        reload=args.dev,
        # Reload must not watch data/ (logs, sqlite, auth.json): the app writes there continuously, and
        # watching it makes every log line trigger a reload that logs again, forever.
        reload_dirs=[str(root / "app"), str(root / "static")] if args.dev else None,
        loop="asyncio",
    )
