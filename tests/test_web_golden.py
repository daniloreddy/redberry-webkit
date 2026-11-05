from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from markupsafe import Markup

from redberry_webkit.web import ConfigField, FieldType, NavItem, WebLayout, status_badge

# Golden conformance test against redberry-webkit-ui: the same fixtures and expected HTML that
# redberry-webkit-go and redberry-webkit-j are tested against. tests/ui is a copy synced from the
# redberry-webkit-ui repo (scripts/sync.py); never edit it here.

_UI = Path(__file__).parent / "ui"
_FIXTURES: dict[str, Any] = json.loads((_UI / "fixtures.json").read_text(encoding="utf-8"))

# 1x1 stand-in bytes: only the presence of a favicon/logo matters for the markup.
_IMAGE = b"\x89PNG\r\n\x1a\nfake"


def _normalize(html: str) -> str:
    """The shared comparison rule (see redberry-webkit-ui README)."""
    html = re.sub(r"<!--.*?-->", "", html, flags=re.S)
    html = re.sub(r"\s+", " ", html)
    html = re.sub(r">\s<", "><", html)
    return html.strip()


def _layout(case: dict[str, Any]) -> WebLayout:
    return WebLayout(
        _FIXTURES["app_name"],
        [NavItem(n["label"], n["href"], n["icon"]) for n in _FIXTURES["nav"]],
        extra_head=_FIXTURES["extra_head"],
        footer_right=case.get("footer_right", ""),
        favicon=_IMAGE if case.get("favicon") else None,
        logo=_IMAGE if case.get("logo") else None,
    )


def _fields() -> list[ConfigField]:
    types = {"text": FieldType.TEXT, "number": FieldType.NUMBER, "bool": FieldType.BOOL}
    return [
        ConfigField(f["key"], f["label"], f.get("help", ""), types[f["type"]], f.get("password", False))
        for f in _FIXTURES["fields"]
    ]


def _render(case: dict[str, Any]) -> str:
    layout = _layout(case)
    kind = case["kind"]
    if kind == "layout":
        return layout.render_page(case["title"], case["nav_current"], Markup(_FIXTURES["content"]))
    if kind == "login":
        return layout.render_login(case["error_code"])
    if kind == "config":
        banner = "Configurazione salvata" if case["saved"] else ""
        return layout.render_config(_fields(), _FIXTURES["values"], banner=banner)
    raise AssertionError(f"unknown case kind {kind!r}")


@pytest.mark.parametrize("name", sorted(_FIXTURES["cases"]))
def test_page_matches_golden(name: str) -> None:
    golden = (_UI / "golden" / f"{name}.html").read_text(encoding="utf-8")

    assert _normalize(_render(_FIXTURES["cases"][name])) == golden.strip()


def test_status_badges_match_golden() -> None:
    golden = (_UI / "golden" / "status_badges.html").read_text(encoding="utf-8")
    badges = "\n".join(str(status_badge(s["status"], s["error"])) for s in _FIXTURES["status_badges"]) + "\n"

    assert _normalize(badges) == golden.strip()
