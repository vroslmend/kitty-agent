"""FastAPI entrypoint."""

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from app.agent.stream import run as agent_run
from app.config import get_settings
from app.db import get_pool
from app.models import ChatRequest, DoneEvent, HealthResponse, StepEvent, TokenEvent
from app.ratelimit import ChatRateLimiter, client_key

settings = get_settings()
# Without a database the shared window has nowhere to live, which leaves the
# local one on its own. That is the pre-Neon behaviour, not a relaxation.
limiter = ChatRateLimiter(
    settings.rate_limit_per_minute,
    pool_provider=get_pool if settings.database_url else None,
)

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
log = logging.getLogger(__name__)


def sse(event: BaseModel) -> str:
    # Two trailing newlines, or the client holds the frame waiting for a
    # record separator that never arrives.
    return f"data: {event.model_dump_json()}\n\n"


async def wake_database() -> None:
    try:
        pool = await get_pool()
        async with pool.connection() as connection:
            await connection.execute("SELECT 1")
    except Exception:  # noqa: BLE001
        # A database that cannot be reached is what this is trying to wake, and
        # /health answers about the service either way.
        pass


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    # The portfolio pings this on page load. Vercel and Neon both scale to zero
    # and their cold starts stack, so waking the instance alone leaves half the
    # wait in place. Await the touch so a serverless invocation cannot finish
    # before Neon is ready; the portfolio fires this request without awaiting
    # it, so the visitor can keep reading while the warm-up completes.
    if settings.database_url:
        await wake_database()

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


async def agent_stream(
    message: str, thread_id: str, *, check_for_resume: bool
) -> AsyncIterator[str]:
    async for event in agent_run(
        message,
        thread_id,
        settings,
        check_for_resume=check_for_resume,
    ):
        yield sse(event)
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
    admission_started = time.perf_counter()
    allowed = await limiter.allow(client_key(request))
    admission_ms = round((time.perf_counter() - admission_started) * 1000)
    log.info("chat admission allowed=%s duration_ms=%s", allowed, admission_ms)
    if not allowed:
        return JSONResponse(
            status_code=429,
            content={"type": "error", "message": "too many requests. slow down."},
            headers={"Retry-After": "60"},
        )

    check_for_resume = body.thread_id is not None
    thread_id = body.thread_id or str(uuid.uuid4())
    # An empty key is a supported state, not a misconfiguration, so this falls
    # back rather than failing. It is what keeps a half configured deploy from
    # being what a visitor meets.
    stream = (
        agent_stream(body.message, thread_id, check_for_resume=check_for_resume)
        if settings.agent_ready
        else napping_stream(thread_id)
    )

    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            # Without this a buffering proxy holds the whole stream and
            # delivers it at once, which looks like the agent hanging.
            "X-Accel-Buffering": "no",
        },
    )
