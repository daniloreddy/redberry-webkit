from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import NamedTuple

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from markupsafe import Markup

STATIC_DIR: Path = Path(__file__).resolve().parent / "static"
"""Directory holding the shared `app.css`; mount it at `/ui/_assets` (auth-exempt) in the host app."""

_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

_ENV = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=True,
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)

LOGIN_ERRORS: dict[str, str] = {
    "nopassword": "Nessuna password configurata — esegui lo strumento set-password.",
    "blocked": "Troppi tentativi falliti da questo indirizzo. Riprova più tardi.",
    "limited": "Troppi tentativi di accesso in questo momento. Riprova tra un minuto.",
    "invalid": "Password errata.",
}
"""Login error code (the `?error=` query value) to its user-facing message."""


class NavItem(NamedTuple):
    """One top-nav entry. `icon` is trusted inline SVG (see `icons.icon`); empty shows only the tooltip."""

    label: str
    href: str
    icon: str = ""


class FieldType(Enum):
    """Input kind rendered for a runtime-editable config key."""

    TEXT = "text"
    NUMBER = "number"
    BOOL = "bool"


@dataclass(frozen=True)
class ConfigField:
    """One runtime-editable config key shown on the config page. `password` never echoes the current value."""

    key: str
    label: str
    help: str = ""
    type: FieldType = FieldType.TEXT
    password: bool = False


ASSET_CACHE_CONTROL = "public, max-age=86400"
"""`Cache-Control` value for the favicon/logo responses (same as webkit-go/-j)."""


_PNG_MAGIC = bytes.fromhex("89504e470d0a1a0a")
_JPEG_MAGIC = bytes.fromhex("ffd8ff")
_ICO_MAGIC = bytes.fromhex("00000100")
_BOM = "\N{ZERO WIDTH NO-BREAK SPACE}"


def detect_image_content_type(data: bytes) -> str:
    """Sniff a favicon/logo content type by magic number (PNG, JPEG, GIF, ICO, WebP, SVG), else octet-stream."""
    if data.startswith(_PNG_MAGIC):
        return "image/png"
    if data.startswith(_JPEG_MAGIC):
        return "image/jpeg"
    if data.startswith(b"GIF8"):
        return "image/gif"
    if data.startswith(_ICO_MAGIC):
        return "image/x-icon"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    head = data[:256].decode("utf-8", errors="ignore").lstrip(_BOM).lstrip()
    if head.startswith(("<?xml", "<svg")):
        return "image/svg+xml"
    return "application/octet-stream"


def login_error_message(code: str) -> str:
    """Return the message for a login `?error=` code, or an empty string if unknown/empty."""
    return LOGIN_ERRORS.get(code, "")


def parse_config_form(fields: Sequence[ConfigField], form: Mapping[str, str]) -> tuple[dict[str, str], str]:
    """Turn a posted config form into `ConfigManager.update_many()` input.

    Returns `(updates, error)`; a non-empty `error` is a user-facing message and `updates` must not be saved.
    Blank text/number/password values are skipped (a blank field never wipes a stored key); an unchecked
    checkbox posts nothing and is stored as "false".
    """
    updates: dict[str, str] = {}
    for field in fields:
        value = form.get(field.key, "").strip()
        if field.type is FieldType.BOOL:
            updates[field.key] = "true" if value == "on" else "false"
        elif not value:
            continue
        elif field.type is FieldType.NUMBER:
            try:
                int(value)
            except ValueError:
                return {}, f"Valore non numerico per {field.label}"
            updates[field.key] = value
        else:
            updates[field.key] = value
    return updates, ""


class WebLayout:
    """Renders the shared page chrome (topbar, nav, theme toggle, logout, footer) and the login/config pages.

    `favicon`/`logo` are optional raw image bytes: when given, the layout links the favicon on every
    page and shows the logo left of the app name in the topbar (not on the login page). The host app
    serves them at `/ui/_assets/favicon` and `/ui/_assets/logo` (auth-exempt) from `asset()`, with
    `ASSET_CACHE_CONTROL`.

    Framework-free: every `render_*` returns an HTML `str`. `content` must be `markupsafe.Markup` to be
    emitted as HTML; a plain `str` is escaped. `extra_head` and `NavItem.icon` are trusted markup;
    `footer_right` is escaped text. `nav_items` may be replaced at runtime for a dynamic nav.
    """

    def __init__(
        self,
        app_name: str,
        nav_items: Sequence[NavItem] = (),
        *,
        extra_head: str = "",
        footer_right: str = "",
        favicon: bytes | None = None,
        logo: bytes | None = None,
        lang: str = "it",
    ) -> None:
        self.app_name = app_name
        self.nav_items: list[NavItem] = list(nav_items)
        self.extra_head = extra_head
        self.footer_right = footer_right
        self.favicon = favicon
        self.logo = logo
        self.lang = lang

    def asset(self, name: str) -> tuple[bytes, str] | None:
        """Return `(bytes, content_type)` for `"favicon"` or `"logo"`, or None when unset/unknown (answer 404)."""
        data = {"favicon": self.favicon, "logo": self.logo}.get(name)
        return None if not data else (data, detect_image_content_type(data))

    def _context(self, title: str, content: str) -> dict[str, object]:
        return {
            "app_name": self.app_name,
            "title": title,
            "content": content,
            "extra_head": Markup(self.extra_head),
            "has_favicon": bool(self.favicon),
            "lang": self.lang,
        }

    def render_page(self, title: str, nav_current: str, content: str) -> str:
        """Render an authenticated page; `nav_current` highlights the nav entry with that label (case-insensitive)."""
        nav = [
            {
                "label": n.label,
                "href": n.href,
                "icon": Markup(n.icon),
                "active": n.label.lower() == nav_current.lower(),
            }
            for n in self.nav_items
        ]
        ctx = self._context(title, content)
        ctx.update(nav=nav, footer_right=self.footer_right, has_logo=bool(self.logo))
        return _ENV.get_template("layout.html").render(ctx)

    def render_auth(self, title: str, content: str) -> str:
        """Render a pre-auth page (centered card, no topbar/nav)."""
        return _ENV.get_template("auth.html").render(self._context(title, content))

    def render_login(self, error_code: str = "") -> str:
        """Render the full login page; `error_code` is the `?error=` query value."""
        form = _ENV.get_template("login_form.html").render(
            app_name=self.app_name, error=login_error_message(error_code)
        )
        return self.render_auth(f"{self.app_name} · Login", Markup(form))

    def render_config(
        self,
        fields: Sequence[ConfigField],
        values: Mapping[str, str],
        *,
        banner: str = "",
        banner_ok: bool = True,
    ) -> str:
        """Render the runtime-config page in the shared layout; pass `ConfigManager.get_public()` as `values`."""
        views = [
            {
                "key": f.key,
                "label": f.label,
                "help": f.help,
                "type": f.type.value,
                "password": f.password,
                "value": "" if f.password else values.get(f.key, ""),
            }
            for f in fields
        ]
        form = _ENV.get_template("config_form.html").render(fields=views, banner=banner, banner_ok=banner_ok)
        return self.render_page("Impostazioni", "Impostazioni", Markup(form))
