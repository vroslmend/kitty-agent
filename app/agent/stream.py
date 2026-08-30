"""Turn a graph run into the events the widget renders.

Yields the event models from `app.models`. It deliberately does not format SSE
frames: that lives in one place in `app/main.py`, because a frame with one
trailing newline instead of two streams nothing and looks like a hang.
"""

import logging
from collections.abc import AsyncIterator

from langchain_core.messages import HumanMessage
from langgraph.types import Command
from pydantic import BaseModel

from app.agent.graph import RECURSION_LIMIT, build_graph
from app.config import Settings
from app.db import get_checkpointer
from app.models import QuestionEvent, StepEvent, TokenEvent

# What the visitor sees while a tool runs. Without these the panel sits blank
# through the slowest part of the answer, which reads as broken.
STEP_LABELS = {
    "search_writing": "reading the writing",
    "list_projects": "looking through the projects",
    "suggest_navigation": "finding the page",
    "get_now_playing": "checking spotify",
    "get_github_activity": "checking github",
}

# The question this one asks is the output the visitor sees. A chip announcing
# that it is about to ask, followed by the question, reads as a stutter.
SILENT_TOOLS = {"ask_clarification"}

BUSY = "too many people are talking to me at once. try again in a minute."
BROKEN = "something went wrong on my end."

log = logging.getLogger(__name__)

_graph = None
_graph_key: tuple | None = None


async def get_graph(settings: Settings):
    """Built once per instance, not once per request.

    Constructing the model client and recompiling the graph on every question
    is pure overhead on a warm instance. Keyed on the settings that change its
    shape so a config change still takes effect.
    """
    global _graph, _graph_key
    key = (settings.llm_model, settings.llm_api_key, bool(settings.database_url))
    if _graph is None or _graph_key != key:
        checkpointer = await get_checkpointer() if settings.database_url else None
        _graph = build_graph(settings, checkpointer=checkpointer)
        _graph_key = key
    return _graph


def is_rate_limited(error: BaseException) -> bool:
    """The provider's own 429, not ours.

    Gemini's free tier allows 15 requests a minute across every visitor at
    once, while our own limit is per client, so two busy visitors can each stay
    inside their allowance and still trip this. It has to read as busy rather
    than broken.
    """
    name = type(error).__name__
    return "RateLimit" in name or "ResourceExhausted" in name or "429" in str(error)


async def run(message: str, thread_id: str, settings: Settings) -> AsyncIterator[BaseModel]:
    graph = await get_graph(settings)
    config = {
        "recursion_limit": RECURSION_LIMIT,
        "configurable": {"thread_id": thread_id},
    }
    # aget_state needs somewhere to have saved state. Without a database the
    # graph is compiled without a checkpointer, and asking it raises.
    remembers = bool(settings.database_url)

    try:
        # A thread that stopped on a question is waiting for an answer, not for
        # another question. Resuming hands the reply back as the paused tool's
        # result; appending it as a new turn would leave the run paused forever
        # and answer nothing.
        paused = (await graph.aget_state(config)).interrupts if remembers else ()
        graph_input = (
            Command(resume=message) if paused else {"messages": [HumanMessage(content=message)]}
        )

        async for event in graph.astream_events(graph_input, config):
            kind = event["event"]
            if kind == "on_tool_start":
                if event["name"] in SILENT_TOOLS:
                    continue
                label = STEP_LABELS.get(event["name"], event["name"].replace("_", " "))
                yield StepEvent(label=label)
            elif kind == "on_chat_model_stream":
                # The deciding turn emits tool-call chunks with no text. Only
                # the answer has any, so an empty string here is not an error.
                if text := getattr(event["data"]["chunk"], "text", ""):
                    yield TokenEvent(text=str(text))

        if remembers:
            for pending in (await graph.aget_state(config)).interrupts:
                yield QuestionEvent(
                    text=pending.value["question"], options=pending.value["options"]
                )
    except Exception as error:  # noqa: BLE001
        # A public endpoint must never show a visitor a traceback, and the
        # napping fallback is for a missing key, not for a failure mid answer.
        # Log it though: a swallowed exception here is a failure nobody can see,
        # and the friendly sentence is identical whatever went wrong.
        log.exception("agent run failed for thread %s", thread_id)
        yield TokenEvent(text=BUSY if is_rate_limited(error) else BROKEN)
