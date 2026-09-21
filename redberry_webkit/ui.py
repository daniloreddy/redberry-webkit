from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any, NamedTuple

from nicegui import app as ng_app
from nicegui import ui


class NavItem(NamedTuple):
    """One header nav button. Structurally a `(label, icon, path)` 3-tuple — an
    existing project's bare-tuple `NAV_ITEMS` list still unpacks correctly."""

    label: str
    icon: str
    path: str


def logout_action(logout_path: str = "/auth/logout") -> None:
    """Standard logout icon button. Navigates via JS, not `ui.navigate.to()` — logout is
    a FastAPI route outside NiceGUI's `/ui` mount (@rules/nicegui.md §5)."""
    ui.button(
        icon="logout",
        on_click=lambda: ui.run_javascript(f"window.location.href='{logout_path}'"),
    ).props("flat color=white round").tooltip("Esci")


def page_setup(section_title: str, app_name: str) -> Any:
    """Set the browser tab title and restore the persisted dark-mode preference.

    Call first in every `@ui.page` handler, before `header()`. Returns the `dark` handle
    `header()` needs for its toggle button. Uses `app.storage.user` (server-side), never
    `ui.dark_mode(True)` hardcoded — see @rules/nicegui.md §4 for why (`app.storage.browser`
    reads from localStorage over the websocket, arriving after the render).
    """
    ui.page_title(f"{section_title} — {app_name}")
    return ui.dark_mode(value=ng_app.storage.user.get("dark_mode", True))


def header(
    page_title: str,
    nav: list[NavItem],
    *,
    current: str = "",
    dark: Any = None,
    app_name: str = "",
    extra_actions: Callable[[], None] | None = None,
) -> None:
    """Standard header: page title (left), nav icon buttons minus the active page,
    project-supplied extra actions, dark/light toggle, app name (right)."""
    with ui.header().classes("bg-primary text-white items-center q-px-md q-gutter-sm"):
        ui.label(page_title).classes("text-h6 text-weight-bold col")

        for item in nav:
            if item.label.lower() != current.lower():
                ui.button(icon=item.icon, on_click=lambda p=item.path: ui.navigate.to(p)).props(
                    "flat color=white round"
                ).tooltip(item.label)

        if extra_actions is not None:
            extra_actions()

        if dark is not None:

            def _toggle_dark() -> None:
                dark.toggle()
                ng_app.storage.user["dark_mode"] = dark.value

            ui.button(icon="contrast", on_click=_toggle_dark).props("flat color=white round").tooltip(
                "Tema chiaro/scuro"
            )

        if app_name:
            ui.label(app_name).classes("text-body2").style("opacity:0.6")


def footer(app_name: str, right_content: str = "") -> None:
    """Standard footer: app name (left), optional right-aligned content (auto-refresh
    label slot, version, ...)."""
    with ui.footer().classes("bg-primary text-white q-px-md q-py-xs row items-center"):
        ui.label(app_name).classes("text-caption col").style("opacity:0.6")
        if right_content:
            ui.label(right_content).classes("text-body2 text-weight-bold")


def metric_card(label: str, value: str, color: str = "primary") -> None:
    """Standard metric card: uppercase caption label, bold colored value."""
    with ui.card().classes("q-pa-md col"):
        ui.label(label).classes("text-caption text-grey-6 text-uppercase")
        ui.label(value).classes(f"text-h5 text-weight-bold text-{color}")


@contextmanager
def page(
    title: str,
    *,
    app_name: str,
    nav: list[NavItem],
    current: str = "",
    extra_actions: Callable[[], None] | None = None,
    footer_right: str = "",
    logout: bool = True,
    logout_path: str = "/auth/logout",
) -> Iterator[Any]:
    """`page_setup()` + `header()` + (page body) + `footer()` in one call — the
    per-project `base_layout()`/`@contextmanager` wrapper that mailmanager and ragbot
    each hand-wrote independently, now shared. Usage:

        with page("Dashboard", app_name=APP_NAME, nav=NAV_ITEMS, current="Dashboard"):
            ui.label("content")

    Yields the `dark` handle for the rare page that needs it beyond the header toggle.
    `logout=True` (default) adds the standard logout button alongside any
    `extra_actions` — pass `logout=False` and call `logout_action()` yourself from
    `extra_actions` for a different order/placement.
    """
    dark = page_setup(title, app_name)

    def _actions() -> None:
        if extra_actions is not None:
            extra_actions()
        if logout:
            logout_action(logout_path)

    header(title, nav, current=current, dark=dark, app_name=app_name, extra_actions=_actions)
    yield dark
    footer(app_name, footer_right)
