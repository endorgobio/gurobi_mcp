"""Persistent MCP client session to a gurobi/mcp container (T026).

Opens one MCP ``ClientSession`` over the streamable-HTTP transport to the
container's loopback port and keeps it alive across turns (FR-011/013). A turn
calls the agent tool (``gurobot``/``explainer``/``modeler``) with a ``prompt``
and optional ``inputFiles``, and relays the agent's reply — text plus any
``structuredContent`` the agent chose to emit — unmodified (FR-016).

Tool API confirmed against the live image: endpoint ``/api/v1/agent/mcp``,
arguments ``prompt`` (required), ``inputFiles`` (``[{path, name}]``, absolute
paths), ``currentDir``. The tools accept no request-side output schema, so
structured output is purely response-side passthrough. The ``mcp`` import is
deferred so this module imports cleanly without the SDK runtime present.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

logger = logging.getLogger("gurobimcp.mcp")

_WORKSPACE = "/workspace"


@dataclass
class AgentReply:
    text: str | None = None
    structured: dict[str, Any] | None = None
    output_files: list[dict[str, Any]] = field(default_factory=list)


class MCPSession:
    """Owns the async context stack for one container's MCP session."""

    def __init__(
        self, host: str, port: int, path: str, startup_timeout: float = 60.0
    ) -> None:
        self._url = f"http://{host}:{port}{path}"
        self._startup_timeout = startup_timeout
        self._session: Any = None
        self._stack: Any = None

    async def connect(self) -> None:
        """Open the transport and initialize the MCP session (readiness)."""
        from contextlib import AsyncExitStack

        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client

        self._stack = AsyncExitStack()
        read, write, _ = await self._stack.enter_async_context(
            streamablehttp_client(self._url, timeout=self._startup_timeout)
        )
        self._session = await self._stack.enter_async_context(ClientSession(read, write))
        await self._session.initialize()
        logger.info("MCP session ready at %s", self._url)

    async def call(
        self,
        agent: str,
        prompt: str,
        structured: bool,
        input_file_names: list[str],
    ) -> AgentReply:
        """Invoke the agent tool and relay its reply unmodified (FR-016).

        Structured output is response-side only: when requested, return the
        agent's ``structuredContent`` if it produced one (the image accepts no
        request-side schema). Callers wanting a particular shape should ask for
        it in ``prompt``.
        """
        if self._session is None:
            raise RuntimeError("MCP session is not connected")
        arguments: dict[str, Any] = {"prompt": prompt, "currentDir": _WORKSPACE}
        if input_file_names:
            arguments["inputFiles"] = [
                {"path": f"{_WORKSPACE}/{name}", "name": name} for name in input_file_names
            ]
        result = await self._session.call_tool(
            agent, arguments, read_timeout_seconds=timedelta(seconds=300)
        )
        text_parts = [
            getattr(block, "text", "")
            for block in (result.content or [])
            if getattr(block, "type", None) == "text"
        ]
        return AgentReply(
            text="\n".join(p for p in text_parts if p) or None,
            structured=result.structuredContent if structured else None,
        )

    async def aclose(self) -> None:
        if self._stack is not None:
            await self._stack.aclose()
            self._stack = None
            self._session = None
