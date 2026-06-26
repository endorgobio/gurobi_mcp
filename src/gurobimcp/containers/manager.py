"""Per-user container lifecycle via the Docker SDK (T025).

Starts one isolated ``gurobi/mcp`` container per user, published only on the
loopback interface (FR-033) on a port from the bounded pool (FR-021), with the
user's own decrypted Gurobi credentials (FR-019) and a private workspace mount
(FR-022). The ``docker`` import is deferred so this module imports cleanly on
machines without a Docker daemon (e.g. license-free CI running contract tests).
"""

from __future__ import annotations

import ipaddress
import logging
import os
from dataclasses import dataclass

from gurobimcp.config import Settings, get_settings
from gurobimcp.containers.port_pool import PortPool

logger = logging.getLogger("gurobimcp.containers")


def _assert_loopback(host: str) -> None:
    """Refuse to publish a container anywhere but loopback (FR-033)."""
    try:
        if not ipaddress.ip_address(host).is_loopback:
            raise ValueError
    except ValueError:
        raise RuntimeError(
            f"Refusing to publish container on non-loopback host {host!r}; "
            "every per-user environment MUST bind to loopback only (FR-033)."
        ) from None


@dataclass
class ContainerHandle:
    container_id: str
    port: int
    workspace_path: str


class ContainerManager:
    def __init__(self, settings: Settings | None = None, pool: PortPool | None = None) -> None:
        self._settings = settings or get_settings()
        start, end = self._settings.port_range_bounds
        self._pool = pool or PortPool(start, end)
        self._client: object | None = None

    def _docker(self) -> object:
        if self._client is None:
            import docker  # lazy: only needed when actually starting a container

            self._client = docker.from_env()
        return self._client

    def _workspace_for(self, user_id: int) -> str:
        """Return this user's private workspace, isolated from every other user.

        Each user gets a dedicated ``<workspace_root>/<user_id>`` directory
        (FR-022); 0o700 keeps it unreadable to other users' processes on the host.
        """
        path = os.path.join(os.path.abspath(self._settings.workspace_root), str(user_id))
        os.makedirs(path, mode=0o700, exist_ok=True)
        os.chmod(path, 0o700)  # enforce even if the dir pre-existed with looser perms
        return path

    def start(self, user_id: int, access_id: str, secret: str) -> ContainerHandle:
        """Start the user's container and return its handle (port + workspace)."""
        _assert_loopback(self._settings.loopback_host)
        port = self._pool.allocate(user_id)
        workspace = self._workspace_for(user_id)
        try:
            client = self._docker()
            container = client.containers.run(  # type: ignore[attr-defined]
                self._settings.mcp_image,
                name=f"grbmcp-{user_id}",
                detach=True,
                environment={
                    "GRB_INTELLIGENCE_ACCESS_ID": access_id,
                    "GRB_INTELLIGENCE_SECRET": secret,
                    "GRB_MCP_MOUNT": workspace,
                },
                ports={
                    f"{self._settings.container_port}/tcp": (
                        self._settings.loopback_host,
                        port,
                    )
                },
                volumes={workspace: {"bind": "/workspace", "mode": "rw"}},
                mem_limit=self._settings.container_mem_limit,
            )
        except Exception:
            # Never leak a port if the container failed to start (FR-031).
            self._pool.release(port)
            raise
        logger.info("Started container for user %s on loopback port %s", user_id, port)
        return ContainerHandle(container_id=container.id, port=port, workspace_path=workspace)

    def stop(self, handle: ContainerHandle) -> None:
        """Stop and remove the container and release its port (FR-026)."""
        try:
            client = self._docker()
            container = client.containers.get(handle.container_id)  # type: ignore[attr-defined]
            container.remove(force=True)
        except Exception:  # pragma: no cover - best-effort teardown
            logger.warning("Failed to remove container %s", handle.container_id, exc_info=True)
        finally:
            self._pool.release(handle.port)

    def reconcile(self) -> int:
        """Remove orphan ``grbmcp-*`` containers left by a previous process.

        The live registry is volatile (lost on restart), so any container named
        ``grbmcp-*`` at boot belongs to a dead process and can never be reattached.
        Removing them frees host memory; the fresh ``PortPool`` already starts full,
        so no explicit pool reset is needed. Best-effort: a missing Docker daemon
        (license-free CI) is not an error.
        """
        try:
            client = self._docker()
            containers = client.containers.list(  # type: ignore[attr-defined]
                all=True, filters={"name": "grbmcp-"}
            )
        except Exception:
            logger.warning("Boot reconciliation skipped (Docker unavailable)", exc_info=True)
            return 0
        removed = 0
        for container in containers:
            try:
                container.remove(force=True)
                removed += 1
            except Exception:  # pragma: no cover - best-effort teardown
                logger.warning("Failed to remove orphan container %s", container, exc_info=True)
        if removed:
            logger.info("Boot reconciliation removed %s orphan container(s)", removed)
        return removed

    @property
    def pool(self) -> PortPool:
        return self._pool
