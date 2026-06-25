"""Logging configuration with a secret-scrubbing filter (T007).

FR-005: Gurobi credentials, passwords, and authorization tokens MUST never be
written to logs. The filter below redacts ``key: value`` / ``key=value`` pairs
whose key looks sensitive, as a defence-in-depth backstop in addition to never
logging such values deliberately.
"""

from __future__ import annotations

import logging
import re

_SENSITIVE_KEYS = (
    "password",
    "secret",
    "token",
    "access_id",
    "authorization",
    "grb_secret",
    "fernet",
)

_KV_PATTERN = re.compile(
    r"(?i)(" + "|".join(re.escape(k) for k in _SENSITIVE_KEYS) + r")"
    r"(\"?\s*[:=]\s*\"?)([^\s,\"'}]+)"
)

REDACTED = "***REDACTED***"


def scrub(text: str) -> str:
    """Replace sensitive values in a string with a redaction marker."""
    return _KV_PATTERN.sub(lambda m: f"{m.group(1)}{m.group(2)}{REDACTED}", text)


class SecretScrubbingFilter(logging.Filter):
    """Redact sensitive values from log records (FR-005)."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = scrub(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {
                    k: (scrub(v) if isinstance(v, str) else v) for k, v in record.args.items()
                }
            else:
                record.args = tuple(
                    scrub(a) if isinstance(a, str) else a for a in record.args
                )
        return True


def configure_logging(level: int = logging.INFO) -> None:
    """Install a stream handler with the secret-scrubbing filter on the root logger."""
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    handler.addFilter(SecretScrubbingFilter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
