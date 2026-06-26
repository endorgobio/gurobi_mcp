"""Persistent MCP client session to a gurobi/mcp container (T026).

Opens one MCP ``ClientSession`` over the streamable-HTTP transport to the
container's loopback port and keeps it alive across turns (FR-011/013). A turn
calls the agent tool (``gurobot``/``explainer``/``modeler``) with a ``prompt``
and optional ``inputFiles``, and relays the agent's reply — text plus any
``structuredContent`` the agent chose to emit — unmodified (FR-016).

The session's transport + ``ClientSession`` are owned by a single dedicated
**runner task** (``_serve``): it enters the async-with stack, initializes, then
serves call requests off a queue until closed. This matters because the MCP/anyio
transport binds its cancel scope to the task that opened it and requires LIFO
teardown — opening on the main task and closing many per-user sessions out of
order (e.g. the idle reaper stopping one user while another stays live) raises
"attempted to exit a cancel scope that isn't the current task's". Confining each
session's whole lifecycle to its own task makes sessions independent and safe to
close in any order.

Tool API confirmed against the live image: endpoint ``/api/v1/agent/mcp``,
arguments ``prompt`` (required), ``inputFiles`` (``[{path, name}]``, absolute
paths), ``currentDir``. The tools accept no request-side output schema, so
structured output is purely response-side passthrough. The ``mcp`` import is
deferred so this module imports cleanly without the SDK runtime present.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

logger = logging.getLogger("gurobimcp.mcp")

_WORKSPACE = "/workspace"
_RETRY_INTERVAL = 0.5


@dataclass
class AgentReply:
    text: str | None = None
    structured: dict[str, Any] | None = None
    output_files: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class _Call:
    agent: str
    arguments: dict[str, Any]
    future: asyncio.Future[Any]


class MCPSession:
    """One container's MCP session, driven by a dedicated runner task."""

    def __init__(
        self, host: str, port: int, path: str, startup_timeout: float = 60.0
    ) -> None:
        self._url = f"http://{host}:{port}{path}"
        self._startup_timeout = startup_timeout
        self._calls: asyncio.Queue[_Call | None] = asyncio.Queue()
        self._ready = asyncio.Event()
        self._error: Exception | None = None
        self._runner: asyncio.Task[None] | None = None

    async def connect(self) -> None:
        """Start the runner task and wait until the session is serving (readiness).

        A freshly ``docker run`` container is detached and not yet listening when
        start returns; the runner retries the initialize handshake until it
        succeeds or ``startup_timeout`` elapses (SC-001 cold start). Raises the
        startup error if the container never becomes ready.
        """
        self._runner = asyncio.create_task(self._serve())
        await self._ready.wait()
        if self._error is not None:
            await self._await_runner()
            raise self._error

    async def _serve(self) -> None:
        """Own the transport + session for this container's whole lifetime."""
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client

        deadline = time.monotonic() + self._startup_timeout
        attempt = 0
        try:
            while True:
                attempt += 1
                try:
                    async with streamablehttp_client(
                        self._url, timeout=self._startup_timeout
                    ) as (read, write, _):
                        async with ClientSession(read, write) as session:
                            await session.initialize()
                            logger.info(
                                "MCP session ready at %s after %d attempt(s)",
                                self._url,
                                attempt,
                            )
                            self._ready.set()
                            await self._dispatch(session)
                    return
                except Exception:
                    # Once serving, any failure is fatal for this session; before
                    # readiness it just means the container is not up yet — retry.
                    if self._ready.is_set() or time.monotonic() >= deadline:
                        raise
                    await asyncio.sleep(_RETRY_INTERVAL)
        except Exception as exc:  # startup or in-flight transport failure
            self._error = exc
            self._ready.set()  # unblock a waiting connect()

    async def _dispatch(self, session: Any) -> None:
        """Serve queued calls on the session's own task until closed."""
        while True:
            call = await self._calls.get()
            if call is None:  # close sentinel
                return
            try:
                result = await session.call_tool(
                    call.agent, call.arguments, read_timeout_seconds=timedelta(seconds=300)
                )
            except Exception as exc:
                if not call.future.done():
                    call.future.set_exception(exc)
            else:
                if not call.future.done():
                    call.future.set_result(result)

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
        if self._runner is None or self._error is not None:
            raise RuntimeError("MCP session is not connected")
        arguments: dict[str, Any] = {"prompt": prompt, "currentDir": _WORKSPACE}
        if input_file_names:
            arguments["inputFiles"] = [
                {"path": f"{_WORKSPACE}/{name}", "name": name} for name in input_file_names
            ]
        future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        await self._calls.put(_Call(agent, arguments, future))
        result = await future
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
        """Signal the runner to exit and wait for it to tear down its session."""
        if self._runner is None:
            return
        await self._calls.put(None)
        await self._await_runner()

    async def _await_runner(self) -> None:
        runner, self._runner = self._runner, None
        if runner is None:
            return
        with contextlib.suppress(Exception):
            await runner
