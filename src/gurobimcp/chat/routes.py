"""Chat routes (T028).

POST /chat dispatches a turn to the conversation's bound agent (FR-008/011/012),
starting/recovering the user's environment as needed. POST
/conversations/{id}/end releases a conversation's context (FR-018). Cross-user
access is rejected with 403 (FR-025); all routes require a valid token (FR-007).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status

from gurobimcp.auth.deps import CurrentUser
from gurobimcp.chat.service import ChatService, get_chat_service
from gurobimcp.schemas import ChatRequest, ChatResponse

router = APIRouter(tags=["chat"])

ServiceDep = Annotated[ChatService, Depends(get_chat_service)]


@router.post("/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest, user: CurrentUser, service: ServiceDep) -> ChatResponse:
    return await service.chat(user, payload)


@router.post("/conversations/{conversation_id}/end", status_code=status.HTTP_204_NO_CONTENT)
async def end_conversation(
    conversation_id: str, user: CurrentUser, service: ServiceDep
) -> None:
    await service.end(user, conversation_id)
