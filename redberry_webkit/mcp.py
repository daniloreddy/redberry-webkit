"""In-process MCP server for a webkit app: ASGI guard, /mcp mount and shared config keys.

Optional extra ``redberry-webkit[mcp]`` (needs the ``app`` extra too). The project builds its own ``MCPServer`` with
its tools (the SDK's ``mcp.server.mcpserver.MCPServer``, mcp >= 2); this module adds the transport side that is
identical for every service: global rate limit -> global concurrency cap -> Bearer (``API_TOKENS``, fail-closed) ->
streamable-HTTP handler at ``/mcp`` (stateless JSON). See ``~/.claude/guidelines/py-mcp.md``.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import AsyncIterator, Callable
from contextvars import ContextVar
from typing import TYPE_CHECKING

from limits import parse
from limits.storage import MemoryStorage
from limits.strategies import FixedWindowRateLimiter
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import ValidationError
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.types import ASGIApp, Receive, Scope, Send

from .auth import verify_api_token as verify_bearer_token
from .config import ConfigManager
from .request_view import request_meta
from .web import ConfigField, FieldType

if TYPE_CHECKING:
    from fastapi import FastAPI

    from .bootstrap import WebApp

logger = logging.getLogger(__name__)

MCP_PATH = "/mcp"
DEFAULT_MAX_REQUEST_BODY_SIZE = 4 << 20
CONCURRENCY_WAIT_S = 0.5

MCP_CONFIG_DEFAULTS: dict[str, str] = {"MCP_RATE_LIMIT": "60/minute", "MCP_MAX_CONCURRENT": "8"}
"""Spread into ``AppSpec.config_defaults``."""

MCP_CONFIG_FIELDS: list[ConfigField] = [
    ConfigField(
        "MCP_RATE_LIMIT",
        "MCP: rate limit globale (es. 60/minute)",
        help="Globale (non per-IP), applicato a /mcp prima del controllo Bearer",
    ),
    ConfigField("MCP_MAX_CONCURRENT", "MCP: richieste concorrenti massime", type=FieldType.NUMBER),
]
"""Extend ``AppSpec.config_fields`` with these to edit the MCP guards from /ui/config."""

_client_info: ContextVar[tuple[str, str]] = ContextVar("redberry_mcp_client_info", default=("", ""))


def current_client() -> tuple[str, str]:
    """(client IP, User-Agent) of the request being served; ("", "") outside a guarded /mcp request."""
    return _client_info.get()


def validation_message(exc: ValidationError) -> str:
    """First pydantic error as ``field: reason`` (never the rejected value, which is the caller's data)."""
    err = exc.errors()[0]
    loc = ".".join(str(p) for p in err["loc"])
    msg = str(err["msg"]).removeprefix("Value error, ")
    return f"{loc}: {msg}" if loc and err["type"] != "value_error" else msg


class McpGuard:
    """ASGI wrapper for /mcp: global rate limit -> global concurrency cap -> bearer (API_TOKENS) -> handler.

    The two DoS guards are global (constant key), not per-IP: behind a tunnel every request shares one IP. They run
    before the bearer check so a flood with wrong tokens is limited too. Limits are read live from config.
    """

    def __init__(self, app: ASGIApp, config: ConfigManager, trusted_proxies: set[str]) -> None:
        self._app = app
        self._config = config
        self._trusted_proxies = trusted_proxies
        self._limiter = FixedWindowRateLimiter(MemoryStorage())
        self._inflight = 0

    def _rate_limited(self) -> int | None:
        """Seconds until the window resets when over MCP_RATE_LIMIT, else None. Unparseable value = fail-open."""
        raw = self._config.get("MCP_RATE_LIMIT", MCP_CONFIG_DEFAULTS["MCP_RATE_LIMIT"])
        try:
            item = parse(raw)
        except ValueError:
            logger.warning("MCP_RATE_LIMIT %r is not parseable; rate limiting disabled", raw)
            return None
        if self._limiter.hit(item, "global"):
            return None
        stats = self._limiter.get_window_stats(item, "global")
        return max(1, int(stats.reset_time - time.time()) + 1)

    async def _acquire(self) -> bool:
        limit = max(1, self._config.get_int("MCP_MAX_CONCURRENT", 8))
        deadline = time.monotonic() + CONCURRENCY_WAIT_S
        while self._inflight >= limit:
            if time.monotonic() >= deadline:
                return False
            await asyncio.sleep(0.02)
        self._inflight += 1
        return True

    def _auth_error(self, headers: Headers) -> JSONResponse | None:
        raw = self._config.get("API_TOKENS", "")
        if not raw.strip():
            return JSONResponse({"detail": "MCP disabled: API_TOKENS not configured"}, status_code=503)
        tokens = {t.strip() for t in raw.split(",") if t.strip()}
        if not tokens or not verify_bearer_token(headers.get("authorization", ""), tokens):
            return JSONResponse(
                {"detail": "Invalid or missing API token"}, status_code=401, headers={"WWW-Authenticate": "Bearer"}
            )
        return None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        retry_after = self._rate_limited()
        if retry_after is not None:
            await JSONResponse(
                {"detail": "rate limit exceeded"}, status_code=429, headers={"Retry-After": str(retry_after)}
            )(scope, receive, send)
            return
        if not await self._acquire():
            await JSONResponse({"detail": "server busy"}, status_code=503, headers={"Retry-After": "1"})(
                scope, receive, send
            )
            return
        try:
            headers = Headers(scope=scope)
            error = self._auth_error(headers)
            if error is not None:
                await error(scope, receive, send)
                return
            client = scope.get("client")
            token = _client_info.set(request_meta(headers, client[0] if client else "unknown", self._trusted_proxies))
            try:
                await self._app(scope, receive, send)
            finally:
                _client_info.reset(token)
        finally:
            self._inflight -= 1


class McpEndpoint:
    """Stable ASGI endpoint for /mcp: delegates to the guard of the running lifespan (503 while not running)."""

    def __init__(self) -> None:
        self.guard: McpGuard | None = None
        self.__name__ = "mcp_endpoint"  # slowapi's middleware reads handler.__name__

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if self.guard is None:
            await JSONResponse({"detail": "MCP not running"}, status_code=503)(scope, receive, send)
            return
        await self.guard(scope, receive, send)


def mount_mcp(
    web: WebApp,
    build_server: Callable[[], MCPServer],
    *,
    max_request_body_size: int = DEFAULT_MAX_REQUEST_BODY_SIZE,
) -> McpEndpoint:
    """Serve the project's MCP server at /mcp on ``web.app`` (stateless JSON, no long-held streams).

    ``build_server`` is called on every lifespan start: the SDK's session manager can run only once per instance.
    Raise ``max_request_body_size`` (default 4 MiB) when a tool accepts large payloads such as attachments.
    """
    app: FastAPI = web.app
    endpoint = McpEndpoint()
    app.router.routes.append(Route(MCP_PATH, endpoint=endpoint, methods=["GET", "POST", "DELETE"]))
    host_lifespan = app.router.lifespan_context

    @contextlib.asynccontextmanager
    async def lifespan(a: FastAPI) -> AsyncIterator[None]:
        server = build_server()
        inner = server.streamable_http_app(
            streamable_http_path=MCP_PATH,
            stateless_http=True,
            json_response=True,
            max_request_body_size=max_request_body_size,
            # Cloudflare Tunnel forwards to 127.0.0.1 with the public Host header: the SDK's localhost DNS-rebinding
            # check would 403 every tunneled request. McpGuard (fail-closed bearer) covers the risk it exists for.
            transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
        )
        endpoint.guard = McpGuard(inner, web.config, web.trusted_proxies)
        try:
            async with host_lifespan(a), server.session_manager.run():
                yield
        finally:
            endpoint.guard = None

    app.router.lifespan_context = lifespan
    return endpoint
