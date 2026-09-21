from __future__ import annotations

import logging
import sys

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


def test_redact_secret_suffix_of_snake_case_identifier() -> None:
    # ui_storage_secret is redberry_webkit's own AuthManager field name — a plain \b
    # prefix misses it, since `_` is a word char and creates no boundary before "secret".
    assert redact('ui_storage_secret: "abc123"') == 'ui_storage_secret: "***"'
    assert redact("my_secret=abc123") == "my_secret=***"


def test_redact_plural_api_tokens() -> None:
    # API_TOKENS (plural) is this ecosystem's own config key name.
    assert redact("API_TOKENS=abc123def456") == "API_TOKENS=***"


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


def _make_record_with_exc_info(exc: Exception, msg: str = "failed") -> logging.LogRecord:
    try:
        raise exc
    except type(exc):
        return logging.LogRecord(
            name="test", level=logging.ERROR, pathname=__file__, lineno=1, msg=msg, args=(), exc_info=sys.exc_info()
        )


def test_credential_filter_redacts_exception_traceback() -> None:
    record = _make_record_with_exc_info(ValueError("API_TOKENS=abc123def456 rejected"))
    assert CredentialFilter().filter(record) is True
    assert record.exc_text is not None
    assert "abc123def456" not in record.exc_text
    assert "API_TOKENS=***" in record.exc_text


def test_credential_filter_idempotent_across_multiple_handlers() -> None:
    # Simulates the record being shared across two handlers (see app/main.py: one
    # CredentialFilter instance per handler, same LogRecord passed to both).
    record = _make_record_with_exc_info(ValueError("secret=hunter2"))
    assert CredentialFilter().filter(record) is True
    first_pass = record.exc_text
    assert CredentialFilter().filter(record) is True
    assert record.exc_text == first_pass
    assert "hunter2" not in (record.exc_text or "")
