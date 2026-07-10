from __future__ import annotations

from redberry_webkit.logging_utils import redact


def test_redact_password() -> None:
    assert redact("login failed password=hunter2") == "login failed password=***"


def test_redact_bearer_token() -> None:
    assert redact("Authorization: Bearer abc.def.ghi") == "Authorization: Bearer ***"


def test_redact_leaves_normal_text_untouched() -> None:
    assert redact("unknown model 'gpt-4' requested, falling back to sonnet") == (
        "unknown model 'gpt-4' requested, falling back to sonnet"
    )
