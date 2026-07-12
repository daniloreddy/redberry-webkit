from __future__ import annotations

import logging

from redberry_webkit.logging_utils import CredentialFilter, redact


def test_redact_password() -> None:
    assert redact("login failed password=hunter2") == "login failed password=***"


def test_redact_bearer_token() -> None:
    assert redact("Authorization: Bearer abc.def.ghi") == "Authorization: Bearer ***"


def test_redact_api_token() -> None:
    assert redact("api_token=sk-abc123") == "api_token=***"


def test_redact_secret() -> None:
    assert redact("secret: topsecret123") == "secret: ***"


def test_redact_json_quoted_password() -> None:
    assert redact('{"password": "s3cret"}') == '{"password": "***"}'


def test_redact_json_quoted_secret_single_quotes() -> None:
    assert redact("{'secret': 'topsecret'}") == "{'secret': '***'}"


def test_redact_leaves_normal_text_untouched() -> None:
    assert redact("unknown model 'gpt-4' requested, falling back to sonnet") == (
        "unknown model 'gpt-4' requested, falling back to sonnet"
    )


def _make_record(msg: str, args: tuple[object, ...] = ()) -> logging.LogRecord:
    return logging.LogRecord(
        name="test", level=logging.INFO, pathname=__file__, lineno=1, msg=msg, args=args, exc_info=None
    )


def test_credential_filter_redacts_plain_message() -> None:
    record = _make_record("login failed password=hunter2")
    assert CredentialFilter().filter(record) is True
    assert record.msg == "login failed password=***"


def test_credential_filter_redacts_message_with_args() -> None:
    record = _make_record("login failed password=%s", ("hunter2",))
    assert CredentialFilter().filter(record) is True
    assert record.msg == "login failed password=***"
    assert record.args == ()
