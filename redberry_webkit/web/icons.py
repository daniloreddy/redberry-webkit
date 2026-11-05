from __future__ import annotations

from markupsafe import Markup

_ATTRS = (
    'width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
    'stroke-width="2" stroke-linecap="round" stroke-linejoin="round"'
)

_PATHS: dict[str, str] = {
    "home": '<path d="M3 10.5 12 3l9 7.5"/><path d="M5 9.5V21h14V9.5"/><path d="M9 21v-6h6v6"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/>',
    "chip": (
        '<rect x="7" y="7" width="10" height="10" rx="1"/>'
        '<path d="M9 1v3M15 1v3M9 20v3M15 20v3M1 9h3M1 15h3M20 9h3M20 15h3M10 10h4v4h-4z"/>'
    ),
    "sliders": '<path d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M1 14h6M9 8h6M17 16h6"/>',
    "list": '<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>',
    "chart": '<path d="M3 3v18h18"/><path d="M7 15l4-4 3 3 5-6"/>',
    "gauge": '<path d="M12 14 8 9"/><path d="M4 20a8 8 0 1 1 16 0"/>',
    "bell": '<path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.7 21a2 2 0 0 1-3.4 0"/>',
}


def icon(name: str) -> Markup:
    """Return the built-in inline-SVG icon `name` for use as `NavItem.icon`, or empty markup if unknown."""
    path = _PATHS.get(name)
    if path is None:
        return Markup("")
    return Markup(f"<svg {_ATTRS}>{path}</svg>")
