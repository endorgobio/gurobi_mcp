"""Chat service: binding, serialization, and turn dispatch (T027).

``ChatService`` owns the conversation/agent-binding rules and per-user
serialization (one active conversation per environment, FR-029) and delegates
the actual "start container + call agent" work to an injected
``EnvironmentBackend``. The real backend (``DockerMCPBackend``) drives Docker +
MCP; contract tests inject a fake, so binding/validation/error semantics are
testable without any Docker or Intelligence Hub access.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
from dataclasses import dataclass, field
from typing import Protocol

from gurobimcp.chat.registry import (
    Agent,
    AgentConflict,
    ConversationForbidden,
    ConversationNotFound,
    Registry,
    UserEnvironment,
)
from gurobimcp.config import Settings, get_settings
from gurobimcp.errors import AppError
from gurobimcp.models import User
from gurobimcp.schemas import ChatRequest, ChatResponse, FileRef

logger = logging.getLogger("gurobimcp.chat")


@dataclass
class AgentTurn:
    text: str | None = None
    structured: dict[str, object] | None = None
    output_files: list[FileRef] = field(default_factory=list)
    # True when the backend had to (re)provision the environment to serve this
    # turn — either it was missing (reaped) or its session had gone stale. The
    # service decides whether that counts as a recovery (US4 / FR-027/028).
    provisioned: bool = False


class EnvironmentBackend(Protocol):
    """Provides per-user environments and dispatches a turn to the agent."""

    async def send_turn(
        self,
        user: User,
        agent: str,
        message: str,
        structured: bool,
        input_files: list[FileRef],
    ) -> AgentTurn: ...

    async def stop(self, user_id: int) -> None: ...

    async def reconcile(self) -> int:
        """Remove orphan environments left by a previous process (boot-time)."""
        ...


class ChatService:
    def __init__(self, registry: Registry, backend: EnvironmentBackend) -> None:
        self._registry = registry
        self._backend = backend
        self._locks: dict[int, asyncio.Lock] = {}

    @property
    def registry(self) -> Registry:
        return self._registry

    @property
    def backend(self) -> EnvironmentBackend:
        return self._backend

    def _lock(self, user_id: int) -> asyncio.Lock:
        lock = self._locks.get(user_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[user_id] = lock
        return lock

    async def chat(self, user: User, req: ChatRequest) -> ChatResponse:
        try:
            agent = Agent(req.agent)
        except ValueError as exc:
            raise AppError(
                f"Unknown agent '{req.agent}'", status_code=400, code="invalid_agent"
            ) from exc

        # Capture whether this thread already existed *before* we bind it, so a
        # transparent re-provision of an active thread can be flagged as a
        # recovery while a genuine first message is not (FR-027/028).
        pre_existed = self._registry.has_active_conversation(req.conversation_id, user.id)

        try:
            self._registry.bind_or_get(req.conversation_id, user.id, agent)
        except ConversationForbidden as exc:
            raise AppError(
                "Conversation belongs to another user", status_code=403, code="forbidden"
            ) from exc
        except AgentConflict as exc:
            raise AppError(str(exc), status_code=400, code="agent_conflict") from exc

        # Serialize turns per user: one active conversation per environment (FR-029).
        async with self._lock(user.id):
            turn = await self._backend.send_turn(
                user,
                agent.value,
                req.message,
                req.structured,
                req.input_files,
            )
            # Record the most-recent interaction so the idle reaper sees activity
            # and resets the timer (FR-023). Done under the lock, after a
            # successful turn, so last_used_at reflects real progress.
            self._registry.touch(user.id)

        # A recovery is an already-active thread whose environment had to be
        # rebuilt this turn; a cold start of a brand-new thread is not (FR-028).
        recovered = pre_existed and turn.provisioned

        return ChatResponse(
            conversation_id=req.conversation_id,
            agent=agent.value,
            text=turn.text,
            structured=turn.structured,
            output_files=turn.output_files,
            recovered=recovered,
        )

    async def end(self, user: User, conversation_id: str) -> None:
        try:
            self._registry.end(conversation_id, user.id)
        except ConversationForbidden as exc:
            raise AppError(
                "Conversation belongs to another user", status_code=403, code="forbidden"
            ) from exc
        except ConversationNotFound as exc:
            raise AppError("Unknown conversation", status_code=404, code="not_found") from exc


class DockerMCPBackend:
    """Real backend: one gurobi/mcp container + persistent MCP session per user."""

    def __init__(self, registry: Registry, settings: Settings | None = None) -> None:
        from gurobimcp.containers.manager import ContainerHandle, ContainerManager

        self._registry = registry
        self._settings = settings or get_settings()
        self._manager = ContainerManager(self._settings)
        self._handles: dict[int, ContainerHandle] = {}

    async def _ensure(self, user: User) -> UserEnvironment:
        env = self._registry.environments.get(user.id)
        if env is not None:
            return env

        from gurobimcp.auth.security import decrypt_secret
        from gurobimcp.containers.mcp_client import MCPSession
        from gurobimcp.containers.port_pool import CapacityError

        secret = decrypt_secret(user.grb_secret_enc, self._settings.fernet_key)
        try:
            handle = await asyncio.to_thread(
                self._manager.start, user.id, user.grb_access_id, secret
            )
        except CapacityError as exc:
            # Port pool exhausted: no partial resources were allocated (allocate
            # fails first). Surface a clear retryable error (FR-031, SC-008).
            raise AppError(
                "The service is at capacity; please try again shortly",
                status_code=503,
                code="capacity_reached",
            ) from exc
        session = MCPSession(
            self._settings.loopback_host, handle.port, self._settings.mcp_path
        )
        try:
            await session.connect()
        except Exception as exc:
            await asyncio.to_thread(self._manager.stop, handle)
            raise AppError(
                "Could not start the optimization environment",
                status_code=424,
                code="environment_unavailable",
            ) from exc
        self._handles[user.id] = handle
        env = UserEnvironment(
            user_id=user.id,
            container_id=handle.container_id,
            port=handle.port,
            workspace_path=handle.workspace_path,
            session=session,
        )
        self._registry.environments[user.id] = env
        return env

    def _write_inputs(self, workspace: str, input_files: list[FileRef]) -> None:
        for f in input_files:
            if f.content_base64:
                with open(os.path.join(workspace, f.name), "wb") as fh:
                    fh.write(base64.b64decode(f.content_base64))

    async def send_turn(
        self,
        user: User,
        agent: str,
        message: str,
        structured: bool,
        input_files: list[FileRef],
    ) -> AgentTurn:
        # provisioned if there was no live environment when the turn began (cold
        # start after first message, or after the reaper reclaimed it — FR-030).
        provisioned = user.id not in self._registry.environments
        env = await self._ensure(user)
        if input_files:
            await asyncio.to_thread(self._write_inputs, env.workspace_path, input_files)
        try:
            reply = await env.session.call(
                agent, message, structured, [f.name for f in input_files]
            )
        except Exception:
            # The environment was registered but its session/container is dead
            # (e.g. reclaimed externally). Tear it down, rebuild, and retry once
            # with fresh context (FR-027). A clean cold start above will not hit
            # this path; only a stale live session does.
            logger.warning(
                "Session call failed for user %s; rebuilding and retrying", user.id,
                exc_info=True,
            )
            await self.stop(user.id)
            env = await self._ensure(user)
            provisioned = True
            if input_files:
                await asyncio.to_thread(self._write_inputs, env.workspace_path, input_files)
            try:
                reply = await env.session.call(
                    agent, message, structured, [f.name for f in input_files]
                )
            except Exception as exc:
                # Even a fresh environment could not serve the turn — surface a
                # clear, non-internal error rather than a stack trace (FR-031).
                raise AppError(
                    "The optimization agent is currently unavailable",
                    status_code=502,
                    code="agent_unavailable",
                ) from exc
        return AgentTurn(
            text=reply.text, structured=reply.structured, provisioned=provisioned
        )

    async def stop(self, user_id: int) -> None:
        env = self._registry.environments.pop(user_id, None)
        if env is not None and env.session is not None:
            await env.session.aclose()
        handle = self._handles.pop(user_id, None)
        if handle is not None:
            await asyncio.to_thread(self._manager.stop, handle)

    async def reconcile(self) -> int:
        """Remove orphan containers from a previous process (boot-time, FR-026)."""
        return await asyncio.to_thread(self._manager.reconcile)


_service: ChatService | None = None


def get_chat_service() -> ChatService:
    """FastAPI dependency returning the process-wide chat service singleton."""
    global _service
    if _service is None:
        registry = Registry()
        _service = ChatService(registry, DockerMCPBackend(registry))
    return _service
