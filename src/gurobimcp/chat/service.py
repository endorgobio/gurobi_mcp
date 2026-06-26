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


class ChatService:
    def __init__(self, registry: Registry, backend: EnvironmentBackend) -> None:
        self._registry = registry
        self._backend = backend
        self._locks: dict[int, asyncio.Lock] = {}

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
            self._registry.touch(user.id)

        return ChatResponse(
            conversation_id=req.conversation_id,
            agent=agent.value,
            text=turn.text,
            structured=turn.structured,
            output_files=turn.output_files,
            recovered=False,  # transparent recovery arrives with US4
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

        secret = decrypt_secret(user.grb_secret_enc, self._settings.fernet_key)
        handle = await asyncio.to_thread(
            self._manager.start, user.id, user.grb_access_id, secret
        )
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
        env = await self._ensure(user)
        if input_files:
            await asyncio.to_thread(self._write_inputs, env.workspace_path, input_files)
        reply = await env.session.call(
            agent, message, structured, [f.name for f in input_files]
        )
        return AgentTurn(text=reply.text, structured=reply.structured)

    async def stop(self, user_id: int) -> None:
        env = self._registry.environments.pop(user_id, None)
        if env is not None and env.session is not None:
            await env.session.aclose()
        handle = self._handles.pop(user_id, None)
        if handle is not None:
            await asyncio.to_thread(self._manager.stop, handle)


_service: ChatService | None = None


def get_chat_service() -> ChatService:
    """FastAPI dependency returning the process-wide chat service singleton."""
    global _service
    if _service is None:
        registry = Registry()
        _service = ChatService(registry, DockerMCPBackend(registry))
    return _service
