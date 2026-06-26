"""Structured application errors (extracted from main for reuse).

Carries an HTTP status and a stable error code so handlers can render a
consistent ``{"detail", "code"}`` body (see the handler in main.py).
"""

from __future__ import annotations


class AppError(Exception):
    """Base application error carrying an HTTP status and a stable error code."""

    def __init__(
        self, detail: str, *, status_code: int = 400, code: str = "bad_request"
    ) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code
        self.code = code
