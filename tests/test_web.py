from __future__ import annotations

from markupsafe import Markup

from redberry_webkit.web import (
    ASSET_CACHE_CONTROL,
    STATIC_DIR,
    ConfigField,
    FieldType,
    NavItem,
    WebLayout,
    detect_image_content_type,
    icon,
    login_error_message,
    parse_config_form,
    status_badge,
)


def _layout() -> WebLayout:
    return WebLayout(
        "My App",
        [NavItem("Home", "/ui/", icon("home")), NavItem("Log", "/ui/log", icon("list"))],
        extra_head='<link rel="stylesheet" href="/static/app.css">',
        footer_right="v1",
    )


def test_static_dir_ships_app_css() -> None:
    assert (STATIC_DIR / "app.css").is_file()


def test_render_page_marks_current_nav_and_uses_post_logout() -> None:
    html = _layout().render_page("Dashboard", "home", Markup("<p>hi</p>"))

    assert '<span class="nav-link active" title="Home">' in html
    assert '<a class="nav-link" href="/ui/log" title="Log">' in html
    assert '<form method="post" action="/auth/logout"' in html
    assert "<p>hi</p>" in html
    assert '<link rel="stylesheet" href="/static/app.css">' in html
    assert '<span class="footer-right">v1</span>' in html
    assert "<title>Dashboard — My App</title>" in html


def test_plain_str_content_is_escaped() -> None:
    html = _layout().render_page("T", "", "<script>alert(1)</script>")

    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_app_name_and_title_are_escaped() -> None:
    html = WebLayout("<b>x</b>").render_page('"q"', "", Markup(""))

    assert "<b>x</b>" not in html
    assert "&lt;b&gt;x&lt;/b&gt;" in html


def test_logo_and_favicon_flags() -> None:
    html = WebLayout("A", logo=b"<svg/>", favicon=b"<svg/>").render_page("T", "", Markup(""))

    assert 'src="/ui/_assets/logo"' in html
    assert 'href="/ui/_assets/favicon"' in html
    assert 'src="/ui/_assets/logo"' not in WebLayout("A").render_page("T", "", Markup(""))


def test_render_login_shows_error_and_has_no_topbar() -> None:
    html = _layout().render_login("invalid")

    assert "Password errata." in html
    assert 'action="/auth/login"' in html
    assert "topbar" not in html
    assert "Password errata." not in _layout().render_login()


def test_login_error_message_unknown_is_empty() -> None:
    assert login_error_message("nope") == ""
    assert login_error_message("blocked").startswith("Troppi tentativi falliti")


def test_render_config_fields() -> None:
    fields = [
        ConfigField("TZ", "Timezone", help="IANA name"),
        ConfigField("PORT", "Port", type=FieldType.NUMBER),
        ConfigField("DEBUG", "Debug", type=FieldType.BOOL),
        ConfigField("TOKEN", "Token", password=True),
    ]
    html = _layout().render_config(
        fields, {"TZ": "Europe/Rome", "PORT": "8000", "DEBUG": "true", "TOKEN": "***"}, banner="Saved"
    )

    assert 'name="TZ"' in html and 'value="Europe/Rome"' in html
    assert 'type="number"' in html
    assert 'name="DEBUG"' in html and " checked>" in html
    assert 'type="password"' in html and "***" not in html
    assert "IANA name" in html
    assert 'class="banner ok"' in html


def test_render_config_escapes_values() -> None:
    html = _layout().render_config([ConfigField("K", "L")], {"K": '"><script>x</script>'})

    assert "<script>x</script>" not in html


def test_parse_config_form_types() -> None:
    fields = [
        ConfigField("A", "A"),
        ConfigField("N", "N", type=FieldType.NUMBER),
        ConfigField("B", "B", type=FieldType.BOOL),
        ConfigField("P", "P", password=True),
        ConfigField("EMPTY", "E"),
    ]

    updates, error = parse_config_form(fields, {"A": " x ", "N": "5", "B": "on", "P": ""})

    assert error == ""
    assert updates == {"A": "x", "N": "5", "B": "true"}


def test_parse_config_form_unchecked_bool_is_false() -> None:
    updates, error = parse_config_form([ConfigField("B", "B", type=FieldType.BOOL)], {})

    assert error == ""
    assert updates == {"B": "false"}


def test_parse_config_form_non_numeric_rejected() -> None:
    updates, error = parse_config_form([ConfigField("N", "Porta", type=FieldType.NUMBER)], {"N": "abc"})

    assert updates == {}
    assert error == "Valore non numerico per Porta"


def test_status_badge_ok_and_error() -> None:
    assert status_badge("ok") == '<span class="wk-status ok">ok</span>'
    badge = status_badge("error", 'bad "x" <b>')

    assert 'class="wk-status err"' in badge
    assert 'data-error="bad &#34;x&#34; &lt;b&gt;"' in badge
    assert "<b>" not in badge
    assert 'class="wk-status warn"' in status_badge("timeout")


def test_icon_unknown_is_empty() -> None:
    assert icon("nope") == ""
    assert icon("home").startswith("<svg")


def test_logo_only_in_topbar_not_on_login_page() -> None:
    layout = WebLayout("A", logo=b"<svg/>")

    assert 'class="app-logo"' in layout.render_page("T", "", Markup(""))
    assert "app-logo" not in layout.render_login()


def test_detect_image_content_type_shared_format_set() -> None:
    assert detect_image_content_type(bytes.fromhex("89504e470d0a1a0a") + b"x") == "image/png"
    assert detect_image_content_type(bytes.fromhex("ffd8ffe0")) == "image/jpeg"
    assert detect_image_content_type(b"GIF89a...") == "image/gif"
    assert detect_image_content_type(bytes.fromhex("00000100") + b"x") == "image/x-icon"
    assert detect_image_content_type(b"RIFF" + bytes(4) + b"WEBPVP8 ") == "image/webp"
    assert detect_image_content_type(b"<svg></svg>") == "image/svg+xml"
    assert detect_image_content_type(b'<?xml version="1.0"?><svg/>') == "image/svg+xml"
    assert detect_image_content_type("\N{ZERO WIDTH NO-BREAK SPACE}  <svg/>".encode()) == "image/svg+xml"
    assert detect_image_content_type(b"hello") == "application/octet-stream"
    assert detect_image_content_type(b"") == "application/octet-stream"


def test_layout_asset_lookup() -> None:
    layout = WebLayout("A", logo=b"<svg/>")

    assert layout.asset("logo") == (b"<svg/>", "image/svg+xml")
    assert layout.asset("favicon") is None
    assert layout.asset("other") is None
    assert ASSET_CACHE_CONTROL == "public, max-age=86400"
