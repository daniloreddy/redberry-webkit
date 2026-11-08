from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from mcp.server.mcpserver import MCPServer
from pydantic import BaseModel, ValidationError

from redberry_webkit.bootstrap import AppSpec, WebApp, create_app
from redberry_webkit.mcp import (
    MCP_CONFIG_DEFAULTS,
    MCP_CONFIG_FIELDS,
    McpEndpoint,
    current_client,
    mount_mcp,
    validation_message,
)
from redberry_webkit.web import NavItem, icon

TOKEN = "sekret"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
HEADERS = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}


class EchoResult(BaseModel):
    text: str
    client_ip: str
    user_agent: str


class Gate:
    """Lets a test hold the `slow` tool open to observe the concurrency cap."""

    started = threading.Event()
    release = threading.Event()


def build_server() -> MCPServer:
    server = MCPServer("probe")

    @server.tool(name="probe_echo", description="Echo the text and the caller seen by the guard")
    async def probe_echo(text: str) -> EchoResult:
        ip, user_agent = current_client()
        return EchoResult(text=text, client_ip=ip, user_agent=user_agent)

    @server.tool(name="probe_slow", description="Block until released")
    async def probe_slow() -> EchoResult:
        Gate.started.set()
        await _wait(Gate.release)
        return EchoResult(text="done", client_ip="", user_agent="")

    return server


async def _wait(event: threading.Event) -> None:
    import asyncio

    for _ in range(500):
        if event.is_set():
            return
        await asyncio.sleep(0.02)


def make_web(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tokens: str) -> WebApp:
    env_file = tmp_path / ".env"
    env_file.write_text(f"RATE_LIMIT=1000/minute\nAPI_TOKENS={tokens}\n", encoding="utf-8")
    monkeypatch.setenv("ENV_FILE", str(env_file))
    monkeypatch.delenv("DEV", raising=False)
    (tmp_path / "static").mkdir()
    Gate.started.clear()
    Gate.release.clear()
    w = create_app(
        AppSpec(
            name="Probe",
            slug="probe",
            project_root=tmp_path,
            nav_items=[NavItem("Dashboard", "/ui/", icon("home"))],
            config_fields=MCP_CONFIG_FIELDS,
            config_defaults=MCP_CONFIG_DEFAULTS,
        )
    )
    mount_mcp(w, build_server)
    return w


@pytest.fixture
def web(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> WebApp:
    return make_web(tmp_path, monkeypatch, TOKEN)


@pytest.fixture
def client(web: WebApp) -> TestClient:
    with TestClient(web.app) as c:
        yield c  # type: ignore[misc]


def rpc(client: TestClient, method: str, params: dict[str, Any] | None = None, **kwargs: Any) -> Any:
    headers = {**HEADERS, **kwargs.pop("auth", AUTH), **kwargs.pop("extra", {})}
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
    return client.post("/mcp", json=body, headers=headers)


def call_tool(client: TestClient, name: str, arguments: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    response = rpc(client, "tools/call", {"name": name, "arguments": arguments}, **kwargs)
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()["result"]
    return result


def test_config_defaults_and_fields_cover_the_same_keys() -> None:
    assert {f.key for f in MCP_CONFIG_FIELDS} == set(MCP_CONFIG_DEFAULTS)


def test_tools_list_has_input_and_output_schemas(client: TestClient) -> None:
    tools = {t["name"]: t for t in rpc(client, "tools/list").json()["result"]["tools"]}
    assert set(tools) == {"probe_echo", "probe_slow"}
    assert tools["probe_echo"]["outputSchema"]["type"] == "object"


def test_blocked_without_tokens_is_503(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    w = make_web(tmp_path, monkeypatch, "")
    with TestClient(w.app) as c:
        response = rpc(c, "tools/list", auth={})
    assert response.status_code == 503
    assert "API_TOKENS not configured" in response.json()["detail"]


@pytest.mark.parametrize("auth", [{}, {"Authorization": "Bearer nope"}, {"Authorization": f"Token {TOKEN}"}])
def test_missing_or_wrong_token_is_401(client: TestClient, auth: dict[str, str]) -> None:
    response = rpc(client, "tools/list", auth=auth)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_rate_limit_applies_before_bearer(client: TestClient, web: WebApp) -> None:
    web.config.update_many({"MCP_RATE_LIMIT": "2/minute"})
    wrong = {"Authorization": "Bearer nope"}
    assert [rpc(client, "tools/list", auth=wrong).status_code for _ in range(2)] == [401, 401]
    limited = rpc(client, "tools/list", auth=wrong)
    assert limited.status_code == 429
    assert int(limited.headers["retry-after"]) >= 1


def test_unparseable_rate_limit_fails_open(client: TestClient, web: WebApp) -> None:
    web.config.update_many({"MCP_RATE_LIMIT": "not-a-limit"})
    assert rpc(client, "tools/list").status_code == 200


def test_concurrency_cap_is_503(client: TestClient, web: WebApp) -> None:
    web.config.update_many({"MCP_MAX_CONCURRENT": "1"})
    first = threading.Thread(target=call_tool, args=(client, "probe_slow", {}))
    first.start()
    try:
        assert Gate.started.wait(timeout=10), "first call never reached the tool"
        assert rpc(client, "tools/list").status_code == 503
    finally:
        Gate.release.set()
        first.join(timeout=10)
    assert rpc(client, "tools/list").status_code == 200


def test_tool_sees_client_ip_and_user_agent(client: TestClient) -> None:
    result = call_tool(client, "probe_echo", {"text": "hi"}, extra={"User-Agent": "probe-agent/1.0"})
    assert result["structuredContent"]["text"] == "hi"
    assert result["structuredContent"]["user_agent"] == "probe-agent/1.0"
    assert result["structuredContent"]["client_ip"]


def test_foreign_host_header_is_not_rejected(client: TestClient) -> None:
    """DNS-rebinding protection is off: a tunnel forwards the public Host to 127.0.0.1."""
    assert rpc(client, "tools/list", extra={"Host": "mcp.example.com"}).status_code == 200


def test_lifespan_can_restart(web: WebApp) -> None:
    for _ in range(2):
        with TestClient(web.app) as c:
            assert rpc(c, "tools/list").status_code == 200


def test_guard_is_cleared_outside_lifespan(web: WebApp) -> None:
    endpoint = next(r.endpoint for r in web.app.routes if getattr(r, "path", "") == "/mcp")
    assert isinstance(endpoint, McpEndpoint) and endpoint.guard is None
    with TestClient(web.app):
        assert endpoint.guard is not None
    assert endpoint.guard is None


def test_validation_message_hides_values() -> None:
    class M(BaseModel):
        uid: int

    with pytest.raises(ValidationError) as exc:
        M.model_validate({"uid": "secret-value"})
    message = validation_message(exc.value)
    assert message.startswith("uid:")
    assert "secret-value" not in message
