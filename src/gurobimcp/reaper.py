"""Idle environment reaper (T032).

A background asyncio loop that periodically scans the in-memory registry and
stops every per-user environment idle longer than ``IDLE_TIMEOUT_MINUTES``
(FR-024/035). Stopping is delegated to the chat backend's ``stop`` — which closes
the MCP session, removes the container, and releases the loopback port (FR-026) —
so the reaper holds no Docker knowledge and is fully unit-testable.

Selection reads ``UserEnvironment.last_used_at``, which each turn refreshes via
``Registry.touch`` (FR-023), so activity resets the timer. One slow/failed stop
never aborts the cycle: failures are logged and the loop continues (SC-004).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from gurobimcp.chat.registry import Registry
from gurobimcp.chat.service import EnvironmentBackend
from gurobimcp.config import Settings, get_settings

logger = logging.getLogger("gurobimcp.reaper")


class IdleReaper:
    def __init__(
        self,
        registry: Registry,
        backend: EnvironmentBackend,
        settings: Settings | None = None,
    ) -> None:
        self._registry = registry
        self._backend = backend
        settings = settings or get_settings()
        self._idle_after = timedelta(minutes=settings.idle_timeout_minutes)
        self._interval = settings.reaper_interval_seconds

    def _idle_user_ids(self, now: datetime) -> list[int]:
        cutoff = now - self._idle_after
        # Snapshot before mutating the registry via stop().
        return [
            user_id
            for user_id, env in list(self._registry.environments.items())
            if env.last_used_at < cutoff
        ]

    async def reap_once(self, now: datetime | None = None) -> list[int]:
        """Stop every environment idle past the threshold; return reaped ids."""
        now = now or datetime.now(UTC)
        reaped: list[int] = []
        for user_id in self._idle_user_ids(now):
            try:
                await self._backend.stop(user_id)
            except Exception:  # one bad teardown must not stall the cycle
                logger.warning("Failed to reap environment for user %s", user_id, exc_info=True)
                continue
            reaped.append(user_id)
            logger.info("Reaped idle environment for user %s", user_id)
        return reaped

    async def run(self) -> None:
        """Loop forever, reaping once per interval. Cancellation-safe."""
        logger.info(
            "Idle reaper started (interval=%ss, idle_after=%s)",
            self._interval,
            self._idle_after,
        )
        try:
            while True:
                await asyncio.sleep(self._interval)
                try:
                    await self.reap_once()
                except Exception:  # never let a cycle kill the loop
                    logger.exception("Idle reaper cycle failed")
        except asyncio.CancelledError:
            logger.info("Idle reaper stopped")
            raise
