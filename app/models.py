"""Request and response shapes.

The SSE event schema is declared now because the widget will be written against
it long before the graph can emit real steps, and a stub that speaks the final
protocol is worth more than one that has to be rewritten.
"""

from typing import Literal

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    # Groups the turns of one conversation. Becomes the LangGraph checkpointer
    # key in phase 5; carried from the start so the client contract stops moving.
    thread_id: str | None = None


class StepEvent(BaseModel):
    """A thing the agent did, rendered as a chip in the UI while it works."""

    type: Literal["step"] = "step"
    label: str


class TokenEvent(BaseModel):
    type: Literal["token"] = "token"
    text: str


class DoneEvent(BaseModel):
    type: Literal["done"] = "done"
    thread_id: str


class ErrorEvent(BaseModel):
    type: Literal["error"] = "error"
    message: str


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: str
    environment: str
    agent_ready: bool
