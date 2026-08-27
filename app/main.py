"""FastAPI entrypoint."""

import asyncio
import uuid
from collections.abc import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from app.config import get_settings
from app.models import ChatRequest, DoneEvent, HealthResponse, StepEvent, TokenEvent
from app.ratelimit import RateLimiter, client_key

settings = get_settings()
limiter = RateLimiter(settings.rate_limit_per_minute)

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
    # Two trailing newlines, or the client holds the frame waiting for a
    # record separator that never arrives.
    return f"data: {event.model_dump_json()}\n\n"


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
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


# response_model=None because the return type is a union of two Response
# classes, which FastAPI would otherwise try to turn into a Pydantic model.
@app.post("/chat", response_model=None)
async def chat(body: ChatRequest, request: Request) -> StreamingResponse | JSONResponse:
    """Streams the agent's steps and its answer as server sent events.

    Rate limited before anything else runs. Once a model sits behind this, a
    request costs real money and the endpoint is public and unauthenticated,
    so the limit is the only thing between an abusive client and the bill.
    /health is deliberately not limited, or the platform's own probes would
    consume the allowance.
    """
    if not limiter.allow(client_key(request)):
        return JSONResponse(
            status_code=429,
            content={"type": "error", "message": "too many requests. slow down."},
            headers={"Retry-After": "60"},
        )

    thread_id = body.thread_id or str(uuid.uuid4())

    return StreamingResponse(
        napping_stream(thread_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            # Without this a buffering proxy holds the whole stream and
            # delivers it at once, which looks like the agent hanging.
            "X-Accel-Buffering": "no",
        },
    )
