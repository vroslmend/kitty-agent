"""Request and response shapes for the chat endpoint."""

from typing import Literal

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    thread_id: str | None = None


class StepEvent(BaseModel):
    """A thing the agent did, rendered as a chip in the UI while it works."""

    type: Literal["step"] = "step"
    label: str


class TokenEvent(BaseModel):
    type: Literal["token"] = "token"
    text: str


class QuestionEvent(BaseModel):
    """The agent stopped to ask which of several things was meant.

    The turn ends on this rather than on an answer. The visitor's next message
    on the same thread_id is the reply, and it resumes the paused run.
    """

    type: Literal["question"] = "question"
    text: str
    options: list[str] = Field(default_factory=list)


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
