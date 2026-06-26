"""Per-user container lifecycle via the Docker SDK (T025).

Starts one isolated ``gurobi/mcp`` container per user, published only on the
loopback interface (FR-033) on a port from the bounded pool (FR-021), with the
user's own decrypted Gurobi credentials (FR-019) and a private workspace mount
(FR-022). The ``docker`` import is deferred so this module imports cleanly on
machines without a Docker daemon (e.g. license-free CI running contract tests).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from gurobimcp.config import Settings, get_settings
from gurobimcp.containers.port_pool import PortPool

logger = logging.getLogger("gurobimcp.containers")


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
        path = os.path.join(os.path.abspath(self._settings.workspace_root), str(user_id))
        os.makedirs(path, exist_ok=True)
        return path

    def start(self, user_id: int, access_id: str, secret: str) -> ContainerHandle:
        """Start the user's container and return its handle (port + workspace)."""
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

    @property
    def pool(self) -> PortPool:
        return self._pool
