from __future__ import annotations

import pytest
from nicegui import ui
from nicegui.testing import User

from redberry_webkit.ui import NavItem, footer, header, logout_action, metric_card, page, page_setup


def test_nav_item_is_structurally_a_tuple() -> None:
    # A project's existing bare-tuple `NAV_ITEMS: list[tuple[str, str, str]]` must keep
    # unpacking correctly against the new NamedTuple — no forced migration to
    # `NavItem(...)` call sites required.
    assert NavItem("Dashboard", "dashboard", "/") == ("Dashboard", "dashboard", "/")
    label, icon, path = ("Config", "settings", "/config")
    assert (label, icon, path) == NavItem("Config", "settings", "/config")


async def test_header_hides_current_nav_item_and_shows_others(user: User) -> None:
    nav = [NavItem("Dashboard", "dashboard", "/"), NavItem("Config", "settings", "/config")]

    @ui.page("/")
    def index() -> None:
        header("Dashboard", nav, current="Dashboard")

    await user.open("/")
    await user.should_see("Config")
    # Only the non-current nav item renders a button (no dark toggle, no extra actions).
    assert len(user.find(kind=ui.button).elements) == 1


async def test_header_shows_dark_toggle_only_when_dark_handle_given(user: User) -> None:
    @ui.page("/")
    def index() -> None:
        header("Dashboard", [], current="Dashboard")

    await user.open("/")
    with pytest.raises(AssertionError):
        user.find(kind=ui.button)


async def test_header_dark_toggle_present_with_dark_handle(user: User) -> None:
    @ui.page("/")
    def index() -> None:
        dark = page_setup("Dashboard", "TestApp")
        header("Dashboard", [], current="Dashboard", dark=dark)

    await user.open("/")
    assert len(user.find(kind=ui.button).elements) == 1
    await user.should_see("Tema chiaro/scuro")


async def test_header_renders_extra_actions(user: User) -> None:
    def _extra() -> None:
        ui.button(icon="star").tooltip("Preferiti")

    @ui.page("/")
    def index() -> None:
        header("Dashboard", [], current="Dashboard", extra_actions=_extra)

    await user.open("/")
    await user.should_see("Preferiti")


async def test_header_shows_app_name(user: User) -> None:
    @ui.page("/")
    def index() -> None:
        header("Dashboard", [], current="Dashboard", app_name="MyApp")

    await user.open("/")
    await user.should_see("MyApp")


async def test_footer_shows_app_name_and_right_content(user: User) -> None:
    @ui.page("/")
    def index() -> None:
        footer("MyApp", "v1.2.3")

    await user.open("/")
    await user.should_see("MyApp")
    await user.should_see("v1.2.3")


async def test_footer_without_right_content(user: User) -> None:
    @ui.page("/")
    def index() -> None:
        footer("MyApp")

    await user.open("/")
    await user.should_see("MyApp")


async def test_metric_card_shows_label_and_value(user: User) -> None:
    @ui.page("/")
    def index() -> None:
        metric_card("Richieste totali", "42")

    await user.open("/")
    await user.should_see("Richieste totali")
    await user.should_see("42")


async def test_logout_action_renders_button_with_tooltip(user: User) -> None:
    @ui.page("/")
    def index() -> None:
        logout_action()

    await user.open("/")
    await user.should_see("Esci")


async def test_page_contextmanager_renders_body_header_footer_and_default_logout(user: User) -> None:
    nav = [NavItem("Dashboard", "dashboard", "/")]

    @ui.page("/")
    def index() -> None:
        with page("Dashboard", app_name="MyApp", nav=nav, current="Dashboard", footer_right="v1.0"):
            ui.label("page body")

    await user.open("/")
    await user.should_see("page body")
    await user.should_see("Esci")  # default logout=True
    await user.should_see("v1.0")  # footer_right
    await user.should_see("MyApp")


async def test_page_contextmanager_logout_false_omits_logout_button(user: User) -> None:
    @ui.page("/")
    def index() -> None:
        with page("Dashboard", app_name="MyApp", nav=[], current="Dashboard", logout=False):
            ui.label("page body")

    await user.open("/")
    await user.should_see("page body")
    await user.should_not_see("Esci")
