from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi import Depends, Request
from fastapi.testclient import TestClient

from redberry_webkit.bootstrap import AppSpec, WebApp, create_app
from redberry_webkit.web import ConfigField, FieldType, NavItem, icon


def _spec(root: Path, **kwargs: object) -> AppSpec:
    (root / "static").mkdir(exist_ok=True)
    return AppSpec(
        name="Probe App",
        slug="probe_app",
        project_root=root,
        nav_items=[NavItem("Dashboard", "/ui/", icon("home"))],
        config_fields=[
            ConfigField("REFRESH_ENABLED", "Auto-refresh", type=FieldType.BOOL),
            ConfigField("REFRESH_INTERVAL", "Intervallo", type=FieldType.NUMBER),
            ConfigField("RATE_LIMIT", "Rate limit"),
        ],
        **kwargs,  # type: ignore[arg-type]
    )


@pytest.fixture
def web(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> WebApp:
    env_file = tmp_path / ".env"
    env_file.write_text("RATE_LIMIT=20/minute\n", encoding="utf-8")
    monkeypatch.setenv("ENV_FILE", str(env_file))
    monkeypatch.delenv("DEV", raising=False)
    w = create_app(_spec(tmp_path))

    @w.app.get("/api/v1/example")
    @w.limiter.limit(lambda: w.config.get("RATE_LIMIT", "20/minute"))
    async def example(request: Request, token: str | None = Depends(w.verify_api_token)) -> dict[str, str]:
        return {"message": "ok"}

    return w


@pytest.fixture
def client(web: WebApp) -> TestClient:
    # Context manager so the lifespan (metrics.init_db, background loops) runs.
    with TestClient(web.app) as c:
        yield c  # type: ignore[misc]


def _login(client: TestClient, web: WebApp) -> None:
    web.auth.set_password("test-password-123")
    client.post("/auth/login", data={"password": "test-password-123"}, follow_redirects=False)


def test_health(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}


def test_root_redirects_to_ui(client: TestClient) -> None:
    response = client.get("/", follow_redirects=False)
    assert response.status_code in (302, 307)
    assert response.headers["location"].endswith("/ui/")


def test_ui_requires_auth_redirects_to_login(client: TestClient) -> None:
    response = client.get("/ui/config", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/login"


def test_docs_disabled_when_not_dev(client: TestClient) -> None:
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_cookie_name_derives_from_slug(web: WebApp) -> None:
    assert web.auth.cookie_name == "probe_app_session"


def test_login_flow(client: TestClient, web: WebApp) -> None:
    web.auth.set_password("test-password-123")
    response = client.post("/auth/login", data={"password": "test-password-123"}, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/ui/"
    assert web.auth.cookie_name in response.cookies


def test_login_wrong_password(client: TestClient, web: WebApp) -> None:
    web.auth.set_password("test-password-123")
    response = client.post("/auth/login", data={"password": "wrong"}, follow_redirects=False)
    assert response.status_code == 303
    assert "error=invalid" in response.headers["location"]


def test_login_without_password_configured(client: TestClient) -> None:
    response = client.post("/auth/login", data={"password": "x"}, follow_redirects=False)
    assert "error=nopassword" in response.headers["location"]


def test_logout_clears_cookie(client: TestClient, web: WebApp) -> None:
    _login(client, web)
    response = client.post("/auth/logout", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_login_page_and_assets_render_without_auth(client: TestClient) -> None:
    page = client.get("/login", params={"error": "invalid"})
    assert page.status_code == 200
    assert "Password errata." in page.text
    assert 'action="/auth/login"' in page.text
    assert client.get("/ui/_assets/app.css").status_code == 200
    assert client.get("/ui/_assets/app.js").status_code == 200


def test_example_endpoint_ok_and_rate_limited(client: TestClient, web: WebApp) -> None:
    web.config.update_many({"RATE_LIMIT": "2/minute"})
    for _ in range(2):
        assert client.get("/api/v1/example").status_code == 200
    assert client.get("/api/v1/example").status_code == 429


def test_bearer_token_enforced_when_configured(client: TestClient, web: WebApp) -> None:
    web.config.update_many({"API_TOKENS": "abc123"})
    assert client.get("/api/v1/example").status_code == 401
    assert client.get("/api/v1/example", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/api/v1/example", headers={"Authorization": "Bearer abc123"}).status_code == 200


def test_non_ascii_bearer_token_is_401_not_500(client: TestClient, web: WebApp) -> None:
    # Raw bytes bypass httpx's client-side ASCII check, like a real non-conforming client would.
    web.config.update_many({"API_TOKENS": "abc123"})
    response = client.get("/api/v1/example", headers=[("Authorization", "Bearer café".encode())])
    assert response.status_code == 401


def test_blank_api_tokens_fail_closed(client: TestClient, web: WebApp) -> None:
    web.config.update_many({"API_TOKENS": " , "})
    # update_many skips blank values, so write the raw env and reload.
    web.config._env_path.write_text("API_TOKENS= , \n", encoding="utf-8")
    web.config.reload_if_stale()
    assert client.get("/api/v1/example").status_code == 401


def test_login_semaphore_caps_concurrent_verify(client: TestClient, web: WebApp) -> None:
    web.auth.set_password("test-password-123")
    lock = threading.Lock()
    state = {"now": 0, "max": 0}

    def _slow_verify(password: str) -> bool:
        with lock:
            state["now"] += 1
            state["max"] = max(state["max"], state["now"])
        time.sleep(0.3)
        with lock:
            state["now"] -= 1
        return True

    web.auth.verify_password = _slow_verify  # type: ignore[method-assign]
    workers = web.login_max_concurrent + 4
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(client.post, "/auth/login", data={"password": "x"}, follow_redirects=False)
            for _ in range(workers)
        ]
        assert all(f.result().status_code == 303 for f in futures)
    assert state["max"] <= web.login_max_concurrent


def test_login_verify_timeout_returns_503(client: TestClient, web: WebApp) -> None:
    web.auth.set_password("test-password-123")
    web.login_verify_timeout_s = 0.05
    web.auth.verify_password = lambda password: time.sleep(0.3) or True  # type: ignore[method-assign]
    assert client.post("/auth/login", data={"password": "test-password-123"}).status_code == 503


def test_config_page_save_roundtrip(client: TestClient, web: WebApp) -> None:
    _login(client, web)
    response = client.post(
        "/ui/config",
        data={"REFRESH_ENABLED": "on", "REFRESH_INTERVAL": "9", "RATE_LIMIT": "30/minute"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert web.config.get("REFRESH_INTERVAL") == "9"
    assert web.config.get("RATE_LIMIT") == "30/minute"
    assert 'value="9"' in client.get("/ui/config").text


def test_config_page_rejects_invalid_values(client: TestClient, web: WebApp) -> None:
    _login(client, web)
    bad_rate = client.post("/ui/config", data={"REFRESH_INTERVAL": "5", "RATE_LIMIT": "lots"})
    bad_interval = client.post("/ui/config", data={"REFRESH_INTERVAL": "0", "RATE_LIMIT": "5/minute"})
    assert bad_rate.status_code == 400
    assert "Rate limit non valido" in bad_rate.text
    assert bad_interval.status_code == 400
    assert "minimo 1s" in bad_interval.text


def test_project_validate_config_hook(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENV_FILE", str(tmp_path / ".env"))
    w = create_app(_spec(tmp_path, validate_config=lambda u: "no way" if u.get("RATE_LIMIT") == "1/second" else None))
    with TestClient(w.app) as c:
        _login(c, w)
        response = c.post("/ui/config", data={"REFRESH_INTERVAL": "5", "RATE_LIMIT": "1/second"})
    assert response.status_code == 400
    assert "no way" in response.text


def test_project_config_defaults_are_merged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENV_FILE", str(tmp_path / ".env"))
    w = create_app(_spec(tmp_path, config_defaults={"MY_KEY": "v"}, secret_keys={"MY_SECRET"}))
    assert w.config.get("MY_KEY") == "v"
    assert w.config.get("REFRESH_INTERVAL") == "5"


def test_branding_assets_404_when_unset_and_served_when_set(client: TestClient, web: WebApp) -> None:
    assert client.get("/ui/_assets/logo").status_code == 404
    assert client.get("/ui/_assets/favicon").status_code == 404
    assert client.get("/ui/_assets/app.css").status_code == 200  # explicit routes don't shadow the mount

    web.layout.logo = b"<svg xmlns='http://www.w3.org/2000/svg'/>"
    response = client.get("/ui/_assets/logo")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/svg+xml")
    assert response.headers["cache-control"] == "public, max-age=86400"


def test_project_static_dir_is_mounted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENV_FILE", str(tmp_path / ".env"))
    (tmp_path / "static").mkdir()
    (tmp_path / "static" / "app.css").write_text("body{}", encoding="utf-8")
    w = create_app(_spec(tmp_path))
    with TestClient(w.app) as c:
        assert c.get("/ui/_static/app.css").status_code == 200


def test_add_background_runs_for_the_app_lifetime(web: WebApp) -> None:
    import asyncio

    state = {"started": False, "cancelled": False}

    async def loop() -> None:
        state["started"] = True
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            state["cancelled"] = True
            raise

    web.add_background(loop)
    with TestClient(web.app) as c:
        assert c.get("/health").status_code == 200
        assert state["started"]
    assert state["cancelled"]
