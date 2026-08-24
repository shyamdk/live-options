from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.services.app_auth import require_auth
from app.services.assistant import ask_assistant

router = APIRouter(prefix="/assistant", tags=["assistant"])

# Caps are generous for a genuine question/reply, just a backstop against an
# accidental giant paste blowing up token cost on a single request -- role is
# restricted to what the frontend ever sends, since a client could otherwise
# smuggle a "system"-role message into the conversation by calling the API
# directly rather than through the chat widget.
MAX_MESSAGE_LENGTH = 4000


class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=MAX_MESSAGE_LENGTH)


class AskIn(BaseModel):
    question: str = Field(max_length=MAX_MESSAGE_LENGTH)
    history: list[Message] = []


@router.post("/ask", dependencies=[Depends(require_auth)])
async def ask(payload: AskIn) -> dict[str, Any]:
    history = [{"role": m.role, "content": m.content} for m in payload.history]
    answer = await ask_assistant(payload.question, history)
    return {"answer": answer}
