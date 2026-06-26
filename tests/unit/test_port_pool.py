"""Unit tests for the loopback port pool (T018). License-free."""

from __future__ import annotations

import pytest

from gurobimcp.containers.port_pool import CapacityError, PortPool


def test_allocates_within_inclusive_range() -> None:
    pool = PortPool(61100, 61102)
    ports = {pool.allocate(1), pool.allocate(2), pool.allocate(3)}
    assert ports == {61100, 61101, 61102}


def test_exhaustion_raises_capacity_error() -> None:
    pool = PortPool(61100, 61101)
    pool.allocate(1)
    pool.allocate(2)
    with pytest.raises(CapacityError):
        pool.allocate(3)


def test_release_returns_port_for_reuse() -> None:
    pool = PortPool(61100, 61100)
    p = pool.allocate(1)
    pool.release(p)
    assert pool.allocate(2) == p


def test_release_unknown_port_is_safe() -> None:
    pool = PortPool(61100, 61101)
    pool.release(61100)  # never allocated — no error
    assert pool.allocate(1) in (61100, 61101)


def test_in_use_tracking() -> None:
    pool = PortPool(61100, 61101)
    p = pool.allocate(7)
    assert pool.in_use[p] == 7
    pool.release(p)
    assert p not in pool.in_use
