from __future__ import annotations

import logging
import re

_REDACTED = "***"

_PATTERNS = [
    re.compile(r'(?i)(password["\']?\s*[:=]\s*)([^\s,&"\']+)'),
    re.compile(r'(?i)(api[_-]?token["\']?\s*[:=]\s*)([^\s,&"\']+)'),
    re.compile(r'(?i)(authorization["\']?\s*[:=]?\s*bearer\s+)([^\s"\']+)'),
    re.compile(r'(?i)(secret["\']?\s*[:=]\s*)([^\s,&"\']+)'),
]


def redact(text: str) -> str:
    """Replace password/token/secret/bearer values in text with a redaction marker."""
    redacted = text
    for pattern in _PATTERNS:
        redacted = pattern.sub(lambda m: f"{m.group(1)}{_REDACTED}", redacted)
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
