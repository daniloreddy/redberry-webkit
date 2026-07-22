from __future__ import annotations

import logging
import re

_REDACTED = "***"

def _kv_pattern(key: str) -> re.Pattern[str]:
    # Matches both bare and quoted values: `key=value`, `key: "value"`, `key='value'`.
    # The quoted alternative must come first so the alternation prefers consuming the
    # surrounding quotes (and therefore the value up to the *matching* quote) instead of
    # falling through to the bare-value branch, which stops at the first quote character.
    return re.compile(rf'(?i)(\b{key}["\']?\s*[:=]\s*)(?:"([^"]*)"|\'([^\']*)\'|([^\s,&"\']+))')


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


class CredentialFilter(logging.Filter):
    """Logging filter that redacts secrets from every record's message before emission."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.args:
            record.msg = redact(record.getMessage())
            record.args = ()
        else:
            record.msg = redact(str(record.msg))
        return True
