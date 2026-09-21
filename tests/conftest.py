from __future__ import annotations

# `nicegui.testing.plugin` (the usual `pytest_plugins` entry) unconditionally imports
# `screen_plugin`, which requires `selenium` — a real-browser dependency this package
# doesn't otherwise need. `ui.py`'s tests only need the in-process `User` simulation
# (`user_plugin`), not `Screen`, so register that plugin directly instead. See ui.py's
# AGENTS.md note for why.
pytest_plugins = ["nicegui.testing.general_fixtures", "nicegui.testing.user_plugin"]
