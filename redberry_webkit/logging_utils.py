from __future__ import annotations

import logging
import re

_REDACTED = "***"

def _kv_pattern(key: str) -> re.Pattern[str]:
    # Matches both bare and quoted values: `key=value`, `key: "value"`, `key='value'`.
    # The quoted alternative must come first so the alternation prefers consuming the
    # surrounding quotes (and therefore the value up to the *matching* quote) instead of
    # falling through to the bare-value branch, which stops at the first quote character.
    #
    # Prefix is `(?:\b|_)`, not a bare `\b` — `_` is itself a word character, so a plain
    # `\b` never matches immediately before `key` inside a snake_case identifier like
    # `ui_storage_secret` or `my_secret` (no transition between two word chars). The `_`
    # alternative consumes that underscore explicitly so those still redact. Suffix `s?`
    # matches a pluralized key (e.g. this project's own `API_TOKENS`), which the bare
    # singular `key` alone would miss.
    return re.compile(rf'(?i)((?:\b|_){key}s?["\']?\s*[:=]\s*)(?:"([^"]*)"|\'([^\']*)\'|([^\s,&"\']+))')


_PATTERNS = [_kv_pattern("password"), _kv_pattern("api[_-]?token"), _kv_pattern("secret")]
_BEARER_PATTERN = re.compile(r'(?i)(authorization["\']?\s*[:=]?\s*bearer\s+)([^\s"\']+)')


def _quote_preserving_sub(match: re.Match[str]) -> str:
    # Re-wrap the redaction marker in whichever quote style (or none) the value used,
    # so redacted JSON/log lines stay syntactically valid instead of dropping quotes.
    if match.group(2) is not None:
        return f'{match.group(1)}"{_REDACTED}"'
    if match.group(3) is not None:
        return f"{match.group(1)}'{_REDACTED}'"
    return f"{match.group(1)}{_REDACTED}"


def redact(text: str) -> str:
    """Replace password/token/secret/bearer values (bare or quoted) in text with a redaction marker."""
    redacted = text
    for pattern in _PATTERNS:
        redacted = pattern.sub(_quote_preserving_sub, redacted)
    redacted = _BEARER_PATTERN.sub(lambda m: f"{m.group(1)}{_REDACTED}", redacted)
    return redacted


_traceback_formatter = logging.Formatter()


class CredentialFilter(logging.Filter):
    """Logging filter that redacts secrets from a record's message and exception traceback."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.args:
            record.msg = redact(record.getMessage())
            record.args = ()
        else:
            record.msg = redact(str(record.msg))
        # A record logged with exc_info=True (e.g. logger.exception(...), or explicit
        # exc_info=True) carries a full traceback that Formatter.format() renders
        # verbatim — including any secret value present in the exception's own message
        # (a KeyError on a malformed .env line can echo the raw line back). Format it
        # here (once — logging.Formatter.format() only calls formatException() itself
        # when exc_text is still unset, so pre-populating it here pre-empts that) and
        # redact the result; a second handler sharing this record just re-redacts the
        # already-scrubbed text, which is a no-op.
        if record.exc_info and not record.exc_text:
            record.exc_text = _traceback_formatter.formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = redact(record.exc_text)
        return True
