from __future__ import annotations

from markupsafe import Markup, escape


def status_class(status: str) -> str:
    """Map a raw status text to the `.wk-status` modifier: `ok`, `err` or `warn`."""
    if status in ("ok", "success"):
        return "ok"
    if status in ("error", "failed"):
        return "err"
    return "warn"


def status_badge(status: str, error_message: str = "") -> Markup:
    """Render the standard request-table status pill; an error also carries `title`/`data-error` for the popover."""
    css = status_class(status)
    label = escape(status)
    if not error_message:
        return Markup('<span class="wk-status {}">{}</span>').format(css, label)
    return Markup('<span class="wk-status {}" role="button" tabindex="0" title="{}" data-error="{}">{}</span>').format(
        css, error_message, error_message, label
    )
