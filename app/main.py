"""FastAPI entrypoint.

Phase 0: health, CORS, and a /chat endpoint that already speaks SSE but has no
agent behind it yet. Streaming the placeholder rather than returning plain JSON
means the transport is proven before the graph lands, so phase 4 only has to
swap what produces the events.
"""

import asyncio
import uuid
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.config import get_settings
from app.models import ChatRequest, DoneEvent, HealthResponse, StepEvent, TokenEvent

settings = get_settings()

app = FastAPI(
    title="kitty",
    description="On-site agent for ammarhassan.dev.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

NAPPING = "kitty's napping right now. try again in a bit."


def sse(event: BaseModel) -> str:
    """Serialise one pydantic event as an SSE frame.

    Two trailing newlines, or the client buffers the frame forever waiting for
    the record separator.
    """
    return f"data: {event.model_dump_json()}\n\n"


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Liveness probe. Container hosts poll this to decide if a deploy came up."""
    return HealthResponse(
        service=settings.app_name,
        environment=settings.environment,
        agent_ready=settings.agent_ready,
    )


async def napping_stream(thread_id: str) -> AsyncIterator[str]:
    yield sse(StepEvent(label="waking up"))
    await asyncio.sleep(0)
    yield sse(TokenEvent(text=NAPPING))
    yield sse(DoneEvent(thread_id=thread_id))


@app.post("/chat")
async def chat(request: ChatRequest) -> StreamingResponse:
    """Streams the agent's steps and answer.

    No graph yet, so every request gets the napping fallback. The shape of the
    response is final.
    """
    thread_id = request.thread_id or str(uuid.uuid4())

    return StreamingResponse(
        napping_stream(thread_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # stops nginx-style proxies buffering the stream
        },
    )
