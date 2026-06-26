"""Unit tests for the idle reaper (T030). License-free.

Exercises idle-selection and port-release without Docker or MCP: the registry is
populated directly and a fake backend mirrors ``DockerMCPBackend.stop`` (pop the
environment, release its port). Covers FR-023 (activity resets the timer) and
FR-024/026 (idle environments stopped, resources released).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from gurobimcp.chat.registry import Registry, UserEnvironment
from gurobimcp.config import Settings
from gurobimcp.containers.port_pool import PortPool
from gurobimcp.reaper import IdleReaper


class FakeReapBackend:
    """Mirrors DockerMCPBackend.stop: drops the env and frees its port."""

    def __init__(self, registry: Registry, pool: PortPool) -> None:
        self._registry = registry
        self._pool = pool
        self.stopped: list[int] = []

    async def send_turn(self, *args: object, **kwargs: object) -> object:  # pragma: no cover
        raise NotImplementedError

    async def stop(self, user_id: int) -> None:
        env = self._registry.environments.pop(user_id, None)
        if env is not None:
            self._pool.release(env.port)
        self.stopped.append(user_id)


def _settings(idle_minutes: int = 15) -> Settings:
    return Settings(
        fernet_key="", jwt_secret="x", idle_timeout_minutes=idle_minutes
    )


def _add_env(registry: Registry, pool: PortPool, user_id: int, age_minutes: float) -> None:
    port = pool.allocate(user_id)
    registry.environments[user_id] = UserEnvironment(
        user_id=user_id,
        container_id=f"cid-{user_id}",
        port=port,
        workspace_path=f"/ws/{user_id}",
        last_used_at=datetime.now(UTC) - timedelta(minutes=age_minutes),
    )


async def test_reaps_only_idle_environments() -> None:
    registry, pool = Registry(), PortPool(61100, 61102)
    _add_env(registry, pool, user_id=1, age_minutes=30)  # idle
    _add_env(registry, pool, user_id=2, age_minutes=1)  # fresh
    backend = FakeReapBackend(registry, pool)
    reaper = IdleReaper(registry, backend, _settings(idle_minutes=15))

    reaped = await reaper.reap_once()

    assert reaped == [1]
    assert backend.stopped == [1]
    assert 1 not in registry.environments
    assert 2 in registry.environments


async def test_reaping_releases_the_port() -> None:
    registry, pool = Registry(), PortPool(61100, 61100)  # single slot
    _add_env(registry, pool, user_id=1, age_minutes=30)
    assert pool.free_count == 0
    backend = FakeReapBackend(registry, pool)
    reaper = IdleReaper(registry, backend, _settings(idle_minutes=15))

    await reaper.reap_once()

    assert pool.free_count == 1  # port returned for reuse (FR-024)
    assert pool.allocate(2) == 61100


async def test_no_idle_environments_is_a_noop() -> None:
    registry, pool = Registry(), PortPool(61100, 61102)
    _add_env(registry, pool, user_id=1, age_minutes=2)
    backend = FakeReapBackend(registry, pool)
    reaper = IdleReaper(registry, backend, _settings(idle_minutes=15))

    assert await reaper.reap_once() == []
    assert backend.stopped == []
    assert 1 in registry.environments


async def test_activity_resets_the_idle_timer() -> None:
    """A touch() (FR-023) before a cycle keeps an otherwise-idle env alive."""
    registry, pool = Registry(), PortPool(61100, 61102)
    _add_env(registry, pool, user_id=1, age_minutes=30)
    registry.touch(1)  # most-recent interaction is now
    backend = FakeReapBackend(registry, pool)
    reaper = IdleReaper(registry, backend, _settings(idle_minutes=15))

    assert await reaper.reap_once() == []
    assert 1 in registry.environments


async def test_reap_continues_when_one_stop_fails() -> None:
    registry, pool = Registry(), PortPool(61100, 61102)
    _add_env(registry, pool, user_id=1, age_minutes=30)
    _add_env(registry, pool, user_id=2, age_minutes=30)

    class FlakyBackend(FakeReapBackend):
        async def stop(self, user_id: int) -> None:
            if user_id == 1:
                raise RuntimeError("docker hiccup")
            await super().stop(user_id)

    backend = FlakyBackend(registry, pool)
    reaper = IdleReaper(registry, backend, _settings(idle_minutes=15))

    reaped = await reaper.reap_once()

    assert reaped == [2]  # user 1 failed but did not abort the cycle
    assert 2 not in registry.environments
