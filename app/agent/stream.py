"""Turn a graph run into the events the widget renders.

Yields the event models from `app.models`. It deliberately does not format SSE
frames: that lives in one place in `app/main.py`, because a frame with one
trailing newline instead of two streams nothing and looks like a hang.
"""

import json
import logging
import re
import time
from collections.abc import AsyncIterator

from langchain_core.messages import HumanMessage
from langgraph.types import Command
from pydantic import BaseModel

from app.agent.graph import RECURSION_LIMIT, build_graph
from app.agent.prompts import NEVER_SPEAK
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
TANGLED = "that came out wrong. ask me again?"
EMPTY = "nothing came back that time. ask me again?"

# Hold this much of the answer back before releasing any of it. A leak is a
# whole-answer event that is recognisable from its opening words, so checking
# the head catches it while the rest still streams. It delays the first token
# on short answers; the step labels, which are the part worth watching, are
# unaffected.
LEAK_GUARD_CHARS = 160

# Long enough that ordinary phrasing cannot collide by accident, short enough
# that a leak cannot slip through by rewording an edge.
LEAK_RUN_WORDS = 8

log = logging.getLogger(__name__)


def _runs(text: str, n: int = LEAK_RUN_WORDS) -> set[tuple[str, ...]]:
    words = re.findall(r"[a-z0-9']+", text.lower())
    return {tuple(words[i : i + n]) for i in range(len(words) - n + 1)}


_FORBIDDEN = _runs(NEVER_SPEAK)


def reads_as_instructions(answer: str) -> bool:
    """Whether the answer contains a verbatim run from the instruction half."""
    return bool(_runs(answer) & _FORBIDDEN)


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


async def run(
    message: str,
    thread_id: str,
    settings: Settings,
    *,
    check_for_resume: bool = True,
) -> AsyncIterator[BaseModel]:
    started = time.perf_counter()
    timing: dict[str, object] = {
        "event": "agent_timing",
        "model": settings.llm_model,
        "reused_thread": check_for_resume,
    }
    first_event_ms: int | None = None
    first_token_ms: int | None = None
    model_started: dict[str, float] = {}
    tool_started: dict[str, tuple[str, float]] = {}
    model_ms: list[int] = []
    tool_ms: list[dict[str, object]] = []
    tools: list[str] = []
    outcome = "incomplete"

    def elapsed_ms(since: float = started) -> int:
        return round((time.perf_counter() - since) * 1000)

    def mark_event(*, token: bool = False) -> None:
        nonlocal first_event_ms, first_token_ms
        if first_event_ms is None:
            first_event_ms = elapsed_ms()
        if token and first_token_ms is None:
            first_token_ms = elapsed_ms()

    config = {
        "recursion_limit": RECURSION_LIMIT,
        "configurable": {"thread_id": thread_id},
    }
    # aget_state needs somewhere to have saved state. Without a database the
    # graph is compiled without a checkpointer, and asking it raises.
    remembers = bool(settings.database_url)

    try:
        graph_started = time.perf_counter()
        graph = await get_graph(settings)
        timing["graph_ready_ms"] = elapsed_ms(graph_started)

        # A thread that stopped on a question is waiting for an answer, not for
        # another question. Resuming hands the reply back as the paused tool's
        # result; appending it as a new turn would leave the run paused forever
        # and answer nothing.
        resume_started = time.perf_counter()
        paused = (
            (await graph.aget_state(config)).interrupts if remembers and check_for_resume else ()
        )
        if remembers and check_for_resume:
            timing["resume_lookup_ms"] = elapsed_ms(resume_started)
        graph_input = (
            Command(resume=message) if paused else {"messages": [HumanMessage(content=message)]}
        )

        held: list[str] = []
        released = False
        leaked = False
        spoke = False
        clarification_started = False

        async for event in graph.astream_events(graph_input, config):
            kind = event["event"]
            run_id = str(event.get("run_id", "unknown"))
            if kind == "on_chat_model_start":
                model_started[run_id] = time.perf_counter()
                continue
            if kind == "on_chat_model_end":
                if model_start := model_started.pop(run_id, None):
                    model_ms.append(elapsed_ms(model_start))
                continue
            if kind == "on_tool_start":
                name = event["name"]
                tools.append(name)
                tool_started[run_id] = (name, time.perf_counter())
                if name in SILENT_TOOLS:
                    clarification_started = True
                    continue
                label = STEP_LABELS.get(name, name.replace("_", " "))
                mark_event()
                yield StepEvent(label=label)
            elif kind == "on_tool_end":
                if tool_start := tool_started.pop(run_id, None):
                    name, at = tool_start
                    tool_ms.append({"name": name, "duration_ms": elapsed_ms(at)})
            elif kind == "on_chat_model_stream":
                # The deciding turn emits tool-call chunks with no text. Only
                # the answer has any, so an empty string here is not an error.
                if not (text := getattr(event["data"]["chunk"], "text", "")) or leaked:
                    continue
                if released:
                    spoke = True
                    mark_event(token=True)
                    yield TokenEvent(text=str(text))
                    continue
                held.append(str(text))
                if sum(len(part) for part in held) < LEAK_GUARD_CHARS:
                    continue
                opening = "".join(held)
                held.clear()
                if reads_as_instructions(opening):
                    leaked = True
                    log.error("suppressed an answer echoing the prompt on thread %s", thread_id)
                    opening = TANGLED
                else:
                    released = True
                spoke = True
                mark_event(token=True)
                yield TokenEvent(text=opening)

        # An answer shorter than the guard is still held here, unreleased.
        if held and not leaked:
            opening = "".join(held)
            if reads_as_instructions(opening):
                log.error("suppressed an answer echoing the prompt on thread %s", thread_id)
                opening = TANGLED
            spoke = True
            mark_event(token=True)
            yield TokenEvent(text=opening)

        asked = False
        if remembers and clarification_started:
            clarification_started_at = time.perf_counter()
            for pending in (await graph.aget_state(config)).interrupts:
                asked = True
                mark_event()
                yield QuestionEvent(
                    text=pending.value["question"], options=pending.value["options"]
                )
            timing["clarification_lookup_ms"] = elapsed_ms(clarification_started_at)

        # A turn that produced no text used to end on `done` alone, and the
        # widget rendered an empty row that looked like kitty ignoring you. A
        # clarification legitimately has no answer text; nothing else does.
        if not spoke and not asked:
            outcome = "empty"
            mark_event(token=True)
            yield TokenEvent(text=EMPTY)
        elif asked:
            outcome = "question"
        else:
            outcome = "answer"
    except Exception as error:  # noqa: BLE001
        # A public endpoint must never show a visitor a traceback, and the
        # napping fallback is for a missing key, not for a failure mid answer.
        # Log it though: a swallowed exception here is a failure nobody can see,
        # and the friendly sentence is identical whatever went wrong.
        log.exception("agent run failed for thread %s", thread_id)
        rate_limited = is_rate_limited(error)
        outcome = "busy" if rate_limited else "broken"
        mark_event(token=True)
        yield TokenEvent(text=BUSY if rate_limited else BROKEN)
    finally:
        timing.update(
            {
                "outcome": outcome,
                "first_event_ms": first_event_ms,
                "first_token_ms": first_token_ms,
                "total_ms": elapsed_ms(),
                "model_calls": len(model_ms) + len(model_started),
                "model_ms": model_ms,
                "tools": tools,
                "tool_ms": tool_ms,
            }
        )
        log.info("agent timing %s", json.dumps(timing, separators=(",", ":")))
