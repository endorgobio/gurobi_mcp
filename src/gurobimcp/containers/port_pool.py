"""Loopback port pool (T022).

Hands out ports from the bounded inclusive range (default 61100–61200, FR-021).
Allocation is the concurrency bound for active environments (SC-008): when the
pool is empty, ``allocate`` raises ``CapacityError`` so callers can return a
503 rather than crashing.
"""

from __future__ import annotations

import threading


class CapacityError(Exception):
    """Raised when no port is available in the pool."""


class PortPool:
    def __init__(self, start: int, end: int) -> None:
        if start > end:
            raise ValueError("start must be <= end")
        self._available: list[int] = list(range(start, end + 1))
        self.in_use: dict[int, int] = {}
        self._lock = threading.Lock()

    def allocate(self, user_id: int) -> int:
        """Reserve and return a free port for ``user_id`` (FR-021)."""
        with self._lock:
            if not self._available:
                raise CapacityError("No free port in the pool (capacity reached)")
            port = self._available.pop(0)
            self.in_use[port] = user_id
            return port

    def release(self, port: int) -> None:
        """Return a port to the pool; releasing an unknown port is a no-op."""
        with self._lock:
            if port in self.in_use:
                del self.in_use[port]
                self._available.append(port)
                self._available.sort()

    @property
    def free_count(self) -> int:
        with self._lock:
            return len(self._available)
